# Plan: New Georef Pipeline + Chart 18654

## Goal

1. Write `scripts/detect_gcps.py` to replace the hardcoded `scripts/georeference_gcp.py`
2. Validate it by running on chart 18649 and comparing output to the known-good `georef/18649.json`
3. Run detection on chart 18654 and produce `georef/18654.json`

`tile_chart.py`, tiling, and deploying are out of scope for this session.

---

## Step 1 — Write `scripts/detect_gcps.py`

Takes a chart number as argument. Reads `charts/<n>.pdf`, detects the graticule
programmatically, and writes `georef/<n>.json`.

### Detection algorithm (proven on 18649)

**Meridians (vertical lines):**
- Read the raster into numpy via GDAL
- Scan a thin horizontal strip just inside the top neatline (rows `neatline_top + 10` to `+ 210`)
- Sum black pixels (`R < 60`) per column → peaks are meridian candidates
- Cluster nearby peaks, take centroids → column estimates
- Fit a linear regression to get spacing + offset

**Parallels (horizontal lines):**
- Scan a vertical strip in open water (avoid land; try `col = width // 4`, adjust if needed)
- Sum black pixels per row → peaks where ≥ 40% of strip is black → parallel candidates

**GCP intersection measurement:**
- For each (meridian_col_estimate, parallel_row_estimate), scan a ±80px window
- Find centroid of dark cluster → sub-pixel accurate pixel coordinate
- This corrects the ~60–65px systematic bias the regression alone had on 18649

**Lon/lat assignment:**
- Print detected line count, spacing in pixels, and estimated degree spacing
- Prompt the user to input the longitude of the first (westernmost) meridian,
  the latitude of the first (northernmost) parallel, and the tick interval
- Script computes the rest and prints a table of (col, row) → (lon, lat) for review
- User confirms, then script writes `georef/<n>.json`

### Output: `georef/<n>.json`

```json
{
  "chart": "18649",
  "title": "...",
  "source_pdf": "charts/18649.pdf",
  "pdf_dimensions": { "width": 17648, "height": 13832 },
  "gcps": [
    { "pixel_col": 1554.0, "pixel_row": 3620, "lon": -122.6667, "lat": 37.9167 }
  ],
  "neatline": { "col": 173, "row": 202, "width": 17455, "height": 13428 },
  "bounds": { "west": -122.7059, "east": -122.2023, "south": 37.6871, "north": 37.9932 },
  "graticule": {
    "meridian_spacing_arcmin": 5,
    "parallel_spacing_arcmin": 5,
    "meridians_detected": 27,
    "parallels_detected": 3,
    "px_per_arcmin_lon": 577.68,
    "rms_residual_px": 3.2
  },
  "notes": "..."
}
```

The neatline and bounds values can be entered interactively or derived from the
outermost detected GCPs (with a small margin).

---

## Step 2 — Validate Against 18649

Run detection on 18649 and compare output to the known-good `georef/18649.json`
that was extracted from the original script. No tiling needed — just confirm the
numbers match.

```bash
export PATH=/opt/homebrew/bin:$PATH
python3 scripts/detect_gcps.py 18649
```

**Validation checklist:**
- Detected meridian count matches: **27**
- Detected parallel count matches: **3**
- Detected px/arcmin matches: **~577.68**
- Each GCP pixel coordinate is within ~5px of the values in `georef/18649.json`:

| lon | lat | expected col | expected row |
|-----|-----|------|------|
| −122.6667 | 37.9167 | 1554.0 | 3620 |
| −122.5833 | 37.8333 | 4420.5 | 7262 |
| −122.5000 | 37.7500 | 7307.5 | 10900 |
| *(etc. — all 15 GCPs)* | | | |

Differences < 5px are fine. > 20px indicates a detection bug.

If the numbers match, commit the script and proceed.

---

## Step 3 — Detect GCPs for Chart 18654

```bash
# Inspect dimensions and confirm no embedded georef
gdalinfo charts/18654.pdf

# Open charts/18654.pdf visually to read the border tick labels:
# - Westernmost and easternmost longitude labeled on border
# - Northernmost and southernmost latitude labeled on border
# - Tick interval (likely 5' as on 18649)

# Run detection
python3 scripts/detect_gcps.py 18654
```

**What to expect:**
- Detection parameters (`neatline_top`, open-water column for parallel scan) may need
  tuning — the script should print diagnostics so this is easy to adjust
- When prompted, enter the westernmost meridian longitude and northernmost parallel latitude
  (read from the PDF border labels), plus the tick interval
- Review the printed GCP table — columns should increase west→east, rows should
  increase north→south (larger row = further south in image coordinates)
- Script writes `georef/18654.json`

**Commit the result:**
```bash
git add georef/18654.json
git commit -m "Add georef GCPs for chart 18654"
```

---

## Definition of Done

- [ ] `scripts/detect_gcps.py` written and working
- [ ] `detect_gcps.py 18649` output matches `georef/18649.json` within ~5px per GCP
- [ ] `georef/18654.json` exists and GCPs look geometrically consistent
- [ ] Both `detect_gcps.py` and `georef/18654.json` committed

`tile_chart.py`, tiling 18654, and deploying are follow-on work.

---

## Key Gotchas

1. **Measure intersections directly** — don't use regression column estimates as final GCP values; 18649 had ~60–65px systematic bias in the regression.
2. **Chart is polyconic, not Mercator** — px/degree differs in x vs y; don't try to derive one axis from the other.
3. **Open-water column for parallel detection** — on 18649 `col = width // 4` worked; on 18654 it may land on land. Print a diagnostic and make it easy to override.
4. **`--xyz` is required** for gdal2tiles (relevant when tiling later) — without it, Leaflet gets TMS y-coordinates (flipped tiles).
