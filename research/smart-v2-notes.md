# Smart v2: Cell-Based OCR Pipeline

## Approach

Smart v1 ran full-page OCR first, then used OpenCV table line detection to post-process the results (cell-aware merging, row grouping, label-value pairing). Smart v2 flips the order: **detect cells first, then OCR each cell individually**.

### Pipeline

```
Image
  |
  v
[1] OpenCV Table Line Detection
  |  -> horizontal lines (row boundaries)
  |  -> vertical lines (column boundaries)
  |  -> consolidated into Cell grid
  |
  v
[2] Cell Grid Construction
  |  -> Cell(row, col, x1, y1, x2, y2) objects
  |  -> classify into header rows (3-col) and body rows (2-col)
  |
  v
[3] Full-Page OCR (one call, used for two purposes)
  |  -> margin label extraction (col 0)
  |  -> fallback text for failed per-cell OCR
  |
  v
[4] Per-Cell OCR (one call per col 1+ cell)
  |  -> crop cell image with 5px inset
  |  -> add 25px white padding
  |  -> OCR with ocrmac
  |  -> sort results top-to-bottom, group into lines
  |  -> fallback to full-page OCR if empty or low confidence
  |
  v
[5] Assembly
  |  -> margin labels emitted as section headers
  |  -> header rows: "label  value" format
  |  -> body rows: "marker  content" format
  |
  v
Final Text Output
```

## Key Design Decisions

### Why not OCR col-0 cells individually?

The left margin column (col 0) is only ~86px wide. Apple Vision OCR completely fails on such narrow images -- returns empty text regardless of rotation, upscaling, padding, or line cleaning. This was tested extensively with various cell sizes and preprocessing techniques.

Solution: run one full-page OCR call, then filter single-character annotations that fall within col-0 cell bounds. Group them into spans (詢問, 受詢問人, etc.) by y-gap and row-gap thresholds.

### Adaptive line-grouping threshold

OCR results within a cell need to be sorted into reading order (top-to-bottom, left-to-right). The initial implementation used a fixed y-proximity threshold (0.1 in normalized coords) to group fragments into lines. This worked for small cells (1-2 lines) but completely broke for large Q&A body cells (10+ lines), where every line fell within the threshold and all text collapsed into a single jumbled line.

Fix: adaptive threshold = `avg_char_height * 0.5`. This scales to any cell size.

### Fallback mechanism

Some cells are too small for reliable per-cell OCR (e.g., 家庭經濟狀況 label at 377x92 pixels returns garbage). When per-cell OCR returns empty or confidence < 0.35, the system falls back to extracting text from the full-page OCR results that positionally overlap with the cell.

This means we always run full-page OCR regardless -- it serves double duty as both margin label extractor and fallback provider.

## Results Comparison

### Image 1: 被害人調查筆錄-北市提供_p1

| Field | Original (raw) | Smart v1 | Smart v2 (cell-based) |
|-------|----------------|----------|----------------------|
| Section label | `詢` `問` (separate lines) | `詢問` | `詢問` |
| 時間 | `自114年12 月14日...` (no label) | `自114年12 月14日...` (no label) | `時  114年12月14日-00點37分起` + next line |
| 地點 | `臺北市...` (no label, `地` `點` scattered) | `地點  臺北市...` | `地點  臺北市...` |
| 案由 | `詐欺` (no label, `由` scattered) | `由  詐欺` (missing 案) | `案由  詐欺` |
| 姓名 | `周芷萱` (label separate) | `姓.名  周芷萱` | `姓.名  周芷萱` |
| 性別 | `女` (label separate) | `性別  女` | `性别  女` |
| 身分證/統一編號 | `身分證` + `統一編號` (separate, no value) | `身分證  H225100716` / `統一編號` | `身分證` / `統一編號  H225100716` |
| 受詢問人 | `受` `訽` `問` `人` (4 separate lines) | `受詢問人` | `受詢問人` |
| 家庭經濟狀況 | `家庭經濟狀況` (scattered with values) | `家庭經濟狀況  貧寒  勉持  小康...` | `家庭經濟狀況  貧寒勉持小康中產富裕` |
| 教育程度 | `太學畢業` (no label) | `教育程度  太學畢業` | `教育程度  太學畢業` |
| Q&A: 問 markers | `問` on separate line | `問  你於何時...` | `問  你於何時...` |
| Q&A body text | Correct reading order | Correct reading order | Correct reading order |

