# Georeferencing & Tile Pipeline — Process Notes

How we got from a raw PDF scan to accurate XYZ tiles for Leaflet.
Written for future-you picking this up cold.

---

## The Problem

The PDF has no usable embedded georeferencing. We need to map pixel coordinates → WGS84 lat/lon.

**What we investigated:**
GDAL identifies the file as `Driver: PDF/Geospatial PDF` but `gdalinfo` returns zero GCPs,
no projection string, and an identity geotransform. NOAA used iTextSharp to produce these
PDFs (creation date 2018) — they are PDF conversions of traditional polyconic paper charts,
not the newer NOAA Custom Chart output (which does embed WGS84/Mercator projection
parameters). The Geospatial PDF extension fields were simply not populated.

**BSB/KAP (RNC) alternative:** NOAA's legacy Raster Navigational Charts shipped in BSB/KAP
format with reference points (GCPs) embedded in the file header, which GDAL could read
directly. However, NOAA discontinued the entire RNC program on **December 4, 2024** — no
BSB/KAP files exist for current charts.

---

## What Didn't Work

### Attempt 1: Use ENC bounding box as neatline
The ENC cell `US4CA11M` has bounds −123.516° to −122.403°.
We assumed these matched the chart's printed neatline. They don't —
the ENC cell is 2.25× larger than the chart. Scale was completely wrong.

### Attempt 2: GCP polynomial warp with ENC landmarks
Picked 5 ENC landmarks (Alcatraz, Bay Bridge, etc.) and ran `gdalwarp -order 2`.
All landmarks clustered in the eastern 10% of the chart → polynomial
extrapolation exploded to a **948,274 × 4,398,219 pixel** output needing 125 GB.

### Attempt 3: Affine warp with single Fort Point anchor
Fort Point (−122.477°, 37.809°) was confirmed at pixel (col=8167, row=8282)
via a full-res crop. Combined with meridian spacing for the x-scale, and
used `cos(lat)` Mercator formula to derive y-scale.

**Problem:** The chart uses a polyconic-like projection, NOT Mercator.
`LON_PER_PX / LAT_PER_PX = 1.26`, not `cos(37.8°) = 0.79`.
Using Mercator math for the latitude scale was wrong.

---

## What Worked: Programmatic GCP Detection

### Step 1 — Detect 27 longitude meridians

Scanned a thin horizontal strip just inside the top neatline (rows 203–402)
for columns with high concentrations of black pixels (vertical lines):

```python
black = (R < 60) & (G < 60) & (B < 60)
black_per_col = black.sum(axis=0)
# Find peaks → cluster centers
```

Result: **27 meridian lines**, evenly spaced at **577.68 px/arcminute**.
Linear regression `col = 375.92 + 577.68 * n` had RMS residual of only **3.2 px**
across the full 17,648 px chart width.

The first tick (n=0, col≈376) corresponds to **122°42' W**.

### Step 2 — Detect 3 latitude parallels

Scanned a vertical strip in open water for full-width horizontal black lines:

```python
black_per_row = black.sum(axis=1)
# Rows where ≥40% of strip width is black → horizontal lines
```

Found **3 parallels** confirmed independently across 4 different column ranges:

| Row | Latitude |
|-----|----------|
| 3620 | 37°55' N |
| 7262 | 37°50' N |
| 10900 | 37°45' N |

### Step 3 — Directly measure intersection pixel coordinates

At each parallel row, searched ±80px around each expected meridian column
and found the centroid of the dark cluster. This gives **15 GCPs** with
directly-measured pixel coordinates — no manual clicking, no assumptions.

The offsets from regression estimates were consistent (−60 to −65 px for most)
confirming the regression had a small systematic bias that this step corrects.

### Step 4 — Embed GCPs and TPS warp

```bash
gdal_translate -a_srs EPSG:4326 -gcp col row lon lat ... chart.pdf chart_gcp.tif
gdalwarp -tps -t_srs EPSG:3857 -r bilinear chart_gcp.tif chart_mercator.tif
```

**Why TPS (thin-plate spline) not `-order 1`?**
- TPS passes exactly through all 15 GCPs (no residual at GCP locations)
- Handles the polyconic→Mercator reprojection correctly between GCPs
- With 15 well-distributed points it doesn't extrapolate wildly

---

## Accuracy

Verified by comparing ENC-reported positions for 5 named landmarks
to their locations in the warped output:

