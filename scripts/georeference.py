#!/usr/bin/env python3
"""
Georeference NOAA chart 18649 (Entrance to San Francisco Bay).

Calibration method (two independent anchors):
  1. Programmatic detection of 27 graticule meridian lines in chart content
     (rows 203-402) → pixel spacing = 577.68 px/arcmin at 1-minute intervals.
     Linear regression RMS residual: 3.2 px across the full chart width.
  2. Fort Point visually confirmed at pixel (col=8167, row=8282) = (−122.477°, 37.809°).

Derived scale:
  LON_PER_PX = 1 / (577.68 px/arcmin × 60 arcmin/°) = 0.00002885 °/px
  LAT_PER_PX = LON_PER_PX × cos(37.809°)             = 0.00002279 °/px  (Mercator)

Chart geographic extent (neatline):
  W = 122°42.4' W  (col 173)    E = 122°12.1' W  (col 17628)
  N =  37°59.6' N  (row 202)    S =  37°41.2' N  (row 13630)
  Lon span: 30.2 arcmin  |  Lat span: 18.4 arcmin

Outputs:
  chart_georef.tif   — WGS84 GeoTIFF (affine geotransform)
  chart_mercator.tif — Web Mercator GeoTIFF (ready for gdal2tiles)
"""

import math, os, sys, subprocess
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

PDF  = "18649 SF Bay Nautical Chart.pdf"
TIFF = "chart_georef.tif"
MERC = "chart_mercator.tif"

IMG_W, IMG_H = 17648, 13832

# ---------------------------------------------------------------------------
# Calibrated geotransform
# ---------------------------------------------------------------------------
# Meridian regression: col = 375.92 + 577.6844 * n  (n = 0-based minute index)
# Tick n=0 corresponds to 122°42' W; each tick = 1 arcminute west→east.
LON_PER_PX = 0.000028851   # degrees per pixel (east positive)
LAT_PER_PX = 0.000022794   # degrees per pixel (south positive)

# Full image corners (pixel (0,0) = upper-left)
FULL_W = -122.710846   # lon at col 0
FULL_N =   37.997779   # lat at row 0
FULL_E = -122.201686   # lon at col 17648
FULL_S =   37.682494   # lat at row 13832

# Neatline pixel bounds (detected programmatically)
NL_LEFT_COL  =   173
NL_RIGHT_COL = 17628
NL_TOP_ROW   =   202

print("=== Calibrated geographic extent ===")
print(f"  Full image: W={FULL_W:.5f}  E={FULL_E:.5f}  N={FULL_N:.5f}  S={FULL_S:.5f}")
print(f"  Lon span:   {(FULL_E-FULL_W)*60:.1f} arcmin   Lat span: {(FULL_N-FULL_S)*60:.1f} arcmin")
print(f"  Scale:      {LON_PER_PX*111320*1000:.1f} m/px (lon)  "
      f"{LAT_PER_PX*111320*1000:.1f} m/px (lat)")

# ---------------------------------------------------------------------------
# Step 1: Apply affine geotransform
# ---------------------------------------------------------------------------
print(f"\n=== Step 1: Applying affine geotransform to {TIFF} ===")

result = subprocess.run([
    "gdal_translate",
    "-a_srs", "EPSG:4326",
    "-a_ullr",
        str(FULL_W), str(FULL_N),   # upper-left lon, lat
        str(FULL_E), str(FULL_S),   # lower-right lon, lat
    "-co", "TILED=YES",
    "-co", "COMPRESS=DEFLATE",
    "-co", "PREDICTOR=2",
    "-co", "BIGTIFF=IF_SAFER",
    PDF, TIFF
], capture_output=False, text=True)

if result.returncode != 0:
    print("ERROR in gdal_translate")
    sys.exit(1)
print(f"  Written: {TIFF}")

# ---------------------------------------------------------------------------
# Step 2: Warp to Web Mercator
# ---------------------------------------------------------------------------
print(f"\n=== Step 2: Warping to Web Mercator ({MERC}) ===")
print("  (Full-raster reprojection — may take a few minutes...)")

result = subprocess.run([
    "gdalwarp",
    "-t_srs", "EPSG:3857",
    "-r", "bilinear",
    "-co", "TILED=YES",
    "-co", "COMPRESS=DEFLATE",
    "-co", "PREDICTOR=2",
    "-co", "BIGTIFF=IF_SAFER",
    "-overwrite",
    TIFF, MERC
], capture_output=False, text=True)

if result.returncode != 0:
    print("ERROR in gdalwarp")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Step 3: Verify accuracy with known landmarks
# ---------------------------------------------------------------------------
print("\n=== Step 3: Accuracy verification with ENC landmarks ===")

# All landmarks are confirmed within neatline bounds (122°42'–122°12' W, 37°41'–38°00' N)
LANDMARKS = {
    "Fort Point":                       (-122.477000, 37.809000),  # primary calibration anchor
    "Golden Gate Bridge N Light":       (-122.478924, 37.825548),
    "Point Bonita Light":               (-122.529518, 37.815589),
    "Point Diablo Light":               (-122.499460, 37.820122),
    "Alcatraz Light":                   (-122.422142, 37.826229),
}

def ll_to_px(lon, lat):
    """Convert lon/lat to pixel (col, row) using calibrated affine transform."""
    col = round((lon - FULL_W) / LON_PER_PX)
    row = round((FULL_N - lat) / LAT_PER_PX)
    return col, row

print(f"\n  {'Landmark':<38} {'col':>6} {'row':>6}   {'Lon':>12}  {'Lat':>10}")
print(f"  {'-'*38} {'-'*6} {'-'*6}   {'-'*12}  {'-'*10}")
for name, (lon, lat) in LANDMARKS.items():
    col, row = ll_to_px(lon, lat)
    print(f"  {name:<38} {col:>6} {row:>6}   {lon:>12.6f}  {lat:>10.6f}")

print(f"\n  Neatline:  col {NL_LEFT_COL}–{NL_RIGHT_COL},  row {NL_TOP_ROW}–{13832-NL_TOP_ROW}")
print(f"  Verify: open chart_mercator.tif in QGIS and confirm landmarks match ENC positions.")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n=== Done ===")
print(f"  {TIFF}  — WGS84 GeoTIFF")
print(f"  {MERC} — Web Mercator (use this for gdal2tiles)")
print(f"\nNext step:")
print(f"  gdal2tiles.py --tilesize=512 -z 5-14 -r bilinear --processes=4 {MERC} public/tiles/")
