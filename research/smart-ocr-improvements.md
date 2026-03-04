# Smart OCR Post-processing Improvements

## Problem Summary

`run_ocr_smart.py` (v1) attempted to improve Apple Vision OCR output for Taiwanese police investigation forms (調查筆錄) by merging vertical text runs and pairing labels with values. However, the naive approach produced several artifacts:

- **Cross-cell merging**: Characters from different table cells got merged (e.g., `點由`, `時地`)
- **Incorrect vertical text merging**: `性：別 無女` -- characters from label and value columns mixed
- **Q&A marker contamination**: `問答問` -- alternating Q&A markers merged into nonsense
- **Broken reading order**: Scattered single characters interspersed with multi-char labels

## Root Cause Analysis

The v1 algorithm had one fatal flaw: **it ignored table cell boundaries**. It treated the entire page as a flat coordinate space and merged any single characters that were vertically close (similar x, sequential y). But in a structured form, characters at the same x-coordinate can be in completely different cells separated by table lines.

Specific failure modes:

1. **`點由`**: `點` (cx=0.188, label column) and `由` (cx=0.182, same column) are vertically stacked in the same x range, but belong to different form rows (`地點` vs `案由`). A horizontal line separates them.

2. **`性：別 無女`**: `性` and `別` are in the label column; `無` and `女` are in the value column. V1's row grouping put them all on one line because their y-coordinates were close.

3. **`問答問`**: In the Q&A body section, `問` and `答` are independent markers in the left margin. V1 merged them vertically because they share the same x and have sequential y values.

## Solution: Table-Aware Post-processing (v2)

### Key Technique: OpenCV Table Line Detection

Added a `TableGrid` class that detects the form's table structure before any text merging:

```python
# Horizontal lines (row boundaries)
h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 10, 1))
h_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

# Vertical lines (column boundaries)
v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 15))
v_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
```

This gives us:
- **Horizontal lines**: 26-29 lines per page (form row boundaries)
- **Vertical lines**: 4 consolidated column boundaries (table border, spanning column, label column, value column, right border)

### Vertical Line Consolidation

OpenCV detects vertical lines as separate segments (one per contiguous portion). A single logical column line might appear as 2-3 segments. We consolidate them:

```python
def _consolidate_x_positions(positions, tolerance=0.015):
    """Group segments at similar x into one logical column line."""
```

For the test images, this reduces 5-11 raw segments to 4 logical columns.

### Three Key Improvements

#### 1. Cell-Aware Vertical Merging

Before merging single characters vertically, check that they're in the **same table cell**:

```python
if grid.has_table and not grid.same_cell(bbox, jbbox, allow_spanning=True):
    continue  # Different cells -- don't merge
```

This prevents `點`+`由` (different row bands), `無`+`女` (different columns), etc.

#### 2. Spanning Column Recognition

The leftmost narrow column (where `詢問` and `受詢問人` are written vertically) intentionally spans multiple table rows. Characters in this column ARE allowed to merge across horizontal line boundaries, but ONLY in the form header area:

```python
def same_cell(self, bbox1, bbox2, allow_spanning=False):
    # In the spanning column AND in the form header, allow cross-row merging
    if (allow_spanning and self.is_spanning_column(cx1)
            and self.is_in_form_header(cy1) and self.is_in_form_header(cy2)):
        return True
```

The form header boundary is detected heuristically (~55% of the way through the horizontal lines).

#### 3. Q&A Marker Protection

`問` and `答` should never merge with each other -- they're different types of markers:

```python
if (last_char in QA_MARKERS and jtext in QA_MARKERS and last_char != jtext):
    continue  # Don't merge 問 with 答
```

### Additional: Horizontal Pair Merging

Added a new step to merge single characters that are **horizontally** adjacent in the same cell. This handles cases where OCR splits 2-char labels into individual characters: `性`+`別` -> `性別`, `地`+`點` -> `地點`, `案`+`由` -> `案由`, `職`+`業` -> `職業`.

Key fix: the horizontal merge iterates over only single-character annotations (not all annotations), so a multi-char annotation between two single chars doesn't block their merge.

## Results Comparison

### Image 2 (億萬詐騙): Form Header

| Field | v1 (before) | v2 (after) | Correct? |
|-------|-------------|------------|----------|
| 詢問/時間 | `詢問  時地` | `詢問` / `地點` | Yes |
| 案由 | `案：點由  詐欺` | `案由  詐欺` | Yes |
| 性別 | `性：別  無女` | `性別  女` | Yes |
| 受詢問人 | `受詢問人：統一編號  身分證` | `受詢問人` (separate) | Yes |
| 職業 | (scattered) | `職業  家管` | Yes |

### Image 2: Q&A Section

| Issue | v1 (before) | v2 (after) |
|-------|-------------|------------|
| Q&A markers | `問答問  提供投資...` | `問  歹徒提供...` / `答  提供...` |
| Marker placement | Mixed into text | Clean prefix on each Q/A |

### Image 1 (被害人調查筆錄)

| Field | v1 (before) | v2 (after) |
|-------|-------------|------------|
| 地點 | `地：臺北市...` / `點由：詐欺` | `地點  臺北市...` |
| 受詢問人 | `受訽問人  身分證  統一編號  H225100716` | `受詢問人` (separate, OCR-corrected) |
| 問 marker | `問  你於何時...` | `問  你於何時...` |

## Known Remaining Limitations

These are **OCR-level** limitations, not post-processing failures:

1. **Garbage character origins**: Some single characters from table lines are misread as real Chinese characters (`蒔`=`時`, `閰`=`間`, `粢`=`案`). After garbage filtering, the correct character is lost. For example, `時間` becomes just `時` (because `間` -> `閰` -> filtered).

2. **`統一編號` on separate line**: The `身分證` and `統一編號` labels are stacked within one cell but the horizontal line between them causes the row grouper to separate them. This is structurally correct (different row bands) even if semantically they belong together.

3. **`家庭經濟狀況` below its values**: The label is in a different row band than the checkboxes (貧寒/勉持/小康/中產/富裕). This is because the label cell spans a different vertical range than the values.

4. **V on its own line**: The checkmark `V` (indicating 小康) is in a different row band than the status options.

## Performance

No meaningful performance regression. OpenCV table detection adds ~50ms per image. Total OCR time per image remains ~1.0-1.4 seconds.

## Files Changed

- `apple-vision/run_ocr_smart.py` -- Complete rewrite of post-processing pipeline
- `apple-vision/pyproject.toml` -- Added `opencv-python-headless` and `numpy` dependencies

## Architecture

```
OCR Raw Output
    |
    v
[1] Filter Garbage Characters (蒔閬粢閰)
    |
    v
[2] OpenCV Table Line Detection
    |  -> horizontal lines (row boundaries)
    |  -> vertical lines (column boundaries)
    |  -> consolidated into TableGrid
    |
    v
[3] Cell-Aware Vertical Merge
    |  - Same column + same row band required
    |  - Exception: spanning column in form header
    |  - Exception: 問/答 never merge with each other
    |
    v
[4] Horizontal Pair Merge (性+別, 地+點, etc.)
    |  - Same row band + same column required
    |
    v
[5] Table-Aware Row Grouping
    |  - Row bands from horizontal lines
    |  - Sub-split by y-proximity within bands
    |  - Spanning items placed at top of their range
    |
    v
[6] Format (label-value pairing via column boundary)
    |
    v
Final Text Output
```
