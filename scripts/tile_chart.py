#!/usr/bin/env python3
"""
tile_chart.py — Warp + tile pipeline driven by georef/<n>.json.

Usage:
    python3 scripts/tile_chart.py 18654
    python3 scripts/tile_chart.py 18649

Steps:
  1. Read georef/<n>.json for GCPs, neatline, and bounds.
  2. gdal_translate: embed GCPs from PDF → chart_gcp_<n>.tif
  3. gdalwarp -tps:  warp to EPSG:3857 → chart_mercator_<n>.tif
  4. gdal_translate: crop to neatline → chart_mercator_<n>_crop.tif
  5. gdal2tiles.py:  XYZ PNG tiles → public/tiles/
  6. write_manifest.py: bounds.json + tile-manifest.json
"""

import json, os, sys, subprocess, math

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        print(f"ERROR: command failed (exit {r.returncode})")
        sys.exit(r.returncode)
    return r


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/tile_chart.py <chart_num>")
        sys.exit(1)

    chart_num = sys.argv[1]
    georef    = os.path.join(REPO, "georef", f"{chart_num}.json")
    tif_path  = os.path.join(REPO, "charts_rasterized", f"{chart_num}.tif")

    if not os.path.exists(georef):
        print(f"ERROR: {georef} not found")
        print(f"  Run: python3 scripts/detect_gcps.py {chart_num}")
        sys.exit(1)
    if not os.path.exists(tif_path):
        print(f"ERROR: {tif_path} not found.")
        print(f"  Pre-rasterize first:")
        print(f"    python3 scripts/prerasterize.py {chart_num}")
        sys.exit(1)
    src = tif_path
    print(f"  Using pre-rasterized TIF: {tif_path}")

    with open(georef) as f:
        ref = json.load(f)

    gcps    = ref["gcps"]
    nl      = ref["neatline"]
    bounds  = ref["bounds"]
    title   = ref.get("title", f"NOAA Chart {chart_num}")

    gcp_tif  = os.path.join(REPO, f"chart_gcp_{chart_num}.tif")
    merc_tif = os.path.join(REPO, f"chart_mercator_{chart_num}.tif")
    crop_tif = os.path.join(REPO, f"chart_mercator_{chart_num}_crop.tif")
    tiles_dir = os.path.join(REPO, "public", "tiles")

    print(f"\n=== tile_chart.py — {chart_num}: {title} ===")
    print(f"  {len(gcps)} GCPs  |  neatline {nl['width']}×{nl['height']} px")

    # ── Step 1: embed GCPs ───────────────────────────────────────────────────
    print(f"\n── Step 1: Embed GCPs → {os.path.basename(gcp_tif)} ──────────────")
    gcp_args = []
    for g in gcps:
        gcp_args += ["-gcp", str(g["pixel_col"]), str(g["pixel_row"]),
                     str(g["lon"]), str(g["lat"])]

    run(["gdal_translate", "-a_srs", "EPSG:4326"] + gcp_args
        + ["-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
           "-co", "PREDICTOR=2", "-co", "BIGTIFF=IF_SAFER",
           src, gcp_tif])

    # ── Step 2: TPS warp to Web Mercator ────────────────────────────────────
    print(f"\n── Step 2: TPS warp → {os.path.basename(merc_tif)} ─────────────")
    print("  (thin-plate spline — may take several minutes ...)")
    run(["gdalwarp",
         "-tps",     # Thin-plate spline: required for polyconic projection.
                     # NOAA charts have slightly curved meridians (~22 px over chart height).
                     # Affine warp cannot model this; TPS fits the residual distortion.
                     # Trade-off: TPS is slow on large rasters — use charts_rasterized/ to speed up.
         "-t_srs", "EPSG:3857",
         "-r", "bilinear",
         "-co", "TILED=YES",
         "-co", "COMPRESS=DEFLATE",
         "-co", "PREDICTOR=2",
         "-co", "BIGTIFF=IF_SAFER",
         "-overwrite",
         gcp_tif, merc_tif])

    # ── Step 3: crop to neatline ─────────────────────────────────────────────
    print(f"\n── Step 3: Crop neatline → {os.path.basename(crop_tif)} ─────────")
    run(["gdal_translate",
         "-srcwin", str(nl["col"]), str(nl["row"]),
         str(nl["width"]), str(nl["height"]),
         "-co", "TILED=YES",
         "-co", "COMPRESS=DEFLATE",
         "-co", "PREDICTOR=2",
         "-co", "BIGTIFF=IF_SAFER",
         merc_tif, crop_tif])

    # ── Step 4: generate XYZ tiles ───────────────────────────────────────────
    print(f"\n── Step 4: gdal2tiles → {tiles_dir}/ ───────────────────────────")
    import shutil
    if os.path.isdir(tiles_dir):
        print("  Removing old tiles ...")
        shutil.rmtree(tiles_dir)

    run(["gdal2tiles.py",
         "--xyz",            # XYZ tile convention (y=0 at top). Without this, gdal2tiles
                             # uses TMS (y=0 at bottom), flipping the y-axis → black tiles
                             # in Leaflet. This flag is mandatory.
         "--tilesize=768",   # 768px tiles declared as tileSize:256 in Leaflet → 3× CSS pixel
                             # density, pixel-perfect on Retina. Do NOT add zoomOffset:-1.
         "-z", "5-14",
         "-r", "bilinear",
         "--tiledriver=PNG",
         "--processes=4",
         crop_tif, tiles_dir])

    # ── Step 5: write bounds.json + tile-manifest.json ───────────────────────
    print(f"\n── Step 5: Write manifest ──────────────────────────────────────")
    # Pass bounds from georef JSON to write_manifest
    manifest_script = os.path.join(REPO, "scripts", "write_manifest.py")
    run(["python3", manifest_script,
         "--west",  str(bounds["west"]),
         "--east",  str(bounds["east"]),
         "--south", str(bounds["south"]),
         "--north", str(bounds["north"])])

    print(f"\n✓ Done — {chart_num}: {title}")
    print(f"  Tiles: {tiles_dir}")
    print(f"  Run ./deploy.sh to publish.")


if __name__ == "__main__":
    main()
