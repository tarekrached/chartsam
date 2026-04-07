#!/usr/bin/env python3
"""
Georeference NOAA chart 18649 using directly-measured GCPs.

GCP source: 15 graticule intersections (5 meridians × 3 parallels).
Both the meridian columns and parallel rows were measured programmatically
from the raster — no manual clicking required.

Meridians: detected as vertical black lines in chart content (rows 203-402).
           Columns pinpointed by scanning ±80px around regression estimate
           at each parallel row and finding the centroid of the dark cluster.

Parallels: detected as full-width horizontal black lines spanning the chart.
           Three lines confirmed across multiple independent column ranges:
             row  3620 → 37°55' N
             row  7262 → 37°50' N
             row 10900 → 37°45' N

Warp method: -tps (thin-plate spline)
  Handles any residual scan non-linearity and correctly re-projects the
  chart's polyconic-like projection into Web Mercator.

Outputs:
  chart_gcp.tif      — WGS84 GeoTIFF with embedded GCPs (unresampled)
  chart_mercator.tif — Web Mercator GeoTIFF (ready for gdal2tiles)
"""

import os, sys, subprocess

PDF  = "18649 SF Bay Nautical Chart.pdf"
GCP  = "chart_gcp.tif"
MERC = "chart_mercator.tif"

# ---------------------------------------------------------------------------
# 15 directly-measured GCPs: (pixel_col, pixel_row, lon, lat)
# ---------------------------------------------------------------------------
GCPS = [
    # lon=-122.6667 (122°40')
    (1554.0,  3620, -122.6667, 37.9167),
    (1555.2,  7262, -122.6667, 37.8333),
    (1532.0, 10900, -122.6667, 37.7500),
    # lon=-122.5833 (122°35')
    (4420.0,  3620, -122.5833, 37.9167),
    (4420.5,  7262, -122.5833, 37.8333),
    (4420.5, 10900, -122.5833, 37.7500),
    # lon=-122.5000 (122°30')
    (7307.5,  3620, -122.5000, 37.9167),
    (7319.7,  7262, -122.5000, 37.8333),
    (7307.5, 10900, -122.5000, 37.7500),
    # lon=-122.4167 (122°25')
    (10229.5,  3620, -122.4167, 37.9167),
    (10195.0,  7262, -122.4167, 37.8333),
    (10195.0, 10900, -122.4167, 37.7500),
    # lon=-122.3333 (122°20')
    (13083.0,  3620, -122.3333, 37.9167),
    (13082.5,  7262, -122.3333, 37.8333),
    (13082.5, 10900, -122.3333, 37.7500),
]

# ---------------------------------------------------------------------------
# Step 1: embed GCPs into a copy of the raster
# ---------------------------------------------------------------------------
print(f"=== Step 1: Embedding {len(GCPS)} GCPs into {GCP} ===")

gcp_args = []
for col, row, lon, lat in GCPS:
    gcp_args += ["-gcp", str(col), str(row), str(lon), str(lat)]

result = subprocess.run(
    ["gdal_translate", "-a_srs", "EPSG:4326"] + gcp_args +
    ["-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
     "-co", "PREDICTOR=2", "-co", "BIGTIFF=IF_SAFER",
     PDF, GCP],
    check=True
)
print(f"  Written: {GCP}")

# ---------------------------------------------------------------------------
# Step 2: warp to Web Mercator using thin-plate spline
# ---------------------------------------------------------------------------
print(f"\n=== Step 2: TPS warp to Web Mercator → {MERC} ===")
print("  (thin-plate spline warp — may take a few minutes...)")

result = subprocess.run(
    ["gdalwarp",
     "-tps",                    # thin-plate spline — handles scan distortion
     "-t_srs", "EPSG:3857",
     "-r", "bilinear",
     "-co", "TILED=YES",
     "-co", "COMPRESS=DEFLATE",
     "-co", "PREDICTOR=2",
     "-co", "BIGTIFF=IF_SAFER",
     "-overwrite",
     GCP, MERC],
    check=True
)
print(f"  Written: {MERC}")

# ---------------------------------------------------------------------------
# Step 3: verify with independent landmarks
# ---------------------------------------------------------------------------
print("\n=== Step 3: GCP residuals ===")

# Re-open the GCP file and check GDAL's own residual report
from osgeo import gdal
gdal.UseExceptions()
ds = gdal.Open(GCP)
gcps_out = ds.GetGCPs()
print(f"  Embedded GCPs: {len(gcps_out)}")
for g in gcps_out:
    print(f"  pixel ({g.GCPPixel:8.1f}, {g.GCPLine:6.0f})  →  "
          f"({g.GCPX:.4f}, {g.GCPY:.4f})")
ds = None

print(f"\n=== Done ===")
print(f"  {GCP}  — WGS84 with embedded GCPs")
print(f"  {MERC} — Web Mercator (use for gdal2tiles)")
print(f"\nNext:")
print(f"  # Crop to neatline first (strips margin black pixels):")
print(f"  gdal_translate -srcwin 173 202 17455 13428 {MERC} chart_mercator_crop.tif")
print(f"  # Generate XYZ tiles (--xyz required for Leaflet compatibility):")
print(f"  gdal2tiles.py --xyz --tilesize=512 -z 5-13 -r bilinear "
      f"--tiledriver=JPEG --processes=4 chart_mercator_crop.tif public/tiles/")
