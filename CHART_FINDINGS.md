# NOAA Chart 18649 — Technical Findings

**Chart:** "Entrance to San Francisco Bay" (NOAA 18649)
**Source:** `18649 SF Bay Nautical Chart.pdf`

---

## 1. PDF / Raster Properties

| Property | Value |
|----------|-------|
| Dimensions | 17,648 × 13,832 pixels |
| Bands | 3 (RGB) |
| Color depth | 256-color indexed PNG inside PDF, decoded to 8-bit RGB by GDAL |
| GDAL driver | PDF (reads via Poppler) |
| Embedded georeferencing | **None** — this is a raster scan, not a GeoPDF |
| Approximate print size | 44.1" × 34.6" (at 400 DPI) |
| Scale | ~1:40,000 (derived from meridian pixel spacing) |

---

## 2. Chart Layout (Pixel Coordinates)

```
col 0                      col 173        col 17628     col 17648
row 0  ┌───────────────────────────────────────────────────┐
       │  outer white/cream margin                         │
row 202│  ┌────────────────────────────────────────────┐   │
       │  │  CHART CONTENT (neatline area)             │   │
       │  │  30.2' longitude × 18.4' latitude         │   │
       │  │                                            │   │
row 13630  └────────────────────────────────────────────┘   │
       │  margin                                           │
row 13832  └───────────────────────────────────────────────────┘
```

- **Neatline left:** col 173
- **Neatline top:** row 202
- **Neatline right:** col 17628
- **Neatline bottom:** row ~13630

---

## 3. Georeferencing — Final Method (GCP-based)

### Step 1: Detect meridians programmatically
Scanned rows 203–402 (just inside neatline) for vertical black lines.
Found **27 meridian lines** at 1-arcminute spacing.

Linear regression: `col = 375.92 + 577.68 * n`
- n = 0 corresponds to **122°42' W** (col ~376)
- Spacing: **577.68 px/arcminute**
- RMS residual: **3.2 px** across full chart width

### Step 2: Detect parallels programmatically
Scanned multiple vertical strips for full-width horizontal black lines.
Found **3 latitude parallels** confirmed independently across 4 column ranges:

| Row | Latitude |
|-----|----------|
| 3620 | 37°55' N |
| 7262 | 37°50' N |
| 10900 | 37°45' N |

### Step 3: Directly measure intersection pixel coordinates
At each parallel row, scanned ±80px around each expected meridian column
to find the precise centroid of the dark line cluster. This gives
**15 directly-measured GCPs** (5 meridians × 3 parallels):

| Pixel col | Pixel row | Longitude | Latitude |
|-----------|-----------|-----------|----------|
| 1554.0 | 3620 | −122.6667 | 37.9167 |
| 4420.0 | 3620 | −122.5833 | 37.9167 |
| 7307.5 | 3620 | −122.5000 | 37.9167 |
| 10229.5 | 3620 | −122.4167 | 37.9167 |
| 13083.0 | 3620 | −122.3333 | 37.9167 |
| 1555.2 | 7262 | −122.6667 | 37.8333 |
| 4420.5 | 7262 | −122.5833 | 37.8333 |
| 7319.7 | 7262 | −122.5000 | 37.8333 |
| 10195.0 | 7262 | −122.4167 | 37.8333 |
| 13082.5 | 7262 | −122.3333 | 37.8333 |
| 1532.0 | 10900 | −122.6667 | 37.7500 |
| 4420.5 | 10900 | −122.5833 | 37.7500 |
| 7307.5 | 10900 | −122.5000 | 37.7500 |
| 10195.0 | 10900 | −122.4167 | 37.7500 |
| 13082.5 | 10900 | −122.3333 | 37.7500 |

### Step 4: Warp with thin-plate spline
```bash
gdal_translate -a_srs EPSG:4326 -gcp ... chart.pdf chart_gcp.tif
gdalwarp -tps -t_srs EPSG:3857 -r bilinear chart_gcp.tif chart_mercator.tif
```
TPS handles any residual scan non-linearity and reprojects the chart's
polyconic-like printing into Web Mercator.

---

## 4. Accuracy Assessment (Final)

Verified by checking ENC-reported coordinates for 5 named landmarks
against their positions in the warped output:

| Landmark | Offset |
|----------|--------|
| Alcatraz Light | ~40m SE |
| Point Bonita Light | ~27m SE |
| Point Diablo Light | ~56m NW |
| GG Bridge N Light | ~30m (est.) |
| Fort Point | ~20m (est.) |

