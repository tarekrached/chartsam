#!/usr/bin/env bash
# regen_tiles.sh — Regenerate PNG tiles from chart_mercator_crop.tif
# Run from repo root. Requires chart_mercator_crop.tif to exist.
# After this completes, run ./deploy.sh to push to GitHub Pages.

set -euo pipefail
export PATH=/opt/homebrew/bin:$PATH

REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"

if [ ! -f chart_mercator_crop.tif ]; then
  echo "ERROR: chart_mercator_crop.tif not found."
  echo "Run scripts/georeference_gcp.py and then crop with gdal_translate first."
  exit 1
fi

echo "▶ Removing old tiles..."
rm -rf public/tiles

echo "▶ Generating PNG tiles (z=5–14, 768px)..."
gdal2tiles.py --xyz --tilesize=768 -z 5-14 -r bilinear \
  --tiledriver=PNG --processes=4 \
  chart_mercator_crop.tif public/tiles/

echo "▶ Writing manifest + bounds..."
/opt/homebrew/bin/python3 scripts/write_manifest.py

echo "✓ Done. Run ./deploy.sh to publish."
