"""Apple Vision OCR with smart post-processing for tables/forms.

Improvements over run_ocr.py:
  1. Filters low-confidence garbage characters (table lines misread as chars)
  2. Detects and merges vertical text runs (single chars with similar x, sequential y)
  3. Pairs labels (left column) with values (right column) on the same row
  4. Reconstructs reading order by sorting into rows (y) then columns (x)

Coordinate system note:
  Apple Vision uses normalized 0-1 coordinates where y=0 is the BOTTOM of image.
  Bounding box = (x, y, w, h) where (x, y) is the bottom-left corner.
"""

import sys
import time
from pathlib import Path

from ocrmac import ocrmac

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}

# --- Tuning constants ---
VERTICAL_X_TOLERANCE = 0.025     # Max x-center difference for vertical text
VERTICAL_Y_GAP_MAX = 0.045      # Max gap between consecutive chars in a vertical run
ROW_Y_TOLERANCE = 0.013          # Max y-center difference to consider "same row"
LABEL_VALUE_X_GAP_MIN = 0.03    # Min x gap between label end and value start

# Characters commonly produced by OCR misreading table borders/lines.
GARBAGE_CHARS = set("蒔閬粢閰")


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
# Step 2: Detect and merge vertical text (single-character runs only)
# ------------------------------------------------------------------
def merge_vertical_runs(annotations):
    """Find SINGLE-CHARACTER annotations stacked vertically and merge them.

    Only merges runs where every piece is exactly 1 character, which is the
    hallmark of vertical text in Chinese forms (e.g. 詢/問 -> 詢問, 受/訽/問/人 -> 受訽問人).
    Multi-char labels stacked in a column (like 姓名, 性別, 出生地) are NOT merged.
    """
    # Separate single-char candidates from the rest
    singles = []  # (original_index, text, conf, bbox)
    others = []   # (text, conf, bbox)
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

            # Gap: how far below current_bottom the next top is
            gap = current_bottom - j_top
            if gap < -0.005:
                continue  # still above
            if gap > VERTICAL_Y_GAP_MAX:
                continue  # too far below, but don't break -- there might be another char closer in x

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
            merged.append((combined_text, avg_conf, merged_bbox))
        else:
            merged.append((text, conf, bbox))

    # Add all multi-char annotations
    merged.extend(others)

    return merged


# ------------------------------------------------------------------
# Step 3 & 4: Group into rows, pair labels/values, reconstruct order
# ------------------------------------------------------------------
def group_into_rows(annotations, y_tolerance=ROW_Y_TOLERANCE):
    """Group annotations into rows based on y-center proximity."""
    if not annotations:
        return []

    sorted_anns = sorted(annotations, key=lambda a: -center_of(a[2])[1])

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

    for row in rows:
        row.sort(key=lambda a: left_of(a[2]))

    return rows


def format_row(row_items):
    """Format a row of annotations into a readable line."""
    if len(row_items) == 1:
        return row_items[0][0]

    first = row_items[0]
    second = row_items[1]
    first_right = right_of(first[2])
    second_left = left_of(second[2])
    gap = second_left - first_right

    is_label_value = (
        gap >= LABEL_VALUE_X_GAP_MIN
        and len(first[0]) <= 8
    )

    if is_label_value:
        label = first[0]
        value_parts = [item[0] for item in row_items[1:]]
        value = "  ".join(value_parts)
        return f"{label}：{value}"

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

    filtered = filter_garbage(annotations)
    garbage_count = raw_count - len(filtered)

    merged = merge_vertical_runs(filtered)

    rows = group_into_rows(merged)
    lines = [format_row(row) for row in rows]
    text = "\n".join(lines)

    print(f"  [stats] raw={raw_count}, garbage={garbage_count}, "
          f"after_merge={len(merged)}, rows={len(rows)}")

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

    print("Apple Vision OCR -- Smart Post-processing")
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