### Image 2: 億萬詐騙-去識別化(1)_p1

| Field | Original (raw) | Smart v1 | Smart v2 (cell-based) |
|-------|----------------|----------|----------------------|
| Section label | `詢` `時` `閰` `問` `案` (scattered) | `詢問` | `詢問案` (bug: 案 merged) |
| 時間 | `114年05月28日...` (no label) | `時  114年05月28日...` | `時間  自114年05月28日...` |
| 地點 | `：台北市和平東路` (label scattered) | `地點  ：台北市和平東路` | `地點  ：台北市和平東路` |
| 案由 | `詐欺` (label scattered) | `案由  詐欺` | `案由  詐欺.` |
| 別(綽)號 | `無` (label separate) | `別（綽）號  無` | `別（綽）號  無` |
| 性別 | `女` (separate, `性` `別` apart) | `性別  女` | `性別  女` |
| 家庭經濟狀況 | `家庭經濟狀況` (values scattered) | `貧寒  勉持  小康...` / `家庭經濟狀況` | `家庭經濟狀況  貧寒勉持小康中產富裕` / `家庭經濟狀況  V` (duplicate) |
| Q&A: 問/答 | `問` `答` on separate lines | `問  歹徒提供...` / `答  提供...` | `問  歹徒提供投資網站...` / `答  提供投資網站...` |
| Q&A body text | `答` appears mid-paragraph (line 63) | `答` appears mid-paragraph (line 36) | No mid-paragraph marker intrusion |

## What Smart v2 Does Better

1. **Label-value pairing is structurally correct.** Because each cell is OCR'd independently, labels never bleed into neighboring cell values. `案由  詐欺` is clean without needing column-boundary heuristics.

2. **Time field gets its label.** v1 struggled with the `時間` cell because OCR fragmented `時` `間` into garbage chars. v2 OCRs the label cell independently, getting `時` or `時間` directly.

3. **Q&A body text is cleaner.** Per-cell OCR of the large body cell produces well-ordered text. In v1, the `答` marker occasionally appeared mid-paragraph (Image 2, line 36) because the full-page OCR placed it within the body text. v2 handles markers separately from content.

4. **Multi-line cell content preserved.** The time cell naturally produces two lines (起/止) because per-cell OCR preserves internal line structure.

5. **No cross-cell contamination.** The fundamental problem v1 was designed to solve (cross-cell merging) doesn't exist in v2 -- cells are physically cropped before OCR, so there's no possibility of `性別無女` or `問答問` artifacts.

## What Smart v2 Does Worse

1. **Margin label span splitting.** Image 2: `詢問案` -- the `案` character from the `案由` row gets merged with `詢問` from the rows above. The y-gap threshold (200px) and row-gap threshold (2) aren't enough to separate them when the cells are close together. v1 handled this correctly.

2. **Duplicate lines.** Image 2: `家庭經濟狀況` appears twice -- once from per-cell OCR (with the value `貧寒勉持...`) and once from fallback (with just `V`). The fallback emits text that the per-cell OCR already captured.

3. **Per-cell OCR introduces new character errors.** The cropped cell images sometimes produce different (worse) OCR results than full-page OCR:
   - `LINE HD: 9U0111` (v2) vs `LINE ID: qUn111` (v1) -- both wrong, differently
   - `你县前` (v2) vs `你目前` (v1) -- v2 wrong, v1 correct
   - `太學畢業` (both) vs correct `大學畢業`
   - `凋站` (v2) vs `網站` (v1) -- v2 wrong, v1 correct
   - `第三次` (v2) vs `第二次` (v1) -- v2 wrong

4. **Performance.** ~3 seconds per image (many individual OCR calls) vs ~1 second for v1 (one full-page OCR call). 3x slower.

5. **Missing Q/A markers in some body rows.** Some body rows that should have 問 or 答 prefixes don't get them because the full-page OCR didn't detect the marker, or the marker wasn't matched to the correct row.

## Character-Level Accuracy Analysis

Per-cell OCR sometimes produces different recognition results than full-page OCR. This is because Apple Vision OCR uses context (surrounding text, document layout) to disambiguate characters. When you crop a small cell, that context is lost.

Notably affected:
- **English/alphanumeric text in Chinese context**: `ID` -> `HD`, `qUn` -> `9U0` (context loss hurts mixed-script recognition)
- **Characters near table lines**: Cropping with only 5px inset sometimes leaves line artifacts that confuse OCR
- **Rare/ambiguous characters**: `目` -> `县`, `網` -> `凋`, `二` -> `三` (fewer contextual clues in isolation)

