#!/usr/bin/env python3
"""
detect_gcps.py — Programmatic GCP detection for NOAA nautical charts.

Reads charts_rasterized/<n>.tif (pre-rasterized via prerasterize.py),
detects graticule intersections, prompts for coordinate assignment, and
writes georef/<n>.json.

Usage:
    python3 scripts/detect_gcps.py 18654             # interactive — new chart
    python3 scripts/detect_gcps.py 18649 --validate  # compare to existing georef JSON
    python3 scripts/detect_gcps.py 18649 --preview   # render overview PNGs and exit

Projection: the chart's title block shows the projection used. Most modern NOAA
coastal charts are Mercator (converted from polyconic after 1910); Great Lakes
charts remain polyconic. Charts 18649 and 18654 show ~22 px of meridian column
drift over chart height in pixel space — likely scan/digitisation distortion or
a conformal conic variant. TPS warp (gdalwarp -tps) handles any such residual
non-linearity regardless of the named projection; affine warp cannot.
"""

import sys, os, json, math, argparse
import numpy as np
from osgeo import gdal

gdal.UseExceptions()

REPO            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLACK_THRESH    = 60   # R < 60 → "black". Works for all NOAA scans seen so far;
                        # change only if a chart uses unusually light ink.
CENTROID_HALF   = 80   # ±80 px search window for centroid measurement. Wider than
                        # the ~22 px meridian curve, but stays well within the
                        # ~575 px/arcmin inter-meridian spacing.


# ---------------------------------------------------------------------------
# Signal-processing helpers
# ---------------------------------------------------------------------------

def find_peaks_1d(signal, min_height_frac=0.25, min_distance=20):
    """Local peaks above min_height_frac * max, at least min_distance apart."""
    thresh = signal.max() * min_height_frac
    peaks = []
    for i in range(1, len(signal) - 1):
        if signal[i] <= thresh:
            continue
        if signal[i] < signal[i - 1] or signal[i] < signal[i + 1]:
            continue
        if peaks and i - peaks[-1] < min_distance:
            if signal[i] > signal[peaks[-1]]:
                peaks[-1] = i
        else:
            peaks.append(i)
    return np.array(peaks, dtype=int)


def cluster_peaks(peaks, gap=30):
    """Merge peaks within gap pixels; return mean index of each cluster."""
    if len(peaks) == 0:
        return np.array([], dtype=int)
    clusters = [[int(peaks[0])]]
    for p in peaks[1:]:
        if p - clusters[-1][-1] <= gap:
            clusters[-1].append(int(p))
        else:
            clusters.append([int(p)])
    return np.array([int(round(np.mean(c))) for c in clusters])


# ---------------------------------------------------------------------------
# Core measurement
# ---------------------------------------------------------------------------

def _peak_weighted_avg(sums, origin, local_half=15):
    """
    Find the peak of `sums`, then return the weighted-average index in a
    ±local_half window around the peak, offset by `origin`.

    Using a local window prevents distant chart features from biasing the
    result when the global weighted average would be pulled away from the
    graticule line.
    """
    if sums.max() == 0:
        return None
    peak = int(np.argmax(sums))
    l0 = max(0, peak - local_half)
    l1 = min(len(sums) - 1, peak + local_half)
    local = sums[l0:l1 + 1]
    if local.sum() == 0:
        return None
    return float(np.average(np.arange(l0, l1 + 1), weights=local)) + origin


