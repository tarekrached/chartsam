# Georeferencing Learnings — detect_gcps.py development

Notes captured after building `scripts/detect_gcps.py` from scratch, validated on
chart 18649, and partially applied to chart 18654.

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

## Chart 18654 — Specific Findings

### Dimensions and structure
- 12952 × 16792 px at 400 DPI
- Inset sub-chart in **upper-left corner**: rows 259–2985, cols 175–~340
  - Inset has a solid right border at col ~340 that scores 3200 (exceeds main meridians)
  - Solution: restrict scan region to rows 2985–16090, cols 175–12776 (excludes inset)
- **4 main meridians** detected at approximately cols 2870, 5745, 8620, 11500
  - Spacing ~2875 px/tick
  - If 5' interval: ~575 px/arcmin (consistent with ~1:40,000 scale)
- **4 main parallels** detected at approximately rows 2985, 6627, 10271, 13907
  - Spacing ~3644 px/tick
  - If 5' interval: ~729 px/arcmin — suspicious (should be ~455 at this latitude)
  - More likely 6' interval: ~607 px/arcmin — or chart covers more latitude than 18649

### Coordinates (still unknown — need to read PDF border labels)
The chart covers an area near 38°N, 123°W (likely Point Reyes / Bodega Bay area).
To complete georef/18654.json, open `charts/18654.pdf` in a PDF viewer and read:
- Top/bottom border: longitude tick labels (e.g. "123°05'W")
- Left/right border: latitude tick labels (e.g. "38°20'N")

Then run: `python3 scripts/detect_gcps.py 18654` interactively with:
- Neatline: top=259, left=175, right=12776, bottom=16254
- Scan region: top=2985, left=175, right=12776, bottom=16090
- Keep 4 meridians, keep 4 parallels
- Enter the tick interval (probably 5') and first meridian/parallel coordinates

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

```bash
# Detect GCPs for a new chart (interactive TTY required)
python3 scripts/detect_gcps.py 18654

# Validate against existing georef
python3 scripts/detect_gcps.py 18649 --validate

# After georef/<n>.json is written:
python3 scripts/tile_chart.py <n>
./deploy.sh
```

The JSON written to `georef/<n>.json` drives the entire tile pipeline via
`scripts/tile_chart.py` — no manual GDAL commands needed afterward.
