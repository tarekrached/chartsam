#!/usr/bin/env python3
"""
prerasterize.py — Pre-rasterize NOAA chart PDFs to GeoTIFF for fast GDAL access.

Converts charts/<n>.pdf → charts_rasterized/<n>.tif at 400 DPI using DEFLATE
compression. Pre-rasterizing once avoids repeated slow PDF → raster decoding in
detect_gcps.py and tile_chart.py. The resulting TIFs are gitignored; regenerate
them locally with this script.

Usage:
    python3 scripts/prerasterize.py              # rasterize all charts/*.pdf
    python3 scripts/prerasterize.py 18649        # rasterize one chart
    python3 scripts/prerasterize.py --skip-existing
    python3 scripts/prerasterize.py 18649 --skip-existing
"""

import sys, os, subprocess, glob, argparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rasterize(chart_num, skip_existing=False):
    pdf_path = os.path.join(REPO, "charts", f"{chart_num}.pdf")
    tif_dir  = os.path.join(REPO, "charts_rasterized")
    tif_path = os.path.join(tif_dir, f"{chart_num}.tif")

    if not os.path.exists(pdf_path):
        print(f"ERROR: {pdf_path} not found — download the NOAA chart PDF first")
        return False

    os.makedirs(tif_dir, exist_ok=True)

    if skip_existing and os.path.exists(tif_path):
        print(f"  {chart_num}: skipping (already exists: {tif_path})")
        return True

    print(f"  {chart_num}: rasterizing {pdf_path} → {tif_path} ...")
    env = {**os.environ, "GDAL_PDF_DPI": "400"}
    result = subprocess.run(
        [
            "gdal_translate",
            "-of", "GTiff",
            "-co", "TILED=YES",
            "-co", "COMPRESS=DEFLATE",
            "-co", "PREDICTOR=2",
            "-co", "BIGTIFF=IF_SAFER",
            pdf_path, tif_path,
        ],
        env=env,
    )
    if result.returncode != 0:
        print(f"ERROR: gdal_translate failed for chart {chart_num}")
        return False

    # Print output dimensions and file size
    size_mb = os.path.getsize(tif_path) / 1024 / 1024
    info = subprocess.run(
        ["gdalinfo", "-json", tif_path],
        capture_output=True, text=True,
    )
    dims = ""
    if info.returncode == 0:
        import json
        try:
            meta = json.loads(info.stdout)
            size = meta.get("size", [])
            if size:
                dims = f"  dimensions: {size[0]}×{size[1]} px"
        except (json.JSONDecodeError, KeyError):
            pass
    print(f"  {chart_num}: done.{dims}  file size: {size_mb:.1f} MB")
    return True


def main():
    ap = argparse.ArgumentParser(
        description="Pre-rasterize NOAA chart PDFs to GeoTIFF at 400 DPI"
    )
    ap.add_argument("chart_num", nargs="?",
                    help="Chart number (e.g. 18649). Omit to rasterize all charts/*.pdf")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip charts that already have a TIF in charts_rasterized/")
    args = ap.parse_args()

    if args.chart_num:
        ok = rasterize(args.chart_num, skip_existing=args.skip_existing)
        sys.exit(0 if ok else 1)
    else:
        pdfs = sorted(glob.glob(os.path.join(REPO, "charts", "*.pdf")))
        if not pdfs:
            print("No PDFs found in charts/")
            sys.exit(1)
        print(f"Found {len(pdfs)} chart PDF(s):")
        failed = []
        for pdf in pdfs:
            num = os.path.splitext(os.path.basename(pdf))[0]
            ok = rasterize(num, skip_existing=args.skip_existing)
            if not ok:
                failed.append(num)
        if failed:
            print(f"\nFailed: {', '.join(failed)}")
            sys.exit(1)
        print("\nAll charts rasterized.")


if __name__ == "__main__":
    main()
