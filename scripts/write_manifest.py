#!/usr/bin/env python3
"""
Generate public/tile-manifest.json and public/bounds.json from the tile directory.

Run this after gdal2tiles.py. The manifest is used by the service worker
to pre-cache all tiles for offline use.
"""

import json
import math
import os
import xml.etree.ElementTree as ET

TILES_DIR   = "public/tiles"
MANIFEST    = "public/tile-manifest.json"
BOUNDS_FILE = "public/bounds.json"
TMR         = os.path.join(TILES_DIR, "tilemapresource.xml")

# ---------------------------------------------------------------------------
# Derive bounds from the tile files themselves (works with both TMS and --xyz)
# Falls back to tilemapresource.xml if present (TMS mode only).
# ---------------------------------------------------------------------------

def tile_to_lonlat(z, x, y):
    """Return (lon_w, lat_s, lon_e, lat_n) for an XYZ tile."""
    n = 2 ** z
    lon_w = x / n * 360 - 180
    lon_e = (x + 1) / n * 360 - 180
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_w, lat_s, lon_e, lat_n

# Walk tiles to find zoom range, tile extension, and geographic bounds
zoom_levels = set()
tile_ext = None
all_lonlat = []

for z_dir in os.listdir(TILES_DIR):
    z_path = os.path.join(TILES_DIR, z_dir)
    if not os.path.isdir(z_path) or not z_dir.isdigit():
        continue
    z = int(z_dir)
    zoom_levels.add(z)
    for x_dir in os.listdir(z_path):
        x_path = os.path.join(z_path, x_dir)
        if not os.path.isdir(x_path):
            continue
        x = int(x_dir)
        for fname in os.listdir(x_path):
            ext = fname.rsplit(".", 1)[-1] if "." in fname else None
            if ext in ("jpg", "jpeg", "png"):
                tile_ext = "jpg" if ext in ("jpg", "jpeg") else "png"
                y = int(fname.split(".")[0])
                all_lonlat.append(tile_to_lonlat(z, x, y))

zoom_levels = sorted(zoom_levels)
tile_ext = tile_ext or "jpg"

# Use the actual chart neatline bounds (not tile extents, which are much larger at low zoom)
CHART_W, CHART_E = -122.7059, -122.2023
CHART_S, CHART_N =  37.6871,   37.9932

bounds = {
    "west":  CHART_W,
    "south": CHART_S,
    "east":  CHART_E,
    "north": CHART_N,
    "minZoom": zoom_levels[0],
    "maxZoom": zoom_levels[-1],
    "tileExtension": tile_ext,
}

with open(BOUNDS_FILE, "w") as f:
    json.dump(bounds, f, indent=2)
print(f"Written: {BOUNDS_FILE}")
print(f"  Bounds: {bounds['west']:.4f}W, {bounds['south']:.4f}S, "
      f"{bounds['east']:.4f}E, {bounds['north']:.4f}N")
print(f"  Zoom: {bounds['minZoom']}–{bounds['maxZoom']}, tiles: .{tile_ext}")

# ---------------------------------------------------------------------------
# Walk tiles directory, collect all tile paths
# ---------------------------------------------------------------------------
tile_paths = []
for z_dir in sorted(os.listdir(TILES_DIR)):
    z_path = os.path.join(TILES_DIR, z_dir)
    if not os.path.isdir(z_path) or not z_dir.isdigit():
        continue
    for x_dir in sorted(os.listdir(z_path)):
        x_path = os.path.join(z_path, x_dir)
        if not os.path.isdir(x_path):
            continue
        for fname in sorted(os.listdir(x_path)):
            if fname.endswith(f".{tile_ext}"):
                tile_paths.append(f"tiles/{z_dir}/{x_dir}/{fname}")

with open(MANIFEST, "w") as f:
    json.dump(tile_paths, f)

total_size = sum(
    os.path.getsize(os.path.join("public", p))
    for p in tile_paths
)
print(f"\nWritten: {MANIFEST}")
print(f"  {len(tile_paths)} tiles, {total_size / 1_048_576:.1f} MB total")
