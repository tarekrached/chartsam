# PWA Plan — SF Bay Nautical Chart

## Goal
View NOAA chart 18649 on iPhone offline with GPS position overlay.
Hosted on GitHub Pages (HTTPS required for GPS API).

## Current State
- ✅ ~613 XYZ PNG tiles (z=5–14, 768px, ~48 MB), ~30–60 m accuracy
- ✅ `public/bounds.json` — chart geographic bounds + zoom range (maxZoom: 14)
- ✅ `public/tile-manifest.json` — list of all tile paths
- ✅ `public/index.html`, `app.js`, `sw.js`, `manifest.json` — complete
- ✅ App icons (icon-192.png, icon-512.png) — compass rose on navy blue
- ✅ Deployed to GitHub Pages (gh-pages branch via deploy.sh)
- ✅ Offline download button — pre-caches all tiles on demand
- ✅ Cache version shown in attribution label (e.g. "NOAA Chart 18649 · v6")
- ✅ Service worker v6 — network-first for app shell, cache-first for tiles
- ❌ Tiles not committed to git (gitignored, must regenerate locally with regen_tiles.sh)

---

## Tasks

### 1. Audit and fix existing PWA files

`app.js` and `sw.js` were written before the tile pipeline was finalized.
Key things to verify/fix:
- Tile URL template: `tiles/{z}/{x}/{y}.jpg` (XYZ, not TMS)
- `bounds.json` loading: center map on chart, set min/max zoom
- GPS marker: watch position, update in real time
- Service worker: pre-cache all tiles from `tile-manifest.json` on install

### 2. Create app icons

Two PNGs needed for `manifest.json`:
- `public/icon-192.png` (192×192)
- `public/icon-512.png` (512×512)

Suggestion: dark blue background (#1a3a5c) with a simplified compass rose or
anchor glyph. Can generate programmatically with Pillow.

### 3. GitHub Pages deployment

**Repo structure for GitHub Pages:**
GitHub Pages serves from either `/` (root) or `/docs` folder, or a `gh-pages` branch.

Recommended approach: serve from `/public` via `gh-pages` branch.

Steps:
1. Create GitHub repo (e.g. `nautical-charts`)
2. Push code to `main`
3. Regenerate tiles locally, push `public/tiles/` to `gh-pages` branch separately
   (tiles are too large for normal commits; use `git worktree` or a deploy script)
4. Enable GitHub Pages → source: `gh-pages` branch, root `/`

**Alternative:** Use `gh-pages` npm package or a GitHub Action to auto-deploy
`public/` on push to `main`.

**HTTPS:** GitHub Pages provides HTTPS automatically — required for
`navigator.geolocation` on iOS.

### 4. Tile size consideration

Current: 181 tiles × ~28 KB avg = 5.1 MB total.
This fits comfortably in a GitHub Pages repo and in iOS browser cache.
Service worker pre-caches all tiles on first load (requires one online visit).

### 5. iOS-specific considerations

- iOS Safari requires HTTPS for GPS (GitHub Pages provides this ✅)
- PWA "Add to Home Screen" via Safari share sheet
- `manifest.json` needs `display: standalone` and correct icon paths ✅
- Service worker scope must be at root of served path
- Test GPS accuracy: enable "Precise Location" in iOS Settings → Privacy

---

## File Checklist for New Session

Read these files at the start of the new session:
- `GEOREF_PROCESS.md` — how tiles were generated, all the gotchas
- `CHART_FINDINGS.md` — chart geography, bounds, accuracy
- `public/index.html` — current PWA shell
- `public/app.js` — current Leaflet + GPS code
- `public/sw.js` — current service worker
- `public/manifest.json` — current PWA manifest
- `public/bounds.json` — current bounds (verify before using)

---

## Suggested Session Prompt

> "Continue building the nautical chart PWA. Read PWA_PLAN.md, GEOREF_PROCESS.md,
> and the existing public/ files first. The tiles are already generated and correct.
> Goal: working PWA on GitHub Pages with offline tile caching and GPS overlay.
> Start by auditing the existing public/ files against the current tile structure,
> then implement any fixes, create the app icons, and set up GitHub Pages deployment."