| Landmark | Offset |
|----------|--------|
| Alcatraz Light | ~40 m |
| Point Bonita Light | ~27 m |
| Point Diablo Light | ~56 m |
| GG Bridge N Light | ~30 m |
| Fort Point | ~20 m |

Offsets are **inconsistent in direction** (some SE, some NW) → not a systematic
georeferencing error. This is the **inherent positional accuracy of the printed chart**
(1:40,000 NOAA paper charts are rated ±40–75 m).

**No further improvement is possible through the georeferencing step.** The offsets reflect
the inherent positional accuracy of the source chart compilation, not the warp method.
ENC overlay is the right validation tool: compare warped output to ENC buoy/landmark
positions to confirm residuals are random (not systematic).

---

## Tile Generation — Critical Gotcha

### TMS vs XYZ y-axis flip

`gdal2tiles.py` defaults to **TMS** tile convention:
- TMS: y=0 at the **south** (bottom)
- XYZ/Slippy Map (Leaflet default): y=0 at the **north** (top)

Without `--xyz`, tiles are stored at TMS y-coordinates.
Leaflet requests tiles at XYZ y-coordinates.
The y values don't match → tiles serve content from the wrong location
→ many tiles appear **100% black** (showing empty ocean or nodata).

**Fix: always use `--xyz`:**
```bash
gdal2tiles.py --xyz --tilesize=768 -z 5-14 -r bilinear \
  --tiledriver=PNG --processes=4 chart_mercator_crop.tif public/tiles/
```

### Crop to neatline before tiling

The TPS warp fills areas outside the chart's valid extent with black (nodata=0).
Crop to the neatline first:

```bash
# Neatline in source image: col 173, row 202, width 17455, height 13428
gdal_translate -srcwin 173 202 17455 13428 chart_mercator.tif chart_mercator_crop.tif
```

### Edge tiles at low zoom are legitimately mostly black

At z=5–8, one tile covers many degrees. The chart only occupies 0.5°×0.3°,
so edge tiles at low zoom are mostly black (nodata outside chart extent).
This is expected and harmless — Leaflet just shows nothing outside the chart area.

### write_manifest.py must not depend on tilemapresource.xml

`gdal2tiles --xyz` does NOT generate `tilemapresource.xml` (that's TMS-only).
`write_manifest.py` was updated to derive bounds from the tile files directly
using the XYZ tile→lonlat formula:

```python
def tile_to_lonlat(z, x, y):
    n = 2 ** z
    lon_w = x / n * 360 - 180
    lon_e = (x + 1) / n * 360 - 180
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_w, lat_s, lon_e, lat_n
```

Geographic bounds in `bounds.json` are hardcoded to the actual chart neatline
(not the tile extents, which are huge at low zoom levels).

---

## Final Pipeline

Georeferencing and tiling are separate steps. GCP metadata is stored in
`georef/<n>.json` (committed to git) so tiles can be regenerated at any time
without re-running detection.

```bash
export PATH=/opt/homebrew/bin:$PATH

# 1. Detect GCPs and write georef metadata (once per chart)
#    Interactive — confirms lon/lat assignments for detected graticule lines
python3 scripts/detect_gcps.py 18649
# → georef/18649.json

# 2. Warp + tile from georef metadata
#    Runs: gdal_translate (embed GCPs) → gdalwarp -tps → gdal_translate -srcwin → gdal2tiles
python3 scripts/tile_chart.py 18649
# → public/tiles/, public/bounds.json, public/tile-manifest.json
```

Tile spec: `--xyz --tilesize=768 -z 5-14 --tiledriver=PNG`

Result: **~613 PNG tiles, ~48 MB**, zoom 5–14, ~30–60 m positional accuracy.
768px tiles at 3× CSS density = pixel-perfect on Retina iPhone (3× DPR).
Service worker pre-caches z5–13 on install (~22 MB); z14 cached lazily or via the offline button.

The hardcoded chart 18649 values (GCPs, neatline, bounds) previously embedded in
`scripts/georeference_gcp.py` are now stored in `georef/18649.json`.

---

## Environment Notes

- GDAL 3.12.3 at `/opt/homebrew/bin/`
- Python with osgeo: `/opt/homebrew/bin/python3` (NOT `/usr/bin/python3`)
- Always set: `export PATH=/opt/homebrew/bin:$PATH`
- Pillow + numpy available in homebrew Python env