This is an inherent trade-off of the cell-based approach: you gain structural correctness (no cross-cell confusion) but lose recognition context.

## Tradeoff Summary

| Aspect | Smart v1 (post-processing) | Smart v2 (cell-based) |
|--------|---------------------------|----------------------|
| Structure correctness | Good (with OpenCV fixes) | Excellent (by design) |
| Character accuracy | Better (full-page context) | Worse (isolated cells lose context) |
| Label-value pairing | Good (column boundary heuristic) | Excellent (cell isolation) |
| Q&A body formatting | Good (occasional marker intrusion) | Better (markers separated) |
| Margin labels (col 0) | Good (vertical merge + corrections) | Good (full-page OCR extraction) |
| Speed | ~1s/image | ~3s/image |
| Code complexity | High (many merge heuristics) | Moderate (cleaner pipeline) |
| Robustness to new forms | Fragile (many tuned thresholds) | More robust (cell detection is generic) |

## Conclusion

Smart v2's cell-based approach is architecturally cleaner and produces better-structured output. The "detect first, OCR second" paradigm eliminates an entire class of cross-cell merging bugs that required complex heuristics in v1.

However, character-level accuracy is sometimes worse because isolated cell OCR loses the contextual information that full-page OCR uses for disambiguation. This is most noticeable for mixed Chinese/English text and characters near table line boundaries.

A potential best-of-both-worlds approach: use v2's cell grid detection for structure, but run full-page OCR for the actual text content, then assign full-page OCR fragments to cells by position. This would preserve both structural correctness and contextual accuracy. Essentially, this is what v1 does with `TableGrid`, but v2's cell grid construction and classification logic is more robust.

## Known Bugs (v2)

1. ~~`詢問案` merged span (Image 2)~~ -- **FIXED** by cell-based margin label grouping
2. ~~Duplicate `家庭經濟狀況` line (Image 2)~~ -- **FIXED** by intersection-based grid (cell no longer wrongly split)
3. `身分證` on its own line without value -- the value `H225100716` is on the `統一編號` line instead (structural: merged value cell)
4. Missing 問/答 markers on some body rows
5. Per-cell OCR character errors (e.g., `第三次` should be `第二次`, `凋站` should be `網站`)

## Files

- `apple-vision/smart-v2/run_ocr.py` -- main pipeline (~570 lines)
- `apple-vision/smart-v2/results/` -- OCR output for test images

---

## Update: Intersection-Based Cell Grid (2026-03-05)

### The Problem

`build_cell_grid` was fundamentally flawed: it sliced cells between every pair of adjacent horizontal lines, regardless of whether those h-lines actually existed at a given column position. This caused partial horizontal lines to wrongly bisect cells they don't touch.

**Concrete example**: h16 at y=1741 only exists on the right side (x=634..2388). But the `家庭經濟狀況` label is in the left column (x=288..643). The old code cut the left column at y=1741, splitting the `家庭經濟狀況` cell into two halves. The top half got OCR'd as `家庭經濟狀況`, the bottom half was empty, causing the duplicate line bug.

### Root Cause

The old algorithm:
```
for each pair of adjacent h-lines (hi, hi+1):
    find v-lines that span between them
    create cells between consecutive v-lines
```

This treats every h-line as a full-width row boundary. But in real forms, some h-lines only span part of the table width (e.g., the line under the checkboxes only exists in the right value column, not in the left label column).

### The Fix: Intersection-Based Grid

New algorithm:

1. **Build intersection matrix**: For each (h-line, v-line) pair, check if they actually cross. A horizontal line intersects a vertical line when the h-line's x-range covers the v-line's x-position AND the v-line's y-range covers the h-line's y-position.

2. **Find cells from v-line pairs**: For each pair of v-lines (left, right), find all h-lines that intersect BOTH. Consecutive such h-lines define the top/bottom of a cell.

3. **Block wider cells**: When checking v-line pair (vi_left, vi_right), skip if an intermediate v-line also intersects both the top and bottom h-lines (meaning a narrower cell should be created instead).

4. **Assign row/col indices**: Sort cells by y-position (rows) and x-position (columns within each row).

```python
def _lines_intersect(h_line, v_line, tol=25):
    hy, hxs, hxe = h_line
    vx, vys, vye = v_line
    return (hxs - tol <= vx <= hxe + tol) and (vys - tol <= hy <= vye + tol)
```