def measure_centroid(band, col_est, row_est, img_w, img_h,
                     half=CENTROID_HALF, row_band_half=15, threshold=BLACK_THRESH):
    """
    Find graticule intersection near (col_est, row_est) using 1-D projections.

    Step 1 — meridian column: scan a 200-row horizontal band ending ~100 rows
    ABOVE the parallel row.  Scanning away from the parallel avoids the
    parallel line itself dominating col_sums at every column, which would cause
    off-axis chart features to win.

    Step 2 — parallel row: scan a narrow ±row_band_half-col vertical band at the
    found meridian column, spanning ±half rows.  Sum dark pixels per row →
    peak + local weighted average → sub-pixel parallel row.

    Returns (col_float, row_float) or None if no dark pixels found.
    """
    # ── Step 1: find meridian column — vertical-persistence scan ─────────
    # Scan the full ±half row window but use vertical persistence so the
    # horizontal parallel line (which spans every column) is suppressed.
    c0  = max(0, col_est - half)
    c1  = min(img_w - 1, col_est + half)
    vr0 = max(0, row_est - half)
    vr1 = min(img_h - 1, row_est + half)
    full_strip = band.ReadAsArray(c0, vr0, c1 - c0 + 1, vr1 - vr0 + 1)
    col_sums   = _vertical_persistence(full_strip, threshold=threshold)
    best_col   = _peak_weighted_avg(col_sums, c0)
    if best_col is None:
        return None

    # ── Step 2: find parallel row — narrow vertical band at meridian col ──
    bc  = int(round(best_col))
    vc0 = max(0, bc - row_band_half)
    vc1 = min(img_w - 1, bc + row_band_half)
    vr0 = max(0, row_est - half)
    vr1 = min(img_h - 1, row_est + half)
    v_strip  = band.ReadAsArray(vc0, vr0, vc1 - vc0 + 1, vr1 - vr0 + 1)
    row_sums = (v_strip < threshold).sum(axis=1).astype(float)
    best_row = _peak_weighted_avg(row_sums, vr0)
    if best_row is None:
        return None

    return best_col, best_row


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _vertical_persistence(arr, threshold=BLACK_THRESH):
    """
    Per-column count of dark pixels that are part of a vertical run ≥ 2.
    Filters out isolated single-row features (horizontal lines, scattered marks)
    while retaining dashed vertical lines (meridians).
    """
    dark = arr < threshold
    # Row r is "vertically persistent" if dark AND (dark above or dark below)
    vp = dark[1:] & dark[:-1]          # shape (rows-1, cols)
    return vp.sum(axis=0).astype(float)


def _horizontal_persistence(arr, threshold=BLACK_THRESH):
    """
    Per-row count of dark pixels that are part of a horizontal run ≥ 2.
    Retains continuous horizontal lines (parallels) while suppressing
    vertical features and isolated marks.
    """
    dark = arr < threshold
    hp = dark[:, 1:] & dark[:, :-1]    # shape (rows, cols-1)
    return hp.sum(axis=1).astype(float)


def _greedy_min_spacing(candidates, scores, min_spacing):
    """
    Greedy selection: sort candidates by score desc, then accept each candidate
    that is at least min_spacing away from all previously accepted ones.
    Returns accepted candidates (in ascending order).

    Greedy selection is preferred over a fixed threshold because VP score levels
    vary between charts (coastline density, ink contrast). A threshold that works
    for 18649 would reject real meridians on a busier chart.
    """
    if len(candidates) == 0:
        return np.array([], dtype=int)
    order  = np.argsort(scores)[::-1]
    accepted = []
    for idx in order:
        c = candidates[idx]
        if all(abs(c - a) >= min_spacing for a in accepted):
            accepted.append(int(c))
    return np.array(sorted(accepted))


def detect_meridians(band, nl_top, img_w, img_h, nl_left=0, nl_right=None,
                     scan_row=None, min_spacing=200, scan_bottom=None):
    """
    Detect meridian (vertical graticule line) column positions.

    Scans the full scan region using vertical-persistence filtering, then uses
    a greedy best-score + minimum-spacing filter to select graticule meridians.

    `scan_row` is unused (kept for backward compat but ignored in favour of
    scanning the whole height).  Reading every 4th row to keep memory use down.

    Returns (meridian_cols, spacing_px, rms_px).
    """
    if nl_right is None:
        nl_right = img_w - nl_left
    if scan_bottom is None:
        scan_bottom = img_h - nl_top

    # Skip neatline border margins and sample every 4 rows for efficiency.
    # margin=400 ensures we skip both the outer neatline AND the inner margin
    # border that NOAA charts typically have ~165 px inside the outer neatline.
    margin    = 400
    c0        = nl_left  + margin
    c1        = nl_right - margin
    w         = c1 - c0
    row_step  = 4
    rows      = list(range(nl_top + 10, scan_bottom, row_step))

    print(f"  Scanning {len(rows)} rows (every {row_step}th), cols {c0}–{c1} ...")
    # Accumulate VP score per column across all sampled rows
    col_score = np.zeros(w, dtype=float)
    for r in rows:
        if r + 1 >= img_h:
            break
        row0 = band.ReadAsArray(c0, r,     w, 1).ravel().astype(np.int16)
        row1 = band.ReadAsArray(c0, r + 1, w, 1).ravel().astype(np.int16)
        col_score += ((row0 < BLACK_THRESH) & (row1 < BLACK_THRESH)).astype(float)

    raw_peaks  = find_peaks_1d(col_score, min_height_frac=0.05, min_distance=10)
    candidates = cluster_peaks(raw_peaks, gap=10) + c0   # image-space cols

    scores = col_score[candidates - c0]
    meridian_cols = _greedy_min_spacing(candidates, scores, min_spacing)

    if len(meridian_cols) == 0:
        print("  WARNING: no meridians detected")
        return np.array([], dtype=int), None, None

    print(f"  {len(meridian_cols)} meridians — cols {meridian_cols[0]}…{meridian_cols[-1]}")

    spacing_px = rms = None
    if len(meridian_cols) >= 4:
        n_arr = np.arange(len(meridian_cols), dtype=float)
        spacing_px, offset = np.polyfit(n_arr, meridian_cols.astype(float), 1)
        residuals  = meridian_cols - (offset + spacing_px * n_arr)
        rms        = math.sqrt((residuals ** 2).mean())
        print(f"  Spacing {spacing_px:.2f} px/tick  |  regression RMS {rms:.2f} px")
    else:
        print("  WARNING: < 4 meridians — skipping regression")

    return meridian_cols, spacing_px, rms


