"""Cell-based OCR: detect table cells first, then OCR each cell individually.

Strategy:
  1. OpenCV detects horizontal and vertical lines to build a cell grid
  2. Cells are categorized: margin labels (col 0), field labels (col 1),
     values (col 2), or full-width Q&A rows
  3. Each cell is cropped and OCR'd independently with ocrmac
  4. Results are assembled by grid position into structured text

The narrow left-margin column (col 0) is too small for reliable OCR,
so we use the full-page OCR to extract those labels (詢問, 受詢問人, etc.)
and assign them by position. For Q&A body rows, col 0 markers (問/答)
are similarly extracted from full-page OCR.

Cells where per-cell OCR fails (empty result or very low confidence)
fall back to using full-page OCR results assigned by position.
"""

import sys
import time
import tempfile
from pathlib import Path

import cv2
import numpy as np
from ocrmac import ocrmac

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}

# Minimum cell dimension (pixels) for reliable per-cell OCR
MIN_CELL_WIDTH_FOR_OCR = 120

# Padding added around cropped cells before OCR
CELL_PADDING = 25

# Low confidence threshold -- cells below this use fallback
LOW_CONFIDENCE = 0.35

# Known OCR corrections for vertical margin labels
VERTICAL_LABEL_CORRECTIONS = {
    "訽問": "詢問",
    "受訽問人": "受詢問人",
    "訽問人": "詢問人",
}

# Garbage characters from table-line misreads
GARBAGE_CHARS = set("蒔閬粢閰")


# ------------------------------------------------------------------
# Table detection
# ------------------------------------------------------------------

