# Georeferencing Automation — Learnings and Gaps

Notes from attempting fully automated georeferencing of charts 18653 and 18650.
Goal: produce `georef/<n>.json` without any manual prompts.

---

## What Is Fully Automated

- **Pre-rasterization** (`prerasterize.py`): 100% automated, runs in parallel.
- **Neatline detection** (`detect_neatline`): reliable on all charts seen so far.
- **Meridian detection** (`detect_meridians`): reliably finds the right columns when
  the graticule is sparse and the interior is relatively open (18649, 18654). Struggles
  on busy urban/harbour charts where coastlines, piers, and built features generate
  competing vertical signals.
- **Parallel detection** (`detect_parallels`): same caveat — works well on open-water
  charts, degrades on busy charts.
- **GCP measurement** (`measure_gcps`): fully automated once cols/rows and coords are known.
- **Outlier detection**: automated (per-meridian col spread > 20 px).

## What Still Requires Human Input

### 1. Coordinate assignment — the core gap

The detector finds pixel columns/rows of graticule lines but has no way to know which
longitude or latitude those lines represent. A human currently reads the tick labels
from the chart border and types them in.

**Path to automation:** The labels are printed text in the chart margin. OCR
(`pytesseract` or similar) on a small crop of the border at each detected meridian/
parallel position should be able to read them. This is the highest-leverage automation
remaining.

### 2. Graticule interval disambiguation

For charts at different scales, the dominant tick interval varies:

| Chart | Scale (approx) | Graticule interval | px/arcmin |
|-------|---------------|-------------------|-----------|
| 18649 | 1:80,000 | 5' | ~577 |
| 18654 | 1:40,000 | 5' | ~575 |
| 18653 | 1:20,000 | 2' (labeled every 1') | ~1154 |
| 18650 | 1:20,000 | 2' (labeled every 1') | ~1154 |

The detector can infer scale from the dominant meridian spacing, but must still know
which longitude the first meridian represents.

### 3. Inset detection false positive

`detect_inset_boundary()` fires at row ~nl_top for 18653 and 18650 — the outer neatline
itself scores very high (17000+). The 5000-threshold guard is too low for these charts.
Fix: require the detected boundary row to be at least 500 px below nl_top.

---

## Chart-Specific Findings

### 18653 — "San Francisco Bay: Angel Island to Point San Pedro"

- Dimensions: 17904 × 14091 px at 400 DPI
- Approximate scale: 1:20,000 (computed from px spacing)
- **Longitudes**: 122°32'W (west edge) to 122°17'W (east edge), **1' labeled / 2' major**
- **Consistent meridian spacing**: ~2308 px = 2 arcmin at 1:20,000 scale
- **Major meridian cols** (from spacing analysis): ~374, 2682, 4990, 7299, 9607, 11914, 14224, 16530
  (col ~374 falls inside the 400 px margin exclusion zone and is not detected)
- **Longitudes** (if col 2682 = 122°30'W at 2' interval):
  2682→122°30', 4990→122°28', 7299→122°26', 9607→122°24', 11914→122°22', 14224→122°20', 16530→122°18'
- **Latitudes**: visible labels 37°59' down to ~37°51' at 1' intervals; major (2') parallels
  likely at 37°52', 54', 56', 58', 38°00' — spacing ~2920 px (1:20,000 lat scale)
- Parallel detector unreliable due to busy chart interior; needs open-water column selection

### 18650 — "San Francisco Bay: Candlestick Point to Angel Island"

- Dimensions: 17864 × 14300 px at 400 DPI
- Approximate scale: 1:20,000
- **Longitudes**: from top margin: ~122°26'W (west) to ~122°14'W (east), 1' labeled / 2' major
- **Inset**: upper-right corner (Oakland/Alameda harbor detail) — must exclude from scan region
- Parallel and meridian detection needs open-water column tuned for SF Bay interior

---

## Recommended Next Steps for Full Automation

1. **Fix inset false positive**: in `detect_inset_boundary`, require `boundary_row > nl_top + 500`.

2. **Add scale inference**: from dominant meridian spacing, infer px/arcmin and hence chart
   scale. Use this to set expected `min_spacing` for meridian/parallel detection automatically.

3. **OCR tick labels**: crop a ~300 × 100 px window at each detected meridian column
   (just below nl_top) and each detected parallel row (just right of nl_right), run
   `pytesseract.image_to_string()` with a whitelist of digits, `°`, `'`, `"`. The
   first labeled meridian gives the starting longitude; the rest follow from the interval.

4. **Fallback prompt**: only prompt the user if OCR returns ambiguous/unreadable results.

---

## Automation Coverage Today

| Step | Status |
|------|--------|
| Pre-rasterize PDF → TIF | ✅ Fully automated |
| Neatline detection | ✅ Reliable |
| Inset detection | ⚠️ False positive on neatline (fix: +500 px guard) |
| Meridian col detection | ⚠️ Noisy on busy charts; spacing filter helps |
| Parallel row detection | ⚠️ Noisy on busy charts; needs open-water col |
| Coordinate reading | ❌ Manual (OCR would fix this) |
| GCP measurement | ✅ Fully automated |
| Outlier detection | ✅ Fully automated |
| JSON output | ✅ Fully automated |
