"""
Surya OCR + OpenCV grid detection hybrid.

Same approach as apple-ocr-opencv but using Surya for text recognition:
  1. OpenCV detects table grid lines → build cell structure
  2. Surya runs whole-page OCR → get text + pixel bounding boxes
  3. Assign Surya text to cells based on coordinate overlap

Usage:
    uv run python run_ocr_opencv.py [folder_path]
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from surya.detection import DetectionPredictor
from surya.foundation import FoundationPredictor
from surya.recognition import RecognitionPredictor
from surya.common.surya.schema import TaskNames


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}
MIN_CELL_WIDTH_FOR_OCR = 120


# ------------------------------------------------------------------
# OpenCV grid detection (ported from apple-ocr-opencv)
# ------------------------------------------------------------------

def detect_lines(img_gray):
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
    hy, hxs, hxe = h_line
    vx, vys, vye = v_line
    return (hxs - tol <= vx <= hxe + tol) and (vys - tol <= hy <= vye + tol)


class Cell:
    def __init__(self, row, col, x1, y1, x2, y2):
        self.row = row
        self.col = col
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.text = ""

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


def build_cell_grid(h_lines, v_lines):
    h_sorted = sorted(h_lines, key=lambda l: l[0])
    v_sorted = sorted(v_lines, key=lambda l: l[0])

    n_h = len(h_sorted)
    n_v = len(v_sorted)

    intersects = [[False] * n_v for _ in range(n_h)]
    for hi, hl in enumerate(h_sorted):
        for vi, vl in enumerate(v_sorted):
            intersects[hi][vi] = _lines_intersect(hl, vl)

    cells = []
    seen_rects = set()

    for vi_left in range(n_v):
        for vi_right in range(vi_left + 1, n_v):
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

    row_map = {}
    for c in cells:
        row_map.setdefault(c.row, []).append(c)
    for row_cells in row_map.values():
        row_cells.sort(key=lambda c: c.x1)
        for j, c in enumerate(row_cells):
            c.col = j

    return cells


def classify_cells(cells, v_lines):
    v_sorted = sorted(v_lines, key=lambda l: l[0])
    interior_v = v_sorted[1:-1] if len(v_sorted) > 2 else []
    mid_v_x = None
    if interior_v:
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
                if abs(c.x2 - mid_v_x) < 30:
                    is_header = True
                    break
        if is_header:
            header_rows.add(r)
        else:
            body_rows.add(r)

    return header_rows, body_rows


# ------------------------------------------------------------------
# Surya OCR → assign text to cells
# ------------------------------------------------------------------

def run_surya_ocr(image_path, rec_predictor, det_predictor):
    """Run Surya whole-page OCR. Returns list of (text, bbox, confidence).

    bbox is [x1, y1, x2, y2] in pixels.
    """
    image = Image.open(image_path).convert("RGB")
    results = rec_predictor(
        [image],
        task_names=[TaskNames.ocr_with_boxes],
        det_predictor=det_predictor,
    )
    ocr_result = results[0]

    annotations = []
    for tl in ocr_result.text_lines:
        # tl.bbox = [x1, y1, x2, y2] in pixels
        annotations.append((tl.text, tl.bbox, tl.confidence))
        # Also collect individual words for finer-grained assignment
        if hasattr(tl, 'words') and tl.words:
            for w in tl.words:
                if w.text.strip():
                    annotations.append((w.text, w.bbox, w.confidence))

    return annotations, ocr_result


def assign_text_to_cells(annotations, cells):
    """Assign Surya OCR text to cells based on bbox overlap.

    All text within a cell is joined into a single line (no line breaks).
    The cell is the structural unit — line breaks come from cell boundaries,
    not from visual line wrapping within a cell.
    """
    for cell in cells:
        cell_texts = []

        for text, bbox, conf in annotations:
            stripped = text.strip()
            if not stripped:
                continue

            # bbox = [x1, y1, x2, y2]
            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2

            # Check if center falls within cell (with tolerance)
            if (cell.x1 - 5 <= cx <= cell.x2 + 5 and
                    cell.y1 - 5 <= cy <= cell.y2 + 5):
                cell_texts.append((stripped, cy, bbox[0]))  # text, y_center, x_start

        if cell_texts:
            # Sort top-to-bottom, then left-to-right
            cell_texts.sort(key=lambda x: (x[1], x[2]))
            # Deduplicate: if a word is a substring of a line on the same y,
            # skip the word (keep lines only)
            deduped = []
            for t, y, x in cell_texts:
                is_substring = False
                for existing_t, existing_y, _ in deduped:
                    if abs(y - existing_y) < 20 and t in existing_t and t != existing_t:
                        is_substring = True
                        break
                if not is_substring:
                    deduped.append((t, y, x))

            # Join all text in this cell into one line — no line breaks within a cell
            cell.text = "".join(t for t, _, _ in deduped)


def extract_margin_labels(annotations, cells, header_rows):
    """Extract margin labels (問/答, 詢問, etc.) from Surya annotations."""
    margin_texts = {}
    margin_cells = [c for c in cells if c.width < MIN_CELL_WIDTH_FOR_OCR]

    for mc in margin_cells:
        cell_chars = []

        for text, bbox, conf in annotations:
            stripped = text.strip()
            if not stripped:
                continue

            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2

            if (mc.x1 - 10 <= cx <= mc.x2 + 10 and
                    mc.y1 - 10 <= cy <= mc.y2 + 10):
                cell_chars.append((stripped, cy))

        if cell_chars:
            cell_chars.sort(key=lambda x: x[1])
            # Join all text found in this margin cell
            margin_texts[mc.row] = "".join(t for t, _ in cell_chars)

    return margin_texts


# ------------------------------------------------------------------
# Assembly (same as apple-ocr-opencv)
# ------------------------------------------------------------------

def assemble_output(cells, header_rows, body_rows, margin_texts, v_lines):
    v_sorted = sorted(v_lines, key=lambda l: l[0])
    interior_v = v_sorted[1:-1] if len(v_sorted) > 2 else []
    mid_v_x = None
    if interior_v:
        mid_v = min(interior_v, key=lambda v: v[2] - v[1])
        mid_v_x = mid_v[0]

    def is_margin_cell(c):
        return c.width < MIN_CELL_WIDTH_FOR_OCR

    def is_label_cell(c):
        if mid_v_x is None:
            return False
        return abs(c.x2 - mid_v_x) < 30

    def is_value_cell(c):
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
            label_text = ""
            value_text = ""
            for c in row_cells:
                if is_margin_cell(c):
                    continue
                if is_label_cell(c):
                    label_text = c.text.strip()
                elif is_value_cell(c):
                    value_text = c.text.strip()

            margin_label = ""
            for mr, mt in sorted(margin_texts.items()):
                if mr <= r and mr not in emitted_margins and mr in header_rows:
                    if len(mt) == 1 and label_text and mt in label_text:
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
            marker = margin_texts.get(r, "")
            content_parts = []
            for c in row_cells:
                if is_margin_cell(c):
                    continue
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

def process_image(image_path, rec_predictor, det_predictor):
    img_path = Path(image_path)
    img_color = cv2.imread(str(img_path))
    if img_color is None:
        return f"(failed to read {img_path})"
    img_gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)

    # Step 1: OpenCV grid detection
    h_lines, v_lines = detect_lines(img_gray)
    cells = build_cell_grid(h_lines, v_lines)
    print(f"  [grid] h_lines={len(h_lines)}, v_lines={len(v_lines)}, cells={len(cells)}")

    # Step 2: Surya whole-page OCR
    annotations, ocr_result = run_surya_ocr(str(img_path), rec_predictor, det_predictor)
    print(f"  [surya] {len(ocr_result.text_lines)} text lines detected")

    if not cells:
        # No table structure — just return Surya text in reading order
        lines = [tl.text for tl in ocr_result.text_lines]
        return "\n".join(lines)

    # Step 3: Classify cells
    header_rows, body_rows = classify_cells(cells, v_lines)
    print(f"  [classify] header={len(header_rows)} body={len(body_rows)}")

    # Step 4: Assign Surya text to cells by coordinate overlap
    assign_text_to_cells(annotations, cells)

    # Step 5: Extract margin labels
    margin_texts = extract_margin_labels(annotations, cells, header_rows)
    print(f"  [margins] {dict(margin_texts)}")

    # Step 6: Assemble
    output = assemble_output(cells, header_rows, body_rows, margin_texts, v_lines)
    return output


def collect_images(folder):
    folder_path = Path(folder)
    if not folder_path.is_dir():
        print(f"Error: '{folder}' is not a directory.")
        sys.exit(1)
    files = sorted(
        p for p in folder_path.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS and not p.name.startswith(".")
    )
    if not files:
        print(f"No image files found in '{folder}'.")
        sys.exit(1)
    return files


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "../../input-image-zh-tw"
    image_paths = collect_images(folder)
    print(f"Found {len(image_paths)} image(s) in '{folder}'.\n")

    results_dir = Path("results-opencv")
    results_dir.mkdir(exist_ok=True)

    # Load Surya models once
    print("Loading Surya models...")
    t0 = time.time()
    foundation_predictor = FoundationPredictor()
    det_predictor = DetectionPredictor()
    rec_predictor = RecognitionPredictor(foundation_predictor)
    print(f"Models loaded in {time.time() - t0:.1f}s\n")

    separator = "-" * 60
    total_time = 0.0
    summary_rows = []

    for img_path in image_paths:
        print(separator)
        print(f"Processing: {img_path.name}")

        start = time.time()
        text = process_image(str(img_path), rec_predictor, det_predictor)
        elapsed = time.time() - start
        total_time += elapsed

        line_count = len(text.split("\n"))
        print(f"Time: {elapsed:.2f}s | Lines: {line_count}")
        print()
        # Show first 500 chars
        display = text if len(text) <= 500 else text[:500] + "\n... (truncated)"
        print(display)
        print()

        out_file = results_dir / f"{img_path.stem}.txt"
        out_file.write_text(text, encoding="utf-8")
        print(f"Saved -> {out_file}")

        summary_rows.append((img_path.name, elapsed, line_count))

    print("\n" + "=" * 60)
    print("SUMMARY — Surya OCR + OpenCV Grid")
    print("=" * 60)
    print(f"{'Filename':<35} {'Time':>8} {'Lines':>6}")
    print("-" * 60)
    for name, secs, lc in summary_rows:
        print(f"{name:<35} {secs:>7.2f}s {lc:>6}")
    print("-" * 60)
    print(f"{'Total':<35} {total_time:>7.2f}s {sum(r[2] for r in summary_rows):>6}")
    print(f"\nResults saved to: {results_dir.resolve()}")


if __name__ == "__main__":
    main()