def detect_lines(img_gray):
    """Detect horizontal and vertical lines in a grayscale image.

    Returns:
        h_lines: list of (y_center, x_start, x_end) in pixels, sorted by y
        v_lines: list of (x_center, y_start, y_end) in pixels, sorted by x
    """
    h, w = img_gray.shape
    _, binary = cv2.threshold(img_gray, 180, 255, cv2.THRESH_BINARY_INV)

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 10, 1))
    h_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    h_contours, _ = cv2.findContours(h_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h_lines_raw = []
    for c in h_contours:
        x_c, y_c, w_c, h_c = cv2.boundingRect(c)
        h_lines_raw.append((y_c + h_c // 2, x_c, x_c + w_c))

    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 15))
    v_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
    v_contours, _ = cv2.findContours(v_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    v_lines_raw = []
    for c in v_contours:
        x_c, y_c, w_c, h_c = cv2.boundingRect(c)
        v_lines_raw.append((x_c + w_c // 2, y_c, y_c + h_c))

    h_lines = _consolidate_lines(h_lines_raw, key=0, tol=12)
    v_lines = _consolidate_lines(v_lines_raw, key=0, tol=20)
    return h_lines, v_lines


def _consolidate_lines(lines, key, tol):
    """Merge lines whose primary coordinate differs by less than tol."""
    if not lines:
        return []
    sorted_lines = sorted(lines, key=lambda l: l[key])
    groups = [[sorted_lines[0]]]
    for line in sorted_lines[1:]:
        if abs(line[key] - groups[-1][-1][key]) < tol:
            groups[-1].append(line)
        else:
            groups.append([line])
    result = []
    for g in groups:
        avg_primary = sum(l[key] for l in g) // len(g)
        min_start = min(l[1] for l in g)
        max_end = max(l[2] for l in g)
        result.append((avg_primary, min_start, max_end))
    return result


def _lines_intersect(h_line, v_line, tol=25):
    """Check whether a horizontal line and a vertical line intersect.

    An intersection exists when the h_line's x-range covers the v_line's
    x-position AND the v_line's y-range covers the h_line's y-position.
    """
    hy, hxs, hxe = h_line
    vx, vys, vye = v_line
    return (hxs - tol <= vx <= hxe + tol) and (vys - tol <= hy <= vye + tol)


def build_cell_grid(h_lines, v_lines):
    """Build a grid of cells from line intersections.

    Instead of naively slicing between every pair of adjacent horizontal
    lines, we find actual intersection points.  A cell is only created
    when all four corners are real intersections.  This correctly handles
    partial horizontal lines (e.g. a line that only spans the right half
    of the table) -- they won't split columns they don't reach.

    Merged / spanning cells arise naturally: when an interior horizontal
    line doesn't intersect a vertical line, no cell boundary is created
    at that position, so the cell extends across multiple "rows".

    Algorithm:
    For every pair of v-lines (vi_left, vi_right) that are "adjacent"
    (no v-line between them intersects both the same top and bottom
    h-lines), find h-lines that intersect BOTH.  Consecutive such h-lines
    define the top/bottom of a cell.
    """
    h_sorted = sorted(h_lines, key=lambda l: l[0])
    v_sorted = sorted(v_lines, key=lambda l: l[0])

    n_h = len(h_sorted)
    n_v = len(v_sorted)

    # Build intersection matrix
    intersects = [[False] * n_v for _ in range(n_h)]
    for hi, hl in enumerate(h_sorted):
        for vi, vl in enumerate(v_sorted):
            intersects[hi][vi] = _lines_intersect(hl, vl)

    # For each pair of v-lines, find h-lines intersecting both,
    # then create cells between consecutive such h-lines.
    cells = []
    seen_rects = set()

    for vi_left in range(n_v):
        for vi_right in range(vi_left + 1, n_v):
            # h-lines intersecting both v-lines
            common_h = [hi for hi in range(n_h)
                        if intersects[hi][vi_left] and intersects[hi][vi_right]]
            if len(common_h) < 2:
                continue

            for k in range(len(common_h) - 1):
                hi_top = common_h[k]
                hi_bot = common_h[k + 1]
                y_top = h_sorted[hi_top][0]
                y_bot = h_sorted[hi_bot][0]
                x_left = v_sorted[vi_left][0]
                x_right = v_sorted[vi_right][0]

                # Skip if an intermediate v-line also intersects both
                # hi_top and hi_bot -- that means a narrower cell should
                # be created instead of this wider one.
                blocked = False
                for vi_mid in range(vi_left + 1, vi_right):
                    if (intersects[hi_top][vi_mid] and
                            intersects[hi_bot][vi_mid]):
                        blocked = True
                        break
                if blocked:
                    continue

                rect_key = (y_top, y_bot, x_left, x_right)
                if rect_key not in seen_rects:
                    seen_rects.add(rect_key)
                    cells.append(Cell(row=-1, col=-1,
                                      x1=x_left, y1=y_top,
                                      x2=x_right, y2=y_bot))

    # Assign logical row indices.
    # Sort cells top-to-bottom; cells with the same y_top get the same row.
    cells.sort(key=lambda c: (c.y1, c.x1))
    row_idx = 0
    prev_y = None
    ROW_Y_TOL = 15
    for c in cells:
        if prev_y is None or abs(c.y1 - prev_y) > ROW_Y_TOL:
            if prev_y is not None:
                row_idx += 1
            prev_y = c.y1
        c.row = row_idx

    # Reassign col indices within each row (0-based, left to right)
    row_map = {}
    for c in cells:
        row_map.setdefault(c.row, []).append(c)
    for row_cells in row_map.values():
        row_cells.sort(key=lambda c: c.x1)
        for j, c in enumerate(row_cells):
            c.col = j

    return cells


class Cell:
    """A table cell with grid position and pixel bounds."""

    def __init__(self, row, col, x1, y1, x2, y2):
        self.row = row
        self.col = col
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.text = ""
        self.confidence = 0.0

    @property
    def width(self):
        return self.x2 - self.x1

    @property
    def height(self):
        return self.y2 - self.y1

    def __repr__(self):
        return (f"Cell(r={self.row},c={self.col},"
                f"({self.x1},{self.y1})-({self.x2},{self.y2}),"
                f"text={self.text!r})")


# ------------------------------------------------------------------
# Cell classification
# ------------------------------------------------------------------

def classify_cells(cells, v_lines):
    """Classify cells into header and body regions.

    Header rows: rows that have the label/value column split (the middle
    v-line separates label from value).
    Body rows: rows with a single wide content column (no label/value split).

    We detect the middle v-line as the one that's NOT the leftmost or
    rightmost, and that has a moderate x-position.  A row is "header" if
    it contains a cell whose right edge is near that middle v-line.
    """
    v_sorted = sorted(v_lines, key=lambda l: l[0])

    # Find the middle v-line (label/value separator).
    # It's the one with a limited y-range (only exists in the header area).
    # If there are exactly 4 v-lines, it's index 2 (0=left border,
    # 1=margin/label split, 2=label/value split, 3=right border).
    # More generally, pick the interior v-line with the shortest y-span.
    interior_v = v_sorted[1:-1] if len(v_sorted) > 2 else []
    mid_v_x = None
    if interior_v:
        # The label/value separator typically has the shortest span
        # (only exists in header rows), while the margin line spans
        # most of the page.
        mid_v = min(interior_v, key=lambda v: v[2] - v[1])
        mid_v_x = mid_v[0]

    row_map = {}
    for c in cells:
        row_map.setdefault(c.row, []).append(c)

    header_rows = set()
    body_rows = set()

    for r, row_cells in row_map.items():
        is_header = False
        if mid_v_x is not None:
            for c in row_cells:
                # A cell whose right edge aligns with the middle v-line
                # means this row has the label/value split.
                if abs(c.x2 - mid_v_x) < 30:
                    is_header = True
                    break
        if is_header:
            header_rows.add(r)
        else:
            body_rows.add(r)

    return header_rows, body_rows


# ------------------------------------------------------------------
# Per-cell OCR
# ------------------------------------------------------------------

def ocr_cell(img_color, cell, padding=CELL_PADDING):
    """Crop a cell from the image and OCR it.

    Returns (text, avg_confidence). Text preserves line structure
    with newline separators.
    """
    # Dynamic outset: large cells get more context, small cells stay tight
    min_dim = min(cell.width, cell.height)
    if min_dim > 300:
        outset = 15
    elif min_dim > 150:
        outset = 2
    else:
        outset = 0
    y1 = max(0, cell.y1 - outset)
    y2 = min(img_color.shape[0], cell.y2 + outset)
    x1 = max(0, cell.x1 - outset)
    x2 = min(img_color.shape[1], cell.x2 + outset)

    crop = img_color[y1:y2, x1:x2]
    if crop.size == 0:
        return "", 0.0

    h, w = crop.shape[:2]
    pad = padding
    padded = np.ones((h + 2 * pad, w + 2 * pad, 3), dtype=np.uint8) * 255
    padded[pad:pad + h, pad:pad + w] = crop

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        cv2.imwrite(tmp.name, padded)
        results = ocrmac.OCR(
            tmp.name,
            language_preference=["zh-Hant", "en-US"],
        ).recognize()
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    if not results:
        return "", 0.0

    # Sort results by y-position (top to bottom within the cell)
    # OCR bbox: (x, y, w, h) where y=0 is bottom in Apple Vision coords
    # So higher y = higher on page = earlier in reading order
    sorted_results = sorted(results, key=lambda r: -(r[2][1] + r[2][3] / 2))

    # Determine line-grouping threshold based on average char height.
    # This adapts to both small (1-2 line) and large (10+ line) cells.
    avg_char_h = sum(r[2][3] for r in results) / len(results)
    y_line_threshold = avg_char_h * 0.5  # half a character height

    # Group into lines by y-proximity
    lines = []
    current_line = [sorted_results[0]]
    for r in sorted_results[1:]:
        prev_cy = sum(
            (rr[2][1] + rr[2][3] / 2) for rr in current_line
        ) / len(current_line)
        curr_cy = r[2][1] + r[2][3] / 2
        if abs(prev_cy - curr_cy) <= y_line_threshold:
            current_line.append(r)
        else:
            lines.append(current_line)
            current_line = [r]
    lines.append(current_line)

    # Format: sort each line left-to-right, join fragments
    text_lines = []
    all_confs = []
    for line in lines:
        line.sort(key=lambda r: r[2][0])
        line_text = "".join(t for t, c, b in line)
        text_lines.append(line_text)
        all_confs.extend(c for t, c, b in line)

    text = "\n".join(text_lines)
    avg_conf = sum(all_confs) / len(all_confs) if all_confs else 0.0

    return text, avg_conf


# ------------------------------------------------------------------
# Full-page OCR for margin labels and fallback
# ------------------------------------------------------------------

def run_full_page_ocr(img_path):
    """Run full-page OCR and return annotations."""
    return ocrmac.OCR(
        str(img_path),
        language_preference=["zh-Hant", "en-US"],
    ).recognize()


def extract_margin_labels(annotations, cells, header_rows, img_h, img_w):
    """Extract col-0 margin labels from full-page OCR results.

    For header rows: detects vertically-written labels (詢問, 受詢問人)
    and assigns them to the correct row spans.

    For body rows: detects 問/答 markers.

    Returns dict: row_index -> label_text
    """
    if not annotations:
        return {}

    margin_texts = {}
    # Margin cells are the narrow ones (< MIN_CELL_WIDTH_FOR_OCR pixels wide)
    margin_cells = [c for c in cells if c.width < MIN_CELL_WIDTH_FOR_OCR]

    # For each margin cell, collect the single-char annotations that fall
    # within it.  Characters in the same margin cell form one label.
    # This naturally handles span boundaries -- if 詢 and 問 are in one
    # margin cell (r1, y=245-521) and 案 is in a different one (r3,
    # y=521-613), they'll be separate labels.
    for mc in margin_cells:
        cell_chars = []  # (char, conf, px_cy)
        cell_markers = []  # (marker_text, px_cy) for 問/答

        for text, conf, bbox in annotations:
            stripped = text.strip()
            if not stripped:
                continue

            bx, by, bw, bh = bbox
            px_x = bx * img_w
            px_cy = img_h * (1.0 - (by + bh / 2))

            # Check if annotation falls within this margin cell
            if not (mc.x1 - 10 <= px_x <= mc.x2 + 10 and
                    mc.y1 - 10 <= px_cy <= mc.y2 + 10):
                continue

            if mc.row in header_rows:
                if len(stripped) == 1 and stripped not in GARBAGE_CHARS:
                    cell_chars.append((stripped, conf, px_cy))
            else:
                if stripped in ("問", "答"):
                    cell_markers.append((stripped, px_cy))

        if cell_chars:
            # Sort top-to-bottom and join
            cell_chars.sort(key=lambda x: x[2])
            merged_text = "".join(ch for ch, _, _ in cell_chars)
            merged_text = VERTICAL_LABEL_CORRECTIONS.get(
                merged_text, merged_text)
            margin_texts[mc.row] = merged_text

        if cell_markers:
            # Pick the first marker (there should be only one per cell)
            cell_markers.sort(key=lambda x: x[1])
            margin_texts[mc.row] = cell_markers[0][0]

    return margin_texts


def extract_fallback_text(annotations, cell, img_h, img_w):
    """Extract text from full-page OCR for a specific cell region.

    Used when per-cell OCR fails (empty or low confidence).
    """
    if not annotations:
        return ""

    cell_texts = []
    for text, conf, bbox in annotations:
        stripped = text.strip()
        if not stripped:
            continue
        if len(stripped) == 1 and stripped in GARBAGE_CHARS:
            continue

        bx, by, bw, bh = bbox
        px_cx = (bx + bw / 2) * img_w
        px_cy = img_h * (1.0 - (by + bh / 2))

        # Check if center falls within this cell (with tolerance)
        if (cell.x1 - 5 <= px_cx <= cell.x2 + 5 and
                cell.y1 - 5 <= px_cy <= cell.y2 + 5):
            py_top = img_h * (1.0 - (by + bh))
            cell_texts.append((stripped, conf, py_top))

    if not cell_texts:
        return ""

    # Sort top to bottom, then join
    cell_texts.sort(key=lambda x: x[2])
    return "".join(t for t, c, py in cell_texts)


# ------------------------------------------------------------------
# Assembly
# ------------------------------------------------------------------

def assemble_output(cells, header_rows, body_rows, margin_texts, v_lines):
    """Assemble cells into structured text output.

    Cell roles are identified by x-position, not column index:
    - Margin cell: narrow cell on the far left (x1 near leftmost v-line)
    - Label cell: cell whose right edge aligns with the middle v-line
    - Value cell: cell whose left edge aligns with the middle v-line
    - Content cell: wide cell in body rows (no label/value split)
    """
    v_sorted = sorted(v_lines, key=lambda l: l[0])
    # Middle v-line = the interior v-line with shortest y-span
    interior_v = v_sorted[1:-1] if len(v_sorted) > 2 else []
    mid_v_x = None
    if interior_v:
        mid_v = min(interior_v, key=lambda v: v[2] - v[1])
        mid_v_x = mid_v[0]

    def is_margin_cell(c):
        """Narrow cell on the far left (margin column)."""
        return c.width < MIN_CELL_WIDTH_FOR_OCR

    def is_label_cell(c):
        """Cell whose right edge aligns with the middle v-line."""
        if mid_v_x is None:
            return False
        return abs(c.x2 - mid_v_x) < 30

    def is_value_cell(c):
        """Cell whose left edge aligns with the middle v-line."""
        if mid_v_x is None:
            return False
        return abs(c.x1 - mid_v_x) < 30

    row_map = {}
    for c in cells:
        row_map.setdefault(c.row, []).append(c)
    for row in row_map.values():
        row.sort(key=lambda c: c.x1)

    lines = []
    max_row = max(c.row for c in cells)
    emitted_margins = set()

    for r in range(max_row + 1):
        if r not in row_map:
            continue

        row_cells = row_map[r]

        if r in header_rows:
            # Find label and value cells by x-position
            label_text = ""
            value_text = ""
            for c in row_cells:
                if is_margin_cell(c):
                    continue  # skip margin column
                if is_label_cell(c):
                    label_text = c.text.strip()
                elif is_value_cell(c):
                    value_text = c.text.strip()

            # Emit margin label if new and not yet emitted.
            # Suppress single-char margin labels that are already part of
            # the label cell text (e.g. margin "案" when label is "案由").
            margin_label = ""
            for mr, mt in sorted(margin_texts.items()):
                if mr <= r and mr not in emitted_margins and mr in header_rows:
                    # Skip single-char margin labels redundant with the
                    # label cell on the same row
                    if (len(mt) == 1 and label_text and
                            mt in label_text):
                        emitted_margins.add(mr)
                        continue
                    margin_label = mt
                    emitted_margins.add(mr)

            if margin_label:
                lines.append(margin_label)

            if label_text and value_text:
                lines.append(f"{label_text}  {value_text}")
            elif label_text:
                lines.append(label_text)
            elif value_text:
                lines.append(value_text)

        else:
            # Body row
            marker = margin_texts.get(r, "")
            content_parts = []
            for c in row_cells:
                if is_margin_cell(c):
                    continue  # skip margin column
                if c.text.strip():
                    content_parts.append(c.text.strip())

            content = "\n".join(content_parts) if content_parts else ""

            if marker and content:
                content_lines = content.split("\n")
                content_lines[0] = f"{marker}  {content_lines[0]}"
                lines.extend(content_lines)
            elif content:
                lines.extend(content.split("\n"))
            elif marker:
                lines.append(marker)

    return "\n".join(lines)


# ------------------------------------------------------------------
# Main pipeline
# ------------------------------------------------------------------

def save_debug_cells(img_color, cells, h_lines, v_lines, img_stem, debug_dir):
    """Save each cell as a separate PNG + an annotated full image showing the grid."""
    debug_dir.mkdir(parents=True, exist_ok=True)

    # Draw grid on full image
    annotated = img_color.copy()
    for y, xs, xe in h_lines:
        cv2.line(annotated, (xs, y), (xe, y), (0, 0, 255), 2)
    for x, ys, ye in v_lines:
        cv2.line(annotated, (x, ys), (x, ye), (255, 0, 0), 2)
    for c in cells:
        cv2.putText(annotated, f"r{c.row}c{c.col}", (c.x1 + 5, c.y1 + 20),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 180, 0), 1)
    cv2.imwrite(str(debug_dir / f"{img_stem}_grid.png"), annotated)

    # Save each cell
    for c in cells:
        crop = img_color[max(0, c.y1):c.y2, max(0, c.x1):c.x2]
        if crop.size > 0:
            cv2.imwrite(str(debug_dir / f"{img_stem}_r{c.row}_c{c.col}.png"), crop)


def process_image(image_path: str, debug=False) -> str:
    """Full pipeline: detect cells, OCR each, assemble output."""
    img_path = Path(image_path)
    img_color = cv2.imread(str(img_path))
    if img_color is None:
        return f"(failed to read {img_path})"
    img_gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
    img_h, img_w = img_gray.shape

    # Step 1: Detect table structure
    h_lines, v_lines = detect_lines(img_gray)
    cells = build_cell_grid(h_lines, v_lines)
    print(f"  [grid] h_lines={len(h_lines)}, v_lines={len(v_lines)}, cells={len(cells)}")

    if debug:
        debug_dir = Path(__file__).parent / "debug-cells"
        save_debug_cells(img_color, cells, h_lines, v_lines, img_path.stem, debug_dir)

    # Step 2: Classify cells
    header_rows, body_rows = classify_cells(cells, v_lines)
    print(f"  [classify] header={len(header_rows)} body={len(body_rows)}")

    # Step 3: Full-page OCR (used for margin labels + fallback)
    full_annotations = run_full_page_ocr(img_path)
    print(f"  [full-ocr] {len(full_annotations)} annotations")

    # Step 4: Extract margin labels
    margin_texts = extract_margin_labels(
        full_annotations, cells, header_rows, img_h, img_w
    )
    print(f"  [margins] {dict(margin_texts)}")

    # Step 5: Assign full-page OCR text to cells by position (hybrid approach)
    # Uses full-page OCR for best character recognition + cell grid for structure
    for cell in cells:
        cell.text = extract_fallback_text(
            full_annotations, cell, img_h, img_w
        )
        cell.confidence = 0.5

    print(f"  [hybrid] assigned full-page OCR text to {len(cells)} cells")

    # Step 6: Assemble
    output = assemble_output(cells, header_rows, body_rows, margin_texts, v_lines)
    return output


def find_images(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../input-image-zh-tw")

    if folder.is_file():
        images = [folder]
        folder = folder.parent
    elif folder.is_dir():
        images = find_images(folder)
    else:
        print(f"Error: '{folder}' is not a file or directory.")
        sys.exit(1)

    if not images:
        print(f"No images found in {folder}")
        return

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    print("Apple Vision OCR -- Cell-Based (smart-v2)")
    print("=" * 60)
    print(f"Folder : {folder}")
    print(f"Images : {len(images)}")
    print("=" * 60)
    print()

    total_time = 0.0
    for img_path in images:
        print(f"--- {img_path.name} ---")

        debug = "--debug" in sys.argv
        start = time.perf_counter()
        text = process_image(str(img_path), debug=debug)
        elapsed = time.perf_counter() - start
        total_time += elapsed

        display = text if len(text) <= 800 else text[:800] + "\n... (truncated)"
        print(display)
        print(f"  [{elapsed:.3f}s]\n")

        out_file = results_dir / f"{img_path.stem}.txt"
        out_file.write_text(text, encoding="utf-8")

    print("=" * 60)
    print(f"Total images : {len(images)}")
    print(f"Total time   : {total_time:.3f}s")
    print(f"Average time : {total_time / len(images):.3f}s per image")
    print(f"Results in   : {results_dir.resolve()}")


if __name__ == "__main__":
    main()