### Key Insight: V-Line Pairs, Not Adjacent V-Lines

The first attempt iterated over adjacent v-line pairs only (vi, vi+1). This failed for body rows where the middle v-line (v2, label/value separator) doesn't exist -- no cells were created between v1 and v3 because the algorithm couldn't "skip over" v2.

The fix iterates over ALL v-line pairs (vi_left, vi_right for vi_right > vi_left), but blocks wider cells when a narrower one exists. This naturally handles:
- Header rows: v0-v1 (margin), v1-v2 (label), v2-v3 (value) -- all 3 cells
- Body rows: v0-v1 (margin), v1-v3 (content) -- v2 doesn't intersect body h-lines, so the wide cell v1-v3 is created

### Merged Cells Arise Naturally

When a h-line doesn't intersect a v-line, no cell boundary is created there. The cell extends across multiple "old rows". This correctly handles:

- `家庭經濟狀況` label: h16 doesn't intersect v2 (label/value boundary), so the label cell spans from h15 to h17 instead of being cut at h16
- `受詢問人` margin: the margin column spans from h4 to h17, one tall cell
- Body content cells: the wide content column (v1 to v3) isn't split by v2

### Additional Fixes

**Cell classification**: Changed from counting columns per row (broke when margin column is absent) to checking whether a cell's right edge aligns with the middle v-line. If any cell in a row has its right edge near the label/value separator, that row is a header row.

**Cell role identification in assembly**: Changed from column index (col 0/1/2) to x-position based identification. Cells are classified as margin (narrow, <120px), label (right edge at mid-v-line), or value (left edge at mid-v-line) by their actual pixel coordinates.

**Margin label grouping**: Changed from y-gap/row-gap heuristics to cell-based grouping. Characters in the same margin cell form one label, characters in different margin cells are separate labels. This correctly separates `詢問` (in margin cell r1) from `案` (in margin cell r3).

**Single-char margin suppression**: A single-character margin label that duplicates part of the label cell text on the same row is suppressed. E.g., margin `案` is suppressed when the label cell already has `案由`.

### Results After Fix

**Image 2 (億萬詐騙)**:

| Issue | Before fix | After fix |
|-------|-----------|-----------|
| 家庭經濟狀況 | Duplicated (line 19 + line 20) | Single line: `家庭經濟狀況  貧寒勉持小康中產富裕` |
| 詢問案 merged | `詢問案` on one line | `詢問` (line 2), `案由  詐欺.` (line 6) |
| Body rows missing cells | Only margin col in body | Margin + content cells in all body rows |
| Header label-value pairing | Some labels missing | All labels correctly paired with values |

**Image 1 (被害人調查筆錄)**:

| Issue | Before fix | After fix |
|-------|-----------|-----------|
| 家庭經濟狀況 | Potentially split | Single line: `家庭經濟狀況  貧寒勉持小康中產富裕` |
| 別(綽)號/性別 merge | Value cell correctly spans both rows | `別（綽）號  女` / `性别` (merged value cell, structural) |
| Body rows | Body cells present | All body rows have margin + content |

### Remaining Issues

1. **`V` on its own line**: The checkmark `V` is in a right-side-only cell (r16) that has no label cell. This is structurally correct -- the h-line only exists on the right, creating a separate row there. The `V` belongs semantically with `家庭經濟狀況` but structurally it's in a different cell.

2. **`別（綽）號  女`**: The value `女` should go with `性別`, not `別(綽)號`. This is because h6 doesn't reach the right edge (v3), so the value column merges across the `別(綽)號` and `性別` rows. The OCR of that merged cell returns `女`, which gets paired with the first label row. This is a structural limitation of the form -- the value cells are physically merged.

3. **`身分證` without value**: Same merged cell issue -- the value `H225100716` is in a cell that spans both `身分證` and `統一編號` rows, and gets paired with `統一編號`.

4. **Per-cell OCR accuracy**: Some character recognition errors compared to full-page OCR (see earlier notes). These are inherent to the cell-based approach.

### Cell Counts

| Image | h-lines | v-lines | Cells (before) | Cells (after) |
|-------|---------|---------|----------------|---------------|
| Image 1 | 26 | 4 | 41 | 49 |
| Image 2 | 29 | 4 | 45 | 57 |

The increased cell count comes from body rows now having both margin and content cells (previously body rows only had margin cells due to the adjacent-v-line-only algorithm).
