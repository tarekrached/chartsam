# chartsam — Developer Guide

NOAA Chart 18649 (SF Bay entrance) as an offline-capable PWA.
Hosted on GitHub Pages; primary use case is navigation on the water without cell service.

## Architecture

- **Leaflet** renders XYZ PNG tiles from `public/tiles/`
- **Service worker** (`sw.js`) pre-caches app shell + z5–13 tiles on install; z14 cached lazily
- **GitHub Pages** serves from `gh-pages` branch (tiles too large for `main`)
- **`deploy.sh`** syncs `public/` → gh-pages via git worktree

## Key Files

| File | Purpose |
|------|---------|
| `public/app.js` | Leaflet map, GPS overlay, offline download button |
| `public/sw.js` | Service worker (cache strategy, version gating) |
| `public/bounds.json` | Chart bounds + zoom range — written by `tile_chart.py` |
| `public/tile-manifest.json` | All tile paths for SW pre-cache — written by `tile_chart.py` |
| `regen_tiles.sh` | Full tile pipeline for chart 18649 |
| `deploy.sh` | Push `public/` to gh-pages branch |
| `georef/<n>.json` | GCPs + neatline + bounds per chart — committed to git |
| `charts/<n>.pdf` | Source PDF scans — gitignored, download separately |
| `scripts/detect_gcps.py` | Programmatic GCP detection; writes `georef/<n>.json` |
| `scripts/tile_chart.py` | Warp + tile pipeline driven by `georef/<n>.json` |
| `scripts/write_manifest.py` | Builds `bounds.json` + `tile-manifest.json` from tile files |
| `GEOREF_PROCESS.md` | Full write-up of the georeferencing approach |

## Common Commands

```bash
# Regenerate tiles for an existing chart (georef JSON already committed)
export PATH=/opt/homebrew/bin:$PATH
python3 scripts/tile_chart.py 18649
./deploy.sh

# Add a new chart from scratch
python3 scripts/detect_gcps.py 18654   # interactive — detects GCPs, writes georef/18654.json
git add georef/18654.json && git commit -m "Add georef for chart 18654"
python3 scripts/tile_chart.py 18654
./deploy.sh
```

## Tile Specs

- **Format:** PNG, 768px tiles declared as `tileSize: 256` in Leaflet → 3× CSS density → pixel-perfect on Retina iPhone
- **Zoom range:** z5–14 (~613 tiles, ~48 MB total)
- **SW install pre-caches:** z5–13 only (~22 MB); z14 lazy or via offline button
- **Tiles are gitignored** — regenerate locally with `regen_tiles.sh`

## SW Cache Versioning

The cache version (`CACHE_VERSION` in `sw.js`, currently `v6`) must be bumped whenever:
- App shell files change AND you need to ensure devices pick them up
- The tile set is regenerated (to invalidate old tile cache)

Bump by changing `v6` → `v7` (or next) in `sw.js`. The version is shown in the map attribution ("NOAA Chart 18649 · v6") so you can confirm which version a device is running.

**Two-reload behavior is expected:** after a SW version bump, the first page load installs the new SW; the second load uses it. Devices showing "· uncached" or an old version need one more reload.

## Critical Gotchas

1. **`--xyz` flag is required** for `gdal2tiles.py` — without it, tiles use TMS y-axis (flipped) and Leaflet shows black tiles or wrong locations.
2. **`tileSize: 256` with no `zoomOffset`** — the 768px files are larger than a standard tile but we declare them as 256px; Leaflet handles the rest. Do not add `zoomOffset: -1`.
3. **`r.clone()` before `return r`** in SW network-first handler — if you clone after returning, the body is already consumed and caching silently fails.
4. **SW cache vs browser HTTP cache** — `caches.addAll()` bypasses browser HTTP cache; SW's `fetch()` in network-first does not. If a cached response isn't updating on devices, bump the SW version (forces `addAll()` on reinstall).
5. **Deploy script uses git worktree** for gh-pages — tiles are pushed there, not to `main`. Never commit tiles to `main`.

## Offline-First Priority

This app must work without cell service. Do not add features that degrade gracefully — if something needs the network, make sure it's optional or the offline path is explicitly handled. The z14 lazy-cache design is intentional: z5–13 are always available offline after install; z14 requires prior browsing or the download button.
