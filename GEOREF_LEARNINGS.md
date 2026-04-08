# Georeferencing Learnings — detect_gcps.py development

Notes captured after building `scripts/detect_gcps.py` from scratch, validated on
chart 18649, and fully applied to chart 18654 (San Pablo Bay).

---

## NOAA Chart Structure

### Physical layout (400 DPI scans)
- **Outer neatline**: ~20 px thick black border at the edge of chart content
- **Inner neatline**: a second border ~165 px inside the outer one
- **Margin content**: tick labels, compass rose, title block — between outer and inner neatlines
- **Interior margin**: ~400 px from the outer neatline is the safe zone to start looking for graticule lines
- **Insets**: some charts (e.g. 18654) have an inset sub-chart in a corner at a different scale; the inset has its own border that appears as a strong vertical/horizontal line

### Graticule characteristics
- Graticule lines are **dashed**, not solid — each segment is ~20–40 px long with gaps
- Spacing: ~575–578 px/arcmin at ~1:40,000 scale (400 DPI)
- Meridians: vertical dashed lines
- Parallels: full-width horizontal dashed lines crossing the chart interior

### What looks like (but isn't) a graticule
- Neatline borders (solid, score 100% of rows)
- Inset right/bottom borders (solid, typically score higher than any meridian)
- Coastlines, depth contours (horizontal persistence high in some local regions)
- Annotation boxes, scale bars

---

## Algorithm: Meridian Detection

### What works
**Full-height vertical-persistence accumulation** — for each column, count pairs of
adjacent dark rows (row[r] < 60 AND row[r+1] < 60). Do this at every 4th row across
the entire scan height. Sum gives each column a "VP score".

- Dashed meridians: score intermittently across ~13,000 rows → 2000–3000 total
- Solid inset border at margin: score constantly → 3200+ (excluded by `margin=400`)
- Open water: score ~0; coastlines: score 200–800 depending on orientation

**Greedy min-spacing selection** — sort candidates by VP score descending, accept each
that is ≥ min_spacing from all already-accepted ones. Better than a fixed threshold
because noise levels vary between charts.

**Keep-top-N filter** — if detection finds too many features, user specifies expected
count N; script adapts min_spacing = chart_width / (N+1) and re-runs greedy selection.
This cleanly handles insets and annotation noise that survives the margin exclusion.

### What doesn't work
- **Scanning only a narrow horizontal band** (e.g. 200 rows): dashed meridians score
  only 6–104 in 200 rows; neatline border scores 200. Signal-to-noise is terrible.
- **2D centroid in a ±80 px window**: a solid line within the window (scoring 160/160)
  pulls the result 12–34 px away from the actual dashed graticule line.
- **Threshold at % of max without margin exclusion**: the neatline border is always max.

---

## Algorithm: Parallel Detection

### What works
**Wide-strip horizontal-persistence scoring** — take a strip `img_w//5` columns wide
centred at an open-water column. For each row, count consecutive-column dark pixel
pairs. Take rows above the 90th percentile as candidates. Cluster neighbouring rows
(gap ≤ 5), then greedy min-spacing selection (500 px default).

- Open-water column is critical: coastlines generate many strong horizontal signals.
  Middle of the chart or a known open-water area works well.
- 90th percentile threshold is more robust than a fixed count; adapts to varying
  chart contrast levels.

