"""Apple Vision OCR with smart post-processing for tables/forms.

Improvements over run_ocr.py:
  1. Filters low-confidence garbage characters (table lines misread as chars)
  2. Uses OpenCV to detect table lines (horizontal/vertical) for cell boundaries
  3. Only merges vertical text within the same table cell (or spanning column)
  4. Uses table row boundaries for grouping
  5. Pairs labels with values using detected column separators
  6. Handles Q&A section markers (問/答) properly

Coordinate system note:
  Apple Vision uses normalized 0-1 coordinates where y=0 is the BOTTOM of image.
  Bounding box = (x, y, w, h) where (x, y) is the bottom-left corner.
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np
from ocrmac import ocrmac

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}

# --- Tuning constants ---
VERTICAL_X_TOLERANCE = 0.025     # Max x-center difference for vertical text
VERTICAL_Y_GAP_MAX = 0.045      # Max gap between consecutive chars in a vertical run
ROW_Y_TOLERANCE = 0.012          # Fallback: max y-center difference for "same row"
LABEL_VALUE_GAP_MIN = 0.02      # Min x gap between label end and value start

# Characters commonly produced by OCR misreading table borders/lines.
GARBAGE_CHARS = set("蒔閬粢閰")

# Known vertical text corrections (OCR error -> correct text).
VERTICAL_TEXT_CORRECTIONS = {
    "訽問人": "詢問人",
    "受訽問人": "受詢問人",
    "訽問": "詢問",
}

# Q&A markers: single chars that appear in the left margin of Q&A sections.
# These should NOT be merged with each other vertically.
QA_MARKERS = set("問答")


def find_images(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def center_of(bbox):
    x, y, w, h = bbox
    return x + w / 2, y + h / 2

def top_of(bbox):
    return bbox[1] + bbox[3]

def bottom_of(bbox):
    return bbox[1]

def right_of(bbox):
    return bbox[0] + bbox[2]

def left_of(bbox):
    return bbox[0]


# ------------------------------------------------------------------
# Table line detection with OpenCV
# ------------------------------------------------------------------
class TableGrid:
    """Detected table lines from an image, providing cell boundary queries."""

    def __init__(self, h_lines, v_columns):
        """
        h_lines: sorted list of y positions (Apple Vision coords, descending = top first)
        v_columns: sorted list of x positions for consolidated vertical column boundaries
        """
        self.h_lines = sorted(h_lines, reverse=True)  # top first
        self.v_columns = sorted(v_columns)  # left to right
        self.has_table = len(h_lines) >= 2 and len(v_columns) >= 2

        # Identify the "spanning column" -- the leftmost narrow column
        # where labels like 詢問, 受詢問人 span multiple rows vertically.
        self.spanning_col = 1 if len(v_columns) >= 3 else -1

        # Determine the form header boundary (where structured table ends
        # and the Q&A body begins). This is approximately where the label
        # column's internal vertical lines stop.
        self.form_body_boundary = self._detect_form_body_boundary()

    def _detect_form_body_boundary(self):
        """Find the y-position where the form transitions from structured
        header (with label/value columns) to the Q&A body section.

        Returns a y-position (Apple Vision coords) or 0 if not determinable.
        """
        if not self.has_table or len(self.h_lines) < 4:
            return 0

        # The Q&A body starts roughly at the y-position where the table
        # becomes full-width (no internal column dividers). Look for
        # horizontal lines that span from the left edge to the right edge
        # without internal vertical boundaries.
        #
        # Heuristic: the form body starts below the row containing
        # 家庭經濟狀況 (economic status). This is typically in the lower
        # half of the structured table (y ~ 0.47-0.52).
        #
        # Use the bottom third of horizontal lines as the transition zone.
        n = len(self.h_lines)
        # The transition is typically around the middle set of h_lines
        # For a typical form, h_lines from index n//3 to 2*n//3 span
        # the field label area.
        if n >= 10:
            # Return the h_line that roughly separates header from body
            # This is around the 50-60% mark of the total h_lines
            mid_idx = int(n * 0.55)
            return self.h_lines[min(mid_idx, n - 1)]
        return 0

    @classmethod
    def from_image(cls, image_path: str) -> "TableGrid":
        """Detect horizontal and vertical lines from an image."""
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return cls([], [])
        h, w = img.shape

        # Binarize (invert so lines are white)
        _, binary = cv2.threshold(img, 180, 255, cv2.THRESH_BINARY_INV)

        # Detect horizontal lines (need to be at least 1/10 of image width)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 10, 1))
        h_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

        # Detect vertical lines (need to be at least 1/15 of image height)
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 15))
        v_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

        # Extract horizontal line y-positions
        h_contours, _ = cv2.findContours(h_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h_lines = []
        for c in h_contours:
            _, y_c, _, h_c = cv2.boundingRect(c)
            y_norm = 1.0 - (y_c + h_c / 2) / h
            h_lines.append(y_norm)

        # Extract vertical line segments
        v_contours, _ = cv2.findContours(v_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        v_segments = []
        for c in v_contours:
            x_c, y_c, w_c, h_c = cv2.boundingRect(c)
            x_norm = (x_c + w_c / 2) / w
            v_segments.append(x_norm)

        # Consolidate vertical line segments at similar x positions.
        v_columns = _consolidate_x_positions(v_segments, tolerance=0.015)

        return cls(h_lines, v_columns)

    def get_cell_column(self, cx):
        """Return the column index for an x-center position."""
        if not self.has_table:
            return -1

        for i, vx in enumerate(self.v_columns):
            if cx < vx + 0.005:
                return i
        return len(self.v_columns)

    def get_row_band(self, cy):
        """Return the row band index for a y-center position."""
        if len(self.h_lines) < 2:
            return -1

        for i in range(len(self.h_lines) - 1):
            if self.h_lines[i] >= cy >= self.h_lines[i + 1]:
                return i
        if cy > self.h_lines[0]:
            return -1
        return len(self.h_lines)

    def is_spanning_column(self, cx):
        """Check if an x position falls in the spanning (left-margin) column."""
        return self.spanning_col >= 0 and self.get_cell_column(cx) == self.spanning_col

    def is_in_form_header(self, cy):
        """Check if a y-position is in the structured form header (not Q&A body)."""
        return cy > self.form_body_boundary

    def same_cell(self, bbox1, bbox2, allow_spanning=False):
        """Check if two bboxes are in the same table cell."""
        if not self.has_table:
            return True

        cx1, cy1 = center_of(bbox1)
        cx2, cy2 = center_of(bbox2)

        col1 = self.get_cell_column(cx1)
        col2 = self.get_cell_column(cx2)

        if col1 != col2:
            return False

        # In the spanning column AND in the form header, allow cross-row merging
        if (allow_spanning and self.is_spanning_column(cx1)
                and self.is_in_form_header(cy1) and self.is_in_form_header(cy2)):
            return True

        # Otherwise, must be in the same row band
        row1 = self.get_row_band(cy1)
        row2 = self.get_row_band(cy2)

        return row1 == row2

    def get_label_value_boundary(self):
        """Return the x position of the label-value column boundary."""
        if len(self.v_columns) < 3:
            return None
        for vx in self.v_columns:
            if 0.15 < vx < 0.30:
                return vx
        return None


def _consolidate_x_positions(positions, tolerance=0.015):
    """Consolidate nearby x positions into unique column positions."""
    if not positions:
        return []
    sorted_pos = sorted(positions)
    groups = [[sorted_pos[0]]]
    for p in sorted_pos[1:]:
        if p - groups[-1][-1] <= tolerance:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [sum(g) / len(g) for g in groups]


# ------------------------------------------------------------------
# Step 1: Filter garbage
# ------------------------------------------------------------------
def filter_garbage(annotations):
    """Remove annotations that are OCR artifacts from table lines."""
    result = []
    for text, conf, bbox in annotations:
        stripped = text.strip()
        if len(stripped) == 1 and stripped in GARBAGE_CHARS:
            continue
        result.append((text, conf, bbox))
    return result


# ------------------------------------------------------------------
# Step 2: Merge vertical text (cell-aware, with spanning support)
# ------------------------------------------------------------------
def merge_vertical_runs(annotations, grid: TableGrid):
    """Find SINGLE-CHARACTER annotations stacked vertically and merge them.

    Rules:
    - Only merge single chars that are vertically adjacent (similar x, sequential y)
    - In the form header's spanning column, allow cross-row merging for labels
    - Never merge 問 with 答 (these are independent Q&A markers)
    - In the Q&A body, don't merge across row boundaries
    """
    singles = []
    others = []
    for i, (text, conf, bbox) in enumerate(annotations):
        if len(text.strip()) == 1:
            singles.append((i, text.strip(), conf, bbox))
        else:
            others.append((text, conf, bbox))

    if not singles:
        return list(annotations)

    # Sort singles by y descending (top of page first visually)
    singles.sort(key=lambda c: -center_of(c[3])[1])

    used = set()
    merged = []

    for ci, (idx, text, conf, bbox) in enumerate(singles):
        if idx in used:
            continue

        run = [(idx, text, conf, bbox)]
        used.add(idx)

        current_bottom = bottom_of(bbox)
        current_cx = center_of(bbox)[0]

        for cj in range(ci + 1, len(singles)):
            jdx, jtext, jconf, jbbox = singles[cj]
            if jdx in used:
                continue

            jcx = center_of(jbbox)[0]
            j_top = top_of(jbbox)

            # Must be in similar x column
            if abs(jcx - current_cx) > VERTICAL_X_TOLERANCE:
                continue

            # Gap check
            gap = current_bottom - j_top
            if gap < -0.005:
                continue
            if gap > VERTICAL_Y_GAP_MAX:
                continue

            # Don't merge 問 with 答 or vice versa
            last_char = run[-1][1]
            if (last_char in QA_MARKERS and jtext in QA_MARKERS
                    and last_char != jtext):
                continue

            # Cell-awareness
            if grid.has_table and not grid.same_cell(bbox, jbbox, allow_spanning=True):
                continue

            run.append((jdx, jtext, jconf, jbbox))
            used.add(jdx)
            current_bottom = bottom_of(jbbox)
            current_cx = jcx

        if len(run) >= 2:
            combined_text = "".join(r[1] for r in run)
            avg_conf = sum(r[2] for r in run) / len(run)
            min_x = min(left_of(r[3]) for r in run)
            max_x = max(right_of(r[3]) for r in run)
            min_y = min(bottom_of(r[3]) for r in run)
            max_y = max(top_of(r[3]) for r in run)
            merged_bbox = [min_x, min_y, max_x - min_x, max_y - min_y]

            # Apply known corrections
            if combined_text in VERTICAL_TEXT_CORRECTIONS:
                combined_text = VERTICAL_TEXT_CORRECTIONS[combined_text]

            merged.append((combined_text, avg_conf, merged_bbox))
        else:
            merged.append((text, conf, bbox))

    merged.extend(others)
    return merged


# ------------------------------------------------------------------
# Step 3: Merge horizontally-split single chars in same row/cell
# ------------------------------------------------------------------
def merge_horizontal_pairs(annotations, grid: TableGrid):
    """Merge single characters that are side-by-side in the same table row.

    Handles cases like 性+別, 職+業, 地+點, 案+由 where OCR splits a
    2-char label into individual chars.
    """
    if not annotations:
        return annotations

    HORIZONTAL_Y_TOL = 0.012
    HORIZONTAL_X_GAP_MAX = 0.08

    singles = []
    others = []
    for i, (text, conf, bbox) in enumerate(annotations):
        if len(text.strip()) == 1:
            singles.append((i, text.strip(), conf, bbox))
        else:
            others.append((text, conf, bbox))

    if not singles:
        return list(annotations)

    singles.sort(key=lambda s: (-center_of(s[3])[1], left_of(s[3])))

    used = set()
    merged = []

    for si, (idx, text, conf, bbox) in enumerate(singles):
        if idx in used:
            continue

        run_text = text
        run_conf = conf
        run_bbox = list(bbox)
        current_right = right_of(bbox)
        current_cy = center_of(bbox)[1]

        for sj in range(si + 1, len(singles)):
            jdx, jtext, jconf, jbbox = singles[sj]
            if jdx in used:
                continue

            jcy = center_of(jbbox)[1]
            jleft = left_of(jbbox)

            if abs(jcy - current_cy) > HORIZONTAL_Y_TOL:
                break

            x_gap = jleft - current_right
            if x_gap < -0.01 or x_gap > HORIZONTAL_X_GAP_MAX:
                continue

            if grid.has_table and not grid.same_cell(run_bbox, jbbox, allow_spanning=False):
                continue

            run_text += jtext
            run_conf = (run_conf + jconf) / 2
            new_right = right_of(jbbox)
            run_bbox[2] = new_right - run_bbox[0]
            current_right = new_right
            used.add(jdx)

        merged.append((run_text, run_conf, run_bbox))

    merged.extend(others)
    return merged


# ------------------------------------------------------------------
# Step 4: Group into rows using table lines
# ------------------------------------------------------------------
def group_into_rows(annotations, grid: TableGrid, y_tolerance=ROW_Y_TOLERANCE):
    """Group annotations into rows.

    For the form header: uses horizontal lines as row boundaries,
    with spanning-column items placed at the top of their span.

    For Q&A body: merges 問/答 markers with adjacent text on the same row.
    """
    if not annotations:
        return []

    sorted_anns = sorted(annotations, key=lambda a: -center_of(a[2])[1])

    if grid.has_table and len(grid.h_lines) >= 2:
        h_lines = sorted(grid.h_lines, reverse=True)

        # Separate spanning-column items from regular items
        spanning_items = []
        regular_items = []
        for ann in sorted_anns:
            cx = center_of(ann[2])[0]
            cy = center_of(ann[2])[1]
            # Only treat items in the form header's spanning column specially
            if grid.is_spanning_column(cx) and grid.is_in_form_header(cy):
                spanning_items.append(ann)
            else:
                regular_items.append(ann)

        # Group regular items by row band, then split by y-proximity
        row_bands = {}
        for ann in regular_items:
            cy = center_of(ann[2])[1]
            band_idx = grid.get_row_band(cy)
            if band_idx not in row_bands:
                row_bands[band_idx] = []
            row_bands[band_idx].append(ann)

        rows = []
        for band_idx in sorted(row_bands.keys()):
            band = row_bands[band_idx]
            band.sort(key=lambda a: -center_of(a[2])[1])
            sub_rows = _split_by_y_proximity(band, y_tolerance)
            rows.extend(sub_rows)

        # Insert spanning items at the top of their vertical span
        for sp_ann in spanning_items:
            sp_cy = center_of(sp_ann[2])[1]
            insert_idx = len(rows)
            for i, row in enumerate(rows):
                row_max_y = max(center_of(item[2])[1] for item in row)
                if sp_cy > row_max_y:
                    insert_idx = i
                    break
            rows.insert(insert_idx, [sp_ann])

    else:
        rows = _split_by_y_proximity(sorted_anns, y_tolerance)

    # Sort items within each row left to right
    for row in rows:
        row.sort(key=lambda a: left_of(a[2]))

    return rows


def _split_by_y_proximity(sorted_anns, y_tolerance):
    """Split a list of annotations (sorted by y descending) into rows by y-proximity."""
    if not sorted_anns:
        return []

    rows = []
    current_row = [sorted_anns[0]]
    row_y_sum = center_of(sorted_anns[0][2])[1]

    for ann in sorted_anns[1:]:
        cy = center_of(ann[2])[1]
        row_y_avg = row_y_sum / len(current_row)
        if abs(cy - row_y_avg) <= y_tolerance:
            current_row.append(ann)
            row_y_sum += cy
        else:
            rows.append(current_row)
            current_row = [ann]
            row_y_sum = cy

    if current_row:
        rows.append(current_row)

    return rows


# ------------------------------------------------------------------
# Step 5: Format rows
# ------------------------------------------------------------------
def format_row(row_items, grid: TableGrid):
    """Format a row of annotations into a readable line."""
    if len(row_items) == 1:
        return row_items[0][0]

    label_boundary = grid.get_label_value_boundary() if grid.has_table else None

    if label_boundary:
        labels = []
        values = []
        for item in row_items:
            cx = center_of(item[2])[0]
            if cx < label_boundary:
                labels.append(item)
            else:
                values.append(item)

        if labels and values:
            label_text = "  ".join(item[0] for item in labels)
            value_text = "  ".join(item[0] for item in values)
            return f"{label_text}  {value_text}"
        elif labels:
            return "  ".join(item[0] for item in labels)
        elif values:
            return "  ".join(item[0] for item in values)

    return "  ".join(item[0] for item in row_items)


def smart_ocr(image_path: str) -> tuple[str, list]:
    """Run OCR with smart post-processing. Returns (text, raw_annotations)."""
    annotations = ocrmac.OCR(
        image_path,
        language_preference=["zh-Hant", "en-US"],
    ).recognize()

    if not annotations:
        return "(no text detected)", annotations

    raw_count = len(annotations)

    # Detect table structure
    grid = TableGrid.from_image(image_path)

    filtered = filter_garbage(annotations)
    garbage_count = raw_count - len(filtered)

    # Cell-aware vertical merging (with spanning support in header)
    merged = merge_vertical_runs(filtered, grid)

    # Horizontal pair merging (性+別 -> 性別, etc.)
    merged = merge_horizontal_pairs(merged, grid)

    # Table-aware row grouping
    rows = group_into_rows(merged, grid)
    lines = [format_row(row, grid) for row in rows]
    text = "\n".join(lines)

    print(f"  [stats] raw={raw_count}, garbage={garbage_count}, "
          f"after_merge={len(merged)}, rows={len(rows)}, "
          f"table={'yes' if grid.has_table else 'no'}, "
          f"h_lines={len(grid.h_lines)}, v_cols={len(grid.v_columns)}, "
          f"body_boundary={grid.form_body_boundary:.3f}")

    return text, annotations


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

    results_dir = Path("results-smart")
    results_dir.mkdir(exist_ok=True)

    print("Apple Vision OCR -- Smart Post-processing (v2: table-aware)")
    print("=" * 60)
    print(f"Folder : {folder}")
    print(f"Images : {len(images)}")
    print("=" * 60)
    print()

    total_time = 0.0

    for img_path in images:
        print(f"--- {img_path.name} ---")

        start = time.perf_counter()
        text, _ = smart_ocr(str(img_path))
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