def detect_parallels(band, par_col, nl_top, img_w, img_h, nl_bottom=None,
                     min_spacing=500):
    """
    Scan a wide horizontal region for horizontal black lines (parallels).

    Uses horizontal-persistence filtering to score each row by how many
    consecutive-column dark runs it has.  Takes the top-scoring rows,
    then applies a minimum-spacing filter (keeping only the strongest row
    within each min_spacing-pixel window) to eliminate tightly clustered
    false positives from coastlines, annotations, etc.

    Returns parallel_rows array (sorted north→south, i.e. ascending row).

    90th percentile threshold: robust to varying chart contrast. 97th percentile
    found 106 spurious candidates on 18649 (only 3 real parallels).
    strip_half = img_w // 5: a 40%-width strip gives good SNR. Narrower strips
    fail when a coastline runs through the strip — the parallel signal is swamped.
    """
    if nl_bottom is None:
        nl_bottom = img_h - nl_top

    # Wide strip gives good SNR: use 40% of chart width centred on par_col.
    strip_half = img_w // 5
    c0 = max(0, par_col - strip_half)
    c1 = min(img_w - 1, par_col + strip_half)
    w  = c1 - c0

    print(f"  Scanning col strip {c0}–{c1} ({w} px wide) ...")
    v_strip   = band.ReadAsArray(c0, nl_top, w, nl_bottom - nl_top)
    row_score = _horizontal_persistence(v_strip)

    # Take rows above the 90th percentile of row_score as candidates
    thresh     = np.percentile(row_score, 90)
    strong     = np.where(row_score >= thresh)[0]
    if len(strong) == 0:
        print("  WARNING: no parallels found — try a different open-water column")
        return np.array([], dtype=int)

    # Cluster neighbouring rows, keep cluster peak
    candidates = cluster_peaks(strong, gap=5) + nl_top   # image-space rows
    candidates = candidates[
        (candidates > nl_top  + 100) &
        (candidates < nl_bottom - 100)
    ]

    if len(candidates) == 0:
        print("  WARNING: no parallels found after interior filter")
        return np.array([], dtype=int)

    scores = row_score[candidates - nl_top]
    parallel_rows = _greedy_min_spacing(candidates, scores, min_spacing)

    print(f"  {len(parallel_rows)} parallels — rows {list(parallel_rows)}")
    return parallel_rows


def detect_inset_boundary(band, nl_top, nl_left, nl_right, nl_bottom, img_w, img_h):
    """
    Scan the top 30% of the chart interior for anomalously strong horizontal lines
    (solid inset borders score 10-100x higher than dashed parallels).
    Returns (boundary_row, score) or None if no inset detected.

    Parallels score ~500-700; solid inset border scores 10000+.
    The 5000 threshold is safely between these: chart 18649 has no inset
    (max HP row score ~700); chart 18654's inset border scores ~12000.
    """
    search_bottom = nl_top + (nl_bottom - nl_top) // 3
    w = nl_right - nl_left
    strip = band.ReadAsArray(nl_left, nl_top, w, search_bottom - nl_top)
    row_score = _horizontal_persistence(strip)
    if row_score.max() < 5000:   # no anomalous line found
        return None
    boundary_local = int(np.argmax(row_score))
    return nl_top + boundary_local, float(row_score[boundary_local])


