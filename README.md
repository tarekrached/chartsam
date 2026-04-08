# chartsam

A lark. NOAA Chart 18649 (Entrance to San Francisco Bay) as a Progressive Web App — viewable offline on an iPhone with a live GPS position overlay.

## What it does

- Displays a georeferenced raster scan of [NOAA Chart 18649](18649%20SF%20Bay%20Nautical%20Chart.pdf)
- GPS button centers the map on your position with an accuracy circle
- Works fully offline after one online visit (service worker pre-caches all tiles)
- Installable to home screen via Safari → Share → Add to Home Screen

**Live:** https://tarekrached.github.io/chartsam/

## Accuracy

~30–60 m positional accuracy, which matches the inherent accuracy of a 1:40,000 NOAA paper chart. Good enough to know which channel you're in; not a substitute for a proper chart plotter.

## Repo layout

```
public/          — the PWA (served from gh-pages branch)
  index.html
  app.js         — Leaflet map + GPS logic
  sw.js          — service worker, pre-caches all tiles
  tiles/         — XYZ PNG tiles z5–14, 768px (gitignored, regen locally)
  bounds.json    — chart bounds + zoom range
  tile-manifest.json — list of all tile paths for SW pre-caching

georef/          — georeferencing metadata, one JSON per chart (committed ✅)
  18649.json     — GCPs, neatline crop params, bounds for chart 18649

charts/          — source PDF scans (gitignored, download separately)

scripts/
  detect_gcps.py   — programmatic GCP detection; writes georef/<n>.json
  tile_chart.py    — warp + tile pipeline driven by georef/<n>.json
  write_manifest.py — builds bounds.json + tile-manifest.json

regen_tiles.sh   — full tile pipeline for chart 18649
deploy.sh        — pushes public/ including tiles to gh-pages branch
```

## Regenerating tiles

Tiles are not committed to git (too large). To regenerate:

```bash
export PATH=/opt/homebrew/bin:$PATH

# Tile from existing georef metadata (no re-detection needed)
python3 scripts/tile_chart.py 18649

# Deploy to GitHub Pages
./deploy.sh
```

To add a new chart from scratch:
```bash
# 1. Detect GCPs and write georef JSON (interactive — confirms lon/lat assignments)
python3 scripts/detect_gcps.py 18654

# 2. Review and commit georef/18654.json, then tile
python3 scripts/tile_chart.py 18654
./deploy.sh
```

## How the georeferencing works

The PDF has no embedded georeferencing. A Python script detects 27 longitude meridians and 3 latitude parallels directly from the scanned pixel data, producing 15 GCPs. GDAL then does a thin-plate-spline warp to Web Mercator. See `GEOREF_PROCESS.md` for the full write-up.