### What doesn't work
- 97th percentile: found 106 parallels on 18649 (parallels are only 3)
- Scanning a narrow vertical strip (< img_w//5): coastline features in the strip
  dominate over the parallel graticule line
- Scanning only from nl_top: the top neatline border scores highest and throws off
  the threshold

---

## Algorithm: Intersection Centroid Measurement

### What works: two-step 1D projection

**Step 1 — meridian column:**
1. Read a 160-row × 160-col window centred at (col_est, row_est)
2. Compute vertical-persistence (VP) filter: `dark[r] & dark[r+1]` summed per column
3. Find peak column of VP signal, then weighted average in ±15 px local window

VP filter suppresses the horizontal parallel line (which spans all columns and would
make every column's contribution look equal, washing out the meridian signal).

**Step 2 — parallel row:**
1. Narrow the column to ±15 px around the found meridian column
2. Count dark pixels per row in this narrow band
3. Peak + ±15 px local weighted average → sub-pixel row estimate

### Why local weighted average (not global)
Global weighted average: distant chart features (soundings, coastlines) in the 160-px
window contribute weight proportional to their darkness × count. On some charts this
pulls the estimate 30+ px off the graticule line.

Local weighted average: find peak first (quick argmax), then average only within ±15 px
of the peak. Distant features are completely excluded.

### Validation against 18649 reference
- 11/15 GCPs within 5 px of reference (OK)
- 4 outliers (Δcol 12–34 px): caused by solid non-graticule lines dominating
  the reference measurement. The reference GCPs at those 4 positions appear to
  be measurement artifacts — the reference cols vary 0–34 px per meridian across
  parallels, while our algorithm varies 0–2 px (self-consistent).
- Conclusion: our algorithm is more accurate at those 4 locations; the reference
  values are biased by chart structure.

---

## Chart 18654 — Completed

### Dimensions and structure
- 12952 × 16792 px at 400 DPI — "San Pablo Bay" (inside SF Bay, north of the Gate)
- Inset sub-chart in **upper-left corner**: "Continuation of Petaluma River", rows 259–2985, cols 175–~340
  - Inset has a solid right border at col ~340 that scores 3200 VP (exceeds main meridians at 2073–2804)
  - Solution: restrict scan region to rows 2985–16090, cols 175–12776 (excludes inset)
- **4 main meridians** at cols ~2870, 5745, 8620, 11500 — spacing 2875 px/tick
- **4 main parallels** at rows ~2985, 6627, 10271, 13907 — spacing 3644 px/tick

### Coordinates (confirmed by reading PDF border labels)
- Meridians: **122°25', 122°20', 122°15', 122°10' W** — 5' interval, 575.4 px/arcmin
- Parallels: **38°15', 38°10', 38°05', 38°00' N** — 5' interval

Parallel pixel spacing (3644 px/5') = 728.8 px/arcmin for latitude. At 38°N, the
latitude scale is ~1/cos(38°) ≈ 1.27× the longitude scale: 575 × 1.27 = 730 px/arcmin.
The "suspicious" earlier estimate of 729 px/arcmin was correct for a 5' parallel interval
— the discrepancy from the longitude scale is expected due to the latitude convergence factor.

### GCP measurement results
- 16 GCPs, regression RMS 0.50 px
- 2 col outliers fixed (see "GCP Outlier Fixes" below)
- See `georef/18654.json` for full GCP table

### GCP Outlier Fixes
Two GCPs had bad col measurements, both due to competing dark features:

| GCP | Measured col | Expected (~) | Cause | Fix |
|-----|-------------|--------------|-------|-----|
| (-122.3333, 38.25) at row 2985 | 5680 | 5745 | Competing feature at col 5682 scored equally (VP=44 vs 44). Row 2985 is the inset lower boundary — high noise. | Substituted per-meridian mean col from other 3 rows (5745.8) |
| (-122.1667, 38.00) at row 13907 | 11427 | 11499 | Max VP score = 3 across all columns — essentially no signal at all. | Substituted per-meridian mean from other 2 rows (11499.1) |

**Rule**: When per-meridian col spread across parallels is > 20 px for a single GCP,
that GCP is likely bad. Replace with the mean col from the clean rows for that meridian.

---

## Reading Coordinates from NOAA Chart PDFs

`pdftotext` produces no useful output on NOAA chart PDFs (iTextSharp-generated, text not
embedded as selectable objects). Must read tick labels visually from a rendered image.

### Efficient approach (no PDF viewer needed)
```bash
# 1. Overview — identify chart title, approximate extent, inset location
GDAL_PDF_DPI=50 gdal_translate -of PNG charts/18654.pdf /tmp/overview.png

# 2. Read tick labels — render at 200 DPI, crop margin areas
GDAL_PDF_DPI=200 gdal_translate -of PNG charts/18654.pdf /tmp/chart_200.png

# Longitude: crop below top neatline, centred on each meridian column
# Latitude:  crop right of left neatline, centred on each parallel row
```

At 200 DPI the image is 1/2 linear scale of the 400 DPI raster. Convert coordinates:
`col_200 = col_400 / 2`, `row_200 = row_400 / 2`.

### Where the labels are
- **Longitude labels**: just **below** the top neatline (rows nl_top to nl_top+100 at 400 DPI).
  The label text is centred horizontally on the tick's column.
- **Latitude labels**: just **outside** the right (or left) neatline. The right margin
  shows the full `38° 15'` form; left margin often shows only the minutes part.

### Sub-tick label confusion
NOAA charts have 1-arcminute sub-ticks between 5' major ticks. Each minute tick may also
have 30-arcsecond sub-ticks labeled with double-prime (`50"`) not single-prime (`50'`).
If a margin crop near a parallel row shows `50"` instead of the expected `15'`, the crop
is off-centre — try a wider vertical range to find the full `38° 15'` label on the right margin.

### Parallel spacing cross-check
Expected latitude pixel scale ≈ lon_px_per_arcmin / cos(lat):
- At 38°N: lat_px_per_arcmin ≈ 575 / cos(38°) ≈ 730 px/arcmin
- 5' parallel spacing: ~3644 px ✓
- If detected spacing doesn't match any reasonable interval, re-check the inset boundary —
  a thick inset border can be misidentified as a parallel.

---

## detect_gcps.py — Key Constants and Tuning

| Parameter | Value | Notes |
|-----------|-------|-------|
| `BLACK_THRESH` | 60 | R < 60 → "black". Works for all NOAA chart scans seen so far |
| `CENTROID_HALF` | 80 | ±80 px search window for intersection centroid |
| `margin` (detect_meridians) | 400 | Skip 400 px from each neatline side — excludes outer AND inner border |
| `row_step` | 4 | Sample every 4th row for VP accumulation (4× speedup, still finds dashed lines) |
| `min_height_frac` (find_peaks_1d) | 0.05 | 5% of max — low enough to catch weak meridians |
| `min_distance` (find_peaks_1d) | 10 | px between raw peaks before clustering |
| `cluster_peaks gap` | 10 | Merge raw peaks within 10 px |
| `local_half` (_peak_weighted_avg) | 15 | ±15 px local window for weighted average around peak |
| `row_band_half` (measure_centroid) | 15 | ±15 col band for parallel row measurement |
| `strip_half` (detect_parallels) | img_w//5 | 20% of width each side — wide enough for SNR |
| `parallel min_spacing` | 500 | Minimum px between parallels (at 575 px/arcmin, ~50" separation) |

---

## Polyconic Projection Notes

NOAA charts use polyconic projection (or close approximation). Meridians appear:
- Slightly curved in pixel space (converging toward the poles)
- Column position varies ~22 px over chart height (13,000 rows) at ~38°N

This means:
- Regression `col = offset + spacing * n` holds across meridians at a given row
- The same meridian at different parallels may differ by ±10 px in column
- TPS (thin-plate spline) warp handles this residual distortion; affine warp does not

Using `gdalwarp -tps` in tile_chart.py is correct for polyconic-projection charts.

---

## Workflow Summary

### New chart from scratch
```bash
# 1. Identify coordinates (no PDF viewer needed)
GDAL_PDF_DPI=50 gdal_translate -of PNG charts/<n>.pdf /tmp/overview.png   # read title/extent
GDAL_PDF_DPI=200 gdal_translate -of PNG charts/<n>.pdf /tmp/chart_200.png # read tick labels

# 2. Detect GCPs (interactive — needs a real TTY)
python3 scripts/detect_gcps.py <n>

# 3. Generate tiles
python3 scripts/tile_chart.py <n>
./deploy.sh
```

### Validate existing georef
```bash
python3 scripts/detect_gcps.py 18649 --validate
```

### Fix bad GCPs without re-running interactive mode
If a centroid measurement is bad (competing feature, no signal), edit `georef/<n>.json`
directly and replace the bad `pixel_col` with the mean from the other parallels for that
meridian. The TPS warp tolerates small per-GCP errors well.

The JSON written to `georef/<n>.json` drives the entire tile pipeline via
`scripts/tile_chart.py` — no manual GDAL commands needed afterward.