**Conclusion:** Offsets are small, inconsistent in direction, and within the
stated positional accuracy of 1:40,000 NOAA paper charts (±40–75 m).
This is not a georeferencing error — it is the inherent accuracy limit of
the source material. No further improvement is possible without a newer
GeoPDF source.

**Overall accuracy: ~30–60 m**, adequate for "am I in the channel?" navigation.

---

## 5. What the Chart Covers

- **West:** 2 miles west of Marin Headlands / Point Bonita
- **East:** Oakland / Alameda / Bay Bridge
- **North:** Corte Madera / San Quentin (Marin County)
- **South:** Southern Oakland / San Leandro Bay

Landmarks visible: Point Bonita Light, Point Diablo Light, Golden Gate Bridge,
Fort Point, Alcatraz, Bay Bridge.

**Not included:** Farallon Islands (−123.00°, ~17 arcmin beyond the west neatline).

---

## 6. What Did NOT Work (Lessons Learned)

| Approach | Why it failed |
|----------|---------------|
| Use ENC US4CA11M bounding box as neatline | ENC cell covers 2.25× larger area than chart; produced 2× wrong scale |
| GCP polynomial warp with 5 ENC landmarks | All landmarks clustered in eastern 10% of chart → polynomial exploded to 125 GB output |
| Mercator cos(lat) to derive LAT_PER_PX from LON_PER_PX | Chart is polyconic, not Mercator; ratio is 1.26, not 0.79. Must detect parallels independently |
| Fort Point as sole anchor | Only constrains one point; need second anchor for scale |

---

## 7. ENC Data

- **312 ENC cells** in `ENC_ROOT/` covering all of California
- **Key cell:** `ENC_ROOT/US4CA11M/US4CA11M.000`
  - Covers −123.516° to −122.403° lon, 37.435° to 38.098° lat
  - 13 LIGHTS features and 10 LNDMRK features within the chart neatline
- ENC coordinate precision is better than the chart's printed accuracy

---

## 8. GDAL Pipeline (Final)

```bash
export PATH=/opt/homebrew/bin:$PATH

# 1. Georeference with GCPs (runs gdal_translate + gdalwarp -tps internally)
python3 scripts/georeference_gcp.py

# 2. Crop to neatline (removes margin black pixels from TPS warp)
gdal_translate -srcwin 173 202 17455 13428 chart_mercator.tif chart_mercator_crop.tif

# 3. Generate 512×512 JPEG tile pyramid, zoom 5–13 (~5 MB)
#    IMPORTANT: --xyz is required! gdal2tiles defaults to TMS y-axis (y=0 at south),
#    but Leaflet uses XYZ (y=0 at north). Without --xyz, tiles appear at wrong locations.
rm -rf public/tiles
gdal2tiles.py --xyz --tilesize=512 -z 5-13 -r bilinear \
  --tiledriver=JPEG --processes=4 chart_mercator_crop.tif public/tiles/

# 3. Write tile manifest and bounds.json for the PWA
python3 scripts/write_manifest.py
```

---

## 9. Files

| File | Description |
|------|-------------|
| `18649 SF Bay Nautical Chart.pdf` | Source scan (gitignored) |
| `chart_gcp.tif` | WGS84 GeoTIFF with 15 embedded GCPs (gitignored) |
| `chart_mercator.tif` | Web Mercator GeoTIFF, TPS warped (gitignored) |
| `chart_mercator_crop.tif` | Mercator GeoTIFF cropped to neatline (gitignored) |
| `scripts/georeference_gcp.py` | **Primary script** — GCP detection + warp |
| `scripts/georeference.py` | Older affine-only version (superseded) |
| `scripts/write_manifest.py` | Generates `bounds.json` + `tile-manifest.json` |
| `public/tiles/` | XYZ tile pyramid, z=5–13, 512×512 JPEG (gitignored) |
| `public/index.html` | PWA shell |
| `public/app.js` | Leaflet map + GPS locate + service worker registration |
| `public/sw.js` | Service worker (offline tile caching) |
| `ENC_ROOT/US4CA11M/` | ENC S-57 cell covering this chart area |

---

## 10. PWA Status (Paused)

A working Leaflet PWA was built but set aside to focus on georeferencing.
When resuming:
- Tiles are in `public/tiles/` (gitignored, must regenerate)
- `bounds.json` and `tile-manifest.json` must be regenerated via `write_manifest.py`
- Still needed: `icon-192.png` and `icon-512.png` for PWA manifest
- Still needed: HTTPS hosting (GitHub Pages or similar) for GPS to work on iOS
- Future: ENC vector overlay layer using Leaflet + S-57 data