# ---------------------------------------------------------------------------
# GCP measurement table
# ---------------------------------------------------------------------------

def measure_gcps(band, meridian_cols, parallel_rows,
                 meridian_lons, parallel_lats, img_w, img_h):
    gcps = []
    hdr = f"  {'col_est':>8}  {'row_est':>8}  {'col_meas':>9}  {'row_meas':>9}  {'lon':>10}  {'lat':>9}"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for m_col, m_lon in zip(meridian_cols, meridian_lons):
        for p_row, p_lat in zip(parallel_rows, parallel_lats):
            result = measure_centroid(band, int(m_col), int(p_row), img_w, img_h)
            if result is None:
                print(f"  {m_col:8.0f}  {p_row:8.0f}  {'—':>9}  {'—':>9}  "
                      f"{m_lon:10.4f}  {p_lat:9.4f}  NO DARK PIXELS")
            else:
                c_col, c_row = result
                gcps.append({
                    "pixel_col": round(c_col, 1),
                    "pixel_row": int(round(c_row)),
                    "lon":       round(m_lon, 4),
                    "lat":       round(p_lat, 4),
                })
                print(f"  {m_col:8.0f}  {p_row:8.0f}  {c_col:9.1f}  {c_row:9.1f}  "
                      f"{m_lon:10.4f}  {p_lat:9.4f}")
    return gcps


# ---------------------------------------------------------------------------
# Interactive flow
# ---------------------------------------------------------------------------

def prompt(msg, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"  {msg}{suffix}: ").strip()
    return val if val else (str(default) if default is not None else "")


def detect_neatline(band, img_w, img_h):
    """
    Quick scan to find candidate neatline borders.
    Returns (nl_top, nl_left, nl_right, nl_bottom) as best guesses.
    """
    # Top neatline: first row (from top) where >50% of width is dark
    for r in range(0, min(img_h, 600)):
        row_data = band.ReadAsArray(0, r, img_w, 1)
        if (row_data < BLACK_THRESH).sum() > img_w * 0.5:
            nl_top = r
            break
    else:
        nl_top = 200

    # Bottom neatline: first row from bottom where >50% of width is dark
    for r in range(img_h - 1, max(0, img_h - 600), -1):
        row_data = band.ReadAsArray(0, r, img_w, 1)
        if (row_data < BLACK_THRESH).sum() > img_w * 0.5:
            nl_bottom = r
            break
    else:
        nl_bottom = img_h - 200

    # Left neatline: first col (from left) where >50% of height is dark
    for c in range(0, min(img_w, 600)):
        col_data = band.ReadAsArray(c, 0, 1, img_h)
        if (col_data < BLACK_THRESH).sum() > img_h * 0.5:
            nl_left = c
            break
    else:
        nl_left = 173

    # Right neatline: first col from right where >50% of height is dark
    for c in range(img_w - 1, max(0, img_w - 600), -1):
        col_data = band.ReadAsArray(c, 0, 1, img_h)
        if (col_data < BLACK_THRESH).sum() > img_h * 0.5:
            nl_right = c
            break
    else:
        nl_right = img_w - 173

    return nl_top, nl_left, nl_right, nl_bottom


def interactive_mode(chart_num, band, img_w, img_h):
    print("\n─── 1. Neatline detection ───────────────────────────────────────────")
    print("  Scanning for outer neatline borders ...")
    nl_top_d, nl_left_d, nl_right_d, nl_bot_d = detect_neatline(band, img_w, img_h)
    print(f"  Detected: top={nl_top_d}  left={nl_left_d}  "
          f"right={nl_right_d}  bottom={nl_bot_d}")
    print(f"  (Neatline = the FULL outer chart border for crop/bounds purposes)")

    nl_top    = int(prompt("Neatline top row",    nl_top_d))
    nl_left   = int(prompt("Neatline left col",   nl_left_d))
    nl_right  = int(prompt("Neatline right col",  nl_right_d))
    nl_bottom = int(prompt("Neatline bottom row", nl_bot_d))

    print("\n─── 1.5. Inset detection ────────────────────────────────────────────")
    print("  Scanning for inset boundary in top 30% of chart interior ...")
    inset_result = detect_inset_boundary(
        band, nl_top, nl_left, nl_right, nl_bottom, img_w, img_h
    )
    default_scan_top = nl_top
    if inset_result is not None:
        boundary_row, boundary_score = inset_result
        print(f"  Detected potential inset boundary at row {boundary_row} "
              f"(score {boundary_score:.0f}).")
        print("  Inset sub-charts (different scale) contaminate meridian/parallel detection.")
        print(f"  Suggested scan region: rows {boundary_row}–{nl_bottom}, "
              f"cols {nl_left}–{nl_right}")
        default_scan_top = boundary_row
    else:
        print("  No inset boundary detected — full chart interior will be scanned.")

    # Charts with insets have non-rectangular chart areas.  Let the user restrict
    # the SCAN REGION for meridian/parallel detection to the main chart body.
    print("\n─── 2. Scan region (for detection only) ─────────────────────────────")
    print("  If this chart has an inset or irregular shape, define a rectangular")
    print("  sub-region of the MAIN chart body to scan.  This keeps inset borders")
    print("  and their graticule from interfering with main-chart detection.")
    print("  (Press Enter to use the full neatline as the scan region.)")
    scan_top    = int(prompt("Scan top row",    default_scan_top))
    scan_left   = int(prompt("Scan left col",   nl_left))
    scan_right  = int(prompt("Scan right col",  nl_right))
    scan_bottom = int(prompt("Scan bottom row", nl_bottom))

    print("\n─── 3. Meridian detection ───────────────────────────────────────────")
    meridian_cols, spacing_px, rms = detect_meridians(
        band, scan_top, img_w, img_h,
        nl_left=scan_left, nl_right=scan_right,
        scan_bottom=scan_bottom,
    )
    # Allow user to filter down to the correct count.
    # On a chart with coarse tick marks (e.g. 5') the detector may find many
    # small-scale features; user supplies the expected count and we keep the
    # top-N scoring columns with auto-adapted min_spacing.
    if len(meridian_cols) > 0:
        print(f"  Meridian cols: {list(meridian_cols)}")
        keep_n_str = prompt(
            "Keep top-N meridians by score (Enter = keep all)", None
        )
        if keep_n_str and keep_n_str.strip().isdigit():
            keep_n = int(keep_n_str)
            # Adaptive min_spacing: spread the N cols evenly across chart width
            scan_w      = scan_right - scan_left
            adapt_space = max(50, int(scan_w / (keep_n + 1)))
            # Re-run greedy selection with the adaptive spacing
            meridian_cols, spacing_px, rms = detect_meridians(
                band, scan_top, img_w, img_h,
                nl_left=scan_left, nl_right=scan_right,
                scan_bottom=scan_bottom,
                min_spacing=adapt_space,
            )
            # Trim to exactly keep_n if still over
            if len(meridian_cols) > keep_n:
                meridian_cols = meridian_cols[:keep_n]
            print(f"  Kept {len(meridian_cols)} meridians: {list(meridian_cols)}")

    print("\n─── 4. Parallel detection ───────────────────────────────────────────")
    # Default open-water column: middle of scan region
    default_par_col = (scan_left + scan_right) // 2
    par_col = int(prompt("Open-water column for parallel scan", default_par_col))
    parallel_rows = detect_parallels(
        band, par_col, scan_top, img_w, img_h,
        nl_bottom=scan_bottom,
    )
    # Same override for parallels
    if len(parallel_rows) > 0:
        print(f"  Parallel rows: {list(parallel_rows)}")
        keep_p_str = prompt(
            "Keep top-N parallels by score (Enter = keep all)", None
        )
        if keep_p_str and keep_p_str.strip().isdigit():
            keep_p = int(keep_p_str)
            scan_h      = scan_bottom - scan_top
            adapt_space = max(50, int(scan_h / (keep_p + 1)))
            parallel_rows = detect_parallels(
                band, par_col, scan_top, img_w, img_h,
                nl_bottom=scan_bottom,
                min_spacing=adapt_space,
            )
            if len(parallel_rows) > keep_p:
                parallel_rows = parallel_rows[:keep_p]
            print(f"  Kept {len(parallel_rows)} parallels: {list(parallel_rows)}")

    if len(meridian_cols) == 0 or len(parallel_rows) == 0:
        print("ERROR: detection failed — 0 meridians or parallels")
        sys.exit(1)

    print("\n─── 5. Coordinate assignment ────────────────────────────────────────")
    if spacing_px is not None:
        print(f"  Pixel spacing: {spacing_px:.2f} px/tick")
        for t in [1, 2, 5, 10]:
            print(f"    if interval = {t}' → {spacing_px / t:.2f} px/arcmin")
    print()
    m_interval = float(prompt("Meridian tick interval (arcmin)", 1))
    px_per_arcmin = (spacing_px / m_interval) if spacing_px else None

    print(f"\n  {len(meridian_cols)} meridians, cols {list(meridian_cols)}")
    print(f"  Westernmost (smallest col = {meridian_cols[0]}) longitude:")
    first_lon = float(prompt("  First meridian lon, negative=W (e.g. -122.7000)"))

    print(f"\n  {len(parallel_rows)} parallels, rows {list(parallel_rows)}")
    print(f"  Northernmost (smallest row = {parallel_rows[0]}) latitude:")
    first_lat = float(prompt("  First parallel lat, positive=N (e.g. 37.9167)"))

    p_interval = float(prompt("Parallel tick interval (arcmin)", m_interval))

    meridian_lons = [round(first_lon + i * m_interval / 60.0, 6)
                     for i in range(len(meridian_cols))]
    parallel_lats = [round(first_lat - i * p_interval / 60.0, 6)
                     for i in range(len(parallel_rows))]

    print("\n─── 6. Measuring GCP intersections (±80 px centroid) ────────────────")
    gcps = measure_gcps(band, meridian_cols, parallel_rows,
                        meridian_lons, parallel_lats, img_w, img_h)
    print(f"\n  {len(gcps)} GCPs measured.")

    # Per-meridian col spread check: >20 px spread across parallels on the same
    # meridian typically indicates a bad GCP measurement (solid non-graticule line
    # dominated the centroid scan).
    lon_to_cols: dict = {}
    for g in gcps:
        lon_to_cols.setdefault(g['lon'], []).append(g['pixel_col'])
    for lon, cols in lon_to_cols.items():
        mean_col = sum(cols) / len(cols)
        for g in gcps:
            if g['lon'] != lon:
                continue
            deviation = abs(g['pixel_col'] - mean_col)
            if deviation > 20:
                print(f"\n  WARN: GCP ({lon}, {g['lat']}) col={g['pixel_col']:.1f} "
                      f"deviates {deviation:.1f} px from per-meridian mean {mean_col:.1f}")
                replace = input(
                    f"  Replace with mean col {mean_col:.1f}? [y/n]: "
                ).strip().lower()
                if replace == 'y':
                    g['pixel_col'] = round(mean_col, 1)
                    print("  → Replaced.")

    print("\n─── 7. Chart bounds ─────────────────────────────────────────────────")
    print("  Enter from border labels (approximate; GCPs drive accuracy).")
    west  = float(prompt("West  lon", round(min(g['lon'] for g in gcps) - 0.05, 4)))
    east  = float(prompt("East  lon", round(max(g['lon'] for g in gcps) + 0.05, 4)))
    south = float(prompt("South lat", round(min(g['lat'] for g in gcps) - 0.05, 4)))
    north = float(prompt("North lat", round(max(g['lat'] for g in gcps) + 0.05, 4)))

    title = prompt("Chart title", f"NOAA Chart {chart_num}")

    nl_width  = nl_right  - nl_left
    nl_height = nl_bottom - nl_top

    notes = (
        f"{len(gcps)} GCPs at {len(meridian_cols)} meridians × "
        f"{len(parallel_rows)} parallels. "
        "Intersections measured directly (±80 px centroid scan). "
        "Warp: TPS to EPSG:3857."
    )
    if scan_top != nl_top or scan_left != nl_left:
        notes += (f" Scan region restricted to rows {scan_top}–{scan_bottom},"
                  f" cols {scan_left}–{scan_right} (inset exclusion).")

    return {
        "chart":      chart_num,
        "title":      title,
        "source_tif": f"charts_rasterized/{chart_num}.tif",
        "tif_dimensions": {"width": img_w, "height": img_h},
        "gcps": gcps,
        "neatline": {
            "col":    nl_left,
            "row":    nl_top,
            "width":  nl_width,
            "height": nl_height,
        },
        "bounds": {"west": west, "east": east, "south": south, "north": north},
        "graticule": {
            "meridian_spacing_arcmin": m_interval,
            "parallel_spacing_arcmin": p_interval,
            "meridians_detected":      len(meridian_cols),
            "parallels_detected":      len(parallel_rows),
            "px_per_arcmin_lon":       round(px_per_arcmin, 2) if px_per_arcmin else None,
            "rms_residual_px":         round(rms, 2) if rms else None,
        },
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Validate mode — compare to existing georef/<n>.json
# ---------------------------------------------------------------------------

def validate_mode(chart_num, band, img_w, img_h, ref_path):
    with open(ref_path) as f:
        ref = json.load(f)

    dims  = ref.get('tif_dimensions') or ref.get('pdf_dimensions', {})
    ref_w = dims.get('width', '?')
    ref_h = dims.get('height', '?')
    print(f"\n  Reference:  {ref_w}×{ref_h} px")
    print(f"  This open:  {img_w}×{img_h} px")
    if img_w != ref_w or img_h != ref_h:
        print("  WARNING: dimensions differ — pixel coordinates not directly comparable")

    nl_top = ref['neatline']['row']

    print("\n─── Meridian detection ──────────────────────────────────────────────")
    meridian_cols, spacing_px, rms = detect_meridians(band, nl_top, img_w, img_h)
    print(f"  Reference had {ref['graticule']['meridians_detected']} meridians")

    print("\n─── Parallel detection ──────────────────────────────────────────────")
    parallel_rows = detect_parallels(band, img_w // 4, nl_top, img_w, img_h)
    print(f"  Reference had {ref['graticule']['parallels_detected']} parallels")

    # For each reference GCP, run centroid from the reference pixel estimate
    # and compare to the stored value.  This checks that the centroid measurement
    # is stable and that the PDF opens at the same resolution.
    print("\n─── Centroid check at each reference GCP ────────────────────────────")
    print(f"  {'lon':>10}  {'lat':>9}  {'ref_col':>8}  {'ref_row':>7}  "
          f"{'meas_col':>9}  {'meas_row':>8}  {'Δcol':>6}  {'Δrow':>6}  status")
    print("  " + "─" * 80)

    errors = []
    for g in ref['gcps']:
        rc, rr = g['pixel_col'], g['pixel_row']
        result = measure_centroid(band, int(rc), int(rr), img_w, img_h)
        if result is None:
            print(f"  {g['lon']:10.4f}  {g['lat']:9.4f}  {rc:8.1f}  {rr:7.0f}  "
                  f"{'NO DATA':>9}  {'NO DATA':>8}  {'—':>6}  {'—':>6}  FAIL")
        else:
            mc, mr = result
            dc, dr = mc - rc, mr - rr
            ok = max(abs(dc), abs(dr)) < 5
            errors.append((abs(dc), abs(dr)))
            print(f"  {g['lon']:10.4f}  {g['lat']:9.4f}  {rc:8.1f}  {rr:7.0f}  "
                  f"{mc:9.1f}  {mr:8.1f}  {dc:+6.1f}  {dr:+6.1f}  "
                  f"{'OK' if ok else 'WARN'}")

    if errors:
        rms_err = math.sqrt(sum(dc**2 + dr**2 for dc, dr in errors) / len(errors))
        print(f"\n  GCPs compared: {len(errors)}")
        print(f"  RMS error:     {rms_err:.2f} px")
        print(f"  Max |Δcol|:    {max(dc for dc, dr in errors):.2f} px")
        print(f"  Max |Δrow|:    {max(dr for dc, dr in errors):.2f} px")
        if rms_err < 5:
            print("  ✓ PASS")
        else:
            print("  ✗ WARN — some errors exceed 5 px (may reflect reference measurement")
            print("    artifacts where solid non-graticule lines dominate the centroid scan)")

    # ── Consistency check: per-meridian col spread across parallels ────────
    print("\n─── GCP self-consistency (col spread per meridian) ──────────────────")
    lon_groups: dict = {}
    for g in ref['gcps']:
        lon_groups.setdefault(g['lon'], []).append(g['pixel_col'])

    print(f"  {'lon':>10}  {'ref_col_range':>14}  {'meas cols (this run)':>22}")
    meas_groups: dict = {}
    all_gcps_this_run = []
    for g in ref['gcps']:
        rc, rr = g['pixel_col'], g['pixel_row']
        result = measure_centroid(band, int(rc), int(rr), img_w, img_h)
        if result is not None:
            mc = result[0]
            meas_groups.setdefault(g['lon'], []).append(mc)
            all_gcps_this_run.append((g['lon'], g['lat'], mc, result[1]))

    for lon in sorted(lon_groups.keys()):
        ref_cols  = lon_groups[lon]
        meas_cols = meas_groups.get(lon, [])
        ref_range = max(ref_cols) - min(ref_cols)
        meas_str  = (f"{min(meas_cols):.0f}–{max(meas_cols):.0f} "
                     f"(range {max(meas_cols)-min(meas_cols):.0f} px)"
                     if meas_cols else "—")
        flag = "WARN" if (meas_cols and max(meas_cols) - min(meas_cols) > 5) else ""
        print(f"  {lon:10.4f}  range {ref_range:4.0f} px         {meas_str}  {flag}")


# ---------------------------------------------------------------------------
# Preview mode
# ---------------------------------------------------------------------------

def preview_mode(chart_num, pdf_path):
    """Render at 50 DPI for overview and 200 DPI for reading tick labels. Exits after."""
    import subprocess
    out50  = f"/tmp/chart_{chart_num}_50dpi.png"
    out200 = f"/tmp/chart_{chart_num}_200dpi.png"
    env50  = {**os.environ, "GDAL_PDF_DPI": "50"}
    env200 = {**os.environ, "GDAL_PDF_DPI": "200"}
    print(f"  Rendering 50 DPI → {out50} ...")
    subprocess.run(["gdal_translate", "-of", "PNG", pdf_path, out50],
                   env=env50, check=True)
    print(f"  Rendering 200 DPI → {out200} ...")
    subprocess.run(["gdal_translate", "-of", "PNG", pdf_path, out200],
                   env=env200, check=True)
    print(f"\n  Scale note: col_400 / 2 = col_200 (200 DPI is half-scale of working raster)")
    print(f"  Longitude labels: just below top neatline (rows nl_top to nl_top+100 at 400 DPI)")
    print(f"  Latitude labels:  outside right neatline. Right margin shows full '38° 15'' form.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Detect GCPs in a NOAA chart TIF")
    ap.add_argument("chart_num")
    ap.add_argument("--validate", action="store_true",
                    help="Compare detection to existing georef/<n>.json")
    ap.add_argument("--preview", action="store_true",
                    help="Render chart at 50 DPI (overview) and 200 DPI (tick labels) then exit")
    args = ap.parse_args()

    chart_num = args.chart_num
    pdf_path  = os.path.join(REPO, "charts", f"{chart_num}.pdf")
    tif_path  = os.path.join(REPO, "charts_rasterized", f"{chart_num}.tif")
    out_path  = os.path.join(REPO, "georef", f"{chart_num}.json")

    if args.preview:
        if not os.path.exists(pdf_path):
            print(f"ERROR: {pdf_path} not found — download the NOAA chart PDF first")
            sys.exit(1)
        preview_mode(chart_num, pdf_path)
        sys.exit(0)

    if not os.path.exists(tif_path):
        print(f"ERROR: {tif_path} not found.")
        print(f"  Pre-rasterize first:")
        print(f"    python3 scripts/prerasterize.py {chart_num}")
        sys.exit(1)
    src_path = tif_path

    print(f"\n=== detect_gcps.py — Chart {chart_num} ===")
    print(f"  Opening {tif_path} ...")
    ds   = gdal.Open(src_path)
    img_w = ds.RasterXSize
    img_h = ds.RasterYSize
    print(f"  Dimensions: {img_w} × {img_h} px  ({ds.RasterCount} band(s))")
    band = ds.GetRasterBand(1)

    if args.validate:
        if not os.path.exists(out_path):
            print(f"ERROR: {out_path} not found (needed for --validate)")
            sys.exit(1)
        validate_mode(chart_num, band, img_w, img_h, out_path)
    else:
        data = interactive_mode(chart_num, band, img_w, img_h)
        confirm = input(f"\n  Write {out_path}? [y/n]: ").strip().lower()
        if confirm != 'y':
            print("  Aborted.")
            sys.exit(0)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"  Written: {out_path}")

    ds = None
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
