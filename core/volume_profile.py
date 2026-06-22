"""Composite volume profile approximated from daily OHLCV bars.

Yahoo Finance does not expose intraday tick/volume-at-price data, so a true
volume profile cannot be reconstructed. This module approximates one from daily
bars: each bar's volume is smeared across its high-low range with a triangular
weight peaking at the close (where price ultimately settled), and the smears are
aggregated into fixed-width price buckets. The result is a daily-bar estimate,
NOT a tick-derived profile — callers must surface that caveat in any output.

Pure functions only — no I/O. Callers supply an OHLCV DataFrame (the existing
prices_daily cache via services/price_service.py is the intended source).
"""

import numpy as np
import pandas as pd

from constants import HVN_MIN_PROMINENCE, VP_BUCKET_PCT, VP_VALUE_AREA_PCT


def _bar_weights(centers: np.ndarray, low: float, high: float, close: float) -> np.ndarray:
    """Triangular weights over `centers` for one bar, peaking at the close.

    Rises linearly from `low` to `close`, falls linearly from `close` to `high`.
    Degenerate cases (close at/beyond an edge, or a zero-range bar) collapse to a
    one-sided ramp or a single point. Weights are unnormalised; the caller scales
    them to the bar's volume.
    """
    if high <= low:
        # Zero-range bar (e.g. limit move/halt): all mass at the close level.
        w = np.zeros_like(centers)
        w[np.argmin(np.abs(centers - close))] = 1.0
        return w

    c = min(max(close, low), high)  # clamp close into [low, high] for safety
    w = np.zeros_like(centers)
    in_range = (centers >= low) & (centers <= high)

    left = in_range & (centers <= c)
    right = in_range & (centers > c)

    # Ascending limb low -> close; descending limb close -> high.
    if c > low:
        w[left] = (centers[left] - low) / (c - low)
    else:
        w[left] = 1.0  # close sits on the low: flat support at the bottom bucket
    if high > c:
        w[right] = (high - centers[right]) / (high - c)
    else:
        w[right] = 1.0  # close sits on the high

    return w


def compute_volume_profile(
    ohlcv: pd.DataFrame,
    bucket_pct: float = VP_BUCKET_PCT,
    value_area_pct: float = VP_VALUE_AREA_PCT,
) -> dict:
    """Build a composite volume profile from daily OHLCV bars.

    Args:
        ohlcv: DataFrame with 'high', 'low', 'close', 'volume' columns (one row
            per day). Already sliced to the desired lookback window by the caller.
        bucket_pct: histogram row width as a fraction of the window reference price.
        value_area_pct: fraction of total volume defining the value area.

    Returns a dict:
        poc:        price of the maximum-volume bucket (point of control)
        vah / val:  upper / lower bound of the value area
        hist:       DataFrame['price', 'volume'] — the full histogram (bucket centers)
        total_volume, bucket_width, n_bars
    Returns {} when there is insufficient data.
    """
    if ohlcv is None or ohlcv.empty:
        return {}

    df = ohlcv[["high", "low", "close", "volume"]].dropna()
    df = df[df["volume"] > 0]
    if df.empty:
        return {}

    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    vols = df["volume"].to_numpy(dtype=float)

    price_min = float(lows.min())
    price_max = float(highs.max())
    if price_max <= price_min:
        return {}

    # Bucket width is a fixed fraction of a representative price so rows are
    # uniform across the window. Volume-weighted average close is the natural
    # center of mass; fall back to the mean close if volume is degenerate.
    vwap_ref = float((closes * vols).sum() / vols.sum())
    ref_price = vwap_ref if vwap_ref > 0 else float(closes.mean())
    bucket_width = ref_price * bucket_pct
    if bucket_width <= 0:
        return {}

    n_buckets = int(np.ceil((price_max - price_min) / bucket_width)) + 1
    edges = price_min + np.arange(n_buckets + 1) * bucket_width
    centers = (edges[:-1] + edges[1:]) / 2.0

    hist = np.zeros(n_buckets, dtype=float)
    for low, high, close, vol in zip(lows, highs, closes, vols):
        w = _bar_weights(centers, low, high, close)
        s = w.sum()
        if s > 0:
            hist += (w / s) * vol

    total_volume = float(hist.sum())
    if total_volume <= 0:
        return {}

    poc_idx = int(np.argmax(hist))
    poc = float(centers[poc_idx])

    val_idx, vah_idx = _value_area_bounds(hist, poc_idx, total_volume, value_area_pct)

    return {
        "poc": poc,
        "vah": float(centers[vah_idx]),
        "val": float(centers[val_idx]),
        "hist": pd.DataFrame({"price": centers, "volume": hist}),
        "total_volume": total_volume,
        "bucket_width": float(bucket_width),
        "n_bars": int(len(df)),
    }


def _value_area_bounds(
    hist: np.ndarray, poc_idx: int, total_volume: float, value_area_pct: float
) -> tuple[int, int]:
    """Expand outward from the POC, greedily taking the heavier neighbour, until
    the accumulated volume reaches `value_area_pct` of the total. Returns the
    (low, high) bucket indices bounding the value area.
    """
    target = total_volume * value_area_pct
    lo = hi = poc_idx
    acc = hist[poc_idx]
    n = len(hist)

    while acc < target and (lo > 0 or hi < n - 1):
        below = hist[lo - 1] if lo > 0 else -1.0
        above = hist[hi + 1] if hi < n - 1 else -1.0
        if above >= below:
            hi += 1
            acc += hist[hi]
        else:
            lo -= 1
            acc += hist[lo]
    return lo, hi


def _plateau_peaks(vols: np.ndarray, floor: float) -> list[int]:
    """Indices of local-maximum buckets, robust to flat ties and edges. A run of
    adjacent equal-volume buckets sitting strictly above the buckets bordering it
    on both sides is one peak, represented by its centre bucket.

    Two failure modes this guards against: a single heavy close landing on a
    bucket boundary splits into two equal buckets (a strict `>` test would miss
    it), and the dominant shelf can sit on the very first/last bucket. The array
    is padded with -inf so the edges can peak. `floor` filters out the small
    sawtooth peaks the triangular smear leaves between real shelves.
    """
    n = len(vols)
    if n == 0:
        return []
    eps = vols.max() * 1e-9
    v = np.concatenate(([-np.inf], vols, [-np.inf]))  # pad so edge buckets can peak
    peaks: list[int] = []
    i = 1
    while i < len(v) - 1:
        if v[i] <= 0 or v[i] < floor or not (v[i] > v[i - 1] + eps):
            i += 1
            continue
        # Rising into i: walk across any equal-height plateau.
        j = i
        while j + 1 < len(v) and abs(v[j + 1] - v[i]) <= eps:
            j += 1
        # A peak only if the bucket just past the plateau drops below it
        # (the trailing -inf pad guarantees j+1 is valid).
        if v[j + 1] < v[i] - eps:
            peaks.append((i + j) // 2 - 1)  # unpad: shift back to vols index
        i = j + 1
    return peaks


def find_naked_pocs(ohlcv: pd.DataFrame, profile: dict, min_prominence: float = 0.25) -> list[dict]:
    """Identify high-volume shelves (local histogram peaks) that price has not
    traded back through since they formed — 'naked' levels that often act as
    magnets/targets.

    A peak must clear `min_prominence` of the tallest bucket to count (filtering
    the small discretisation peaks the daily-bar smear leaves behind). It is
    naked if price has since left the bucket and not retested it. Returns peaks
    sorted by volume (descending), each:
        {price, volume, side}  where side is 'above' or 'below' the last close.
    """
    if not profile or ohlcv is None or ohlcv.empty:
        return []

    hist_df = profile["hist"]
    prices = hist_df["price"].to_numpy(dtype=float)
    vols = hist_df["volume"].to_numpy(dtype=float)
    width = profile["bucket_width"]
    if len(prices) < 3:
        return []

    df = ohlcv[["high", "low", "close"]].dropna().reset_index(drop=True)
    last_close = float(df["close"].iloc[-1])

    peak_floor = vols.max() * min_prominence
    naked = []
    for i in _plateau_peaks(vols, peak_floor):
        lo_edge = prices[i] - width / 2.0
        hi_edge = prices[i] + width / 2.0

        # Naked = price has LEFT this shelf and not retested it. Find the most
        # recent bar that traded through the bucket; if that is the final bar,
        # price is sitting on the level right now, so it is not yet naked.
        traded = (df["low"] <= hi_edge) & (df["high"] >= lo_edge)
        if not traded.any():
            continue
        last_touch = traded[traded].index.max()
        if last_touch >= len(df) - 1:
            continue

        naked.append({
            "price": float(prices[i]),
            "volume": float(vols[i]),
            "side": "above" if prices[i] > last_close else "below",
        })

    naked.sort(key=lambda d: d["volume"], reverse=True)
    return naked


def find_high_volume_nodes(profile: dict, min_prominence: float = HVN_MIN_PROMINENCE) -> list[dict]:
    """High-volume nodes (local histogram peaks) in a profile — the price shelves
    where volume has stacked, used as support/resistance anchors.

    Unlike find_naked_pocs, this does NOT require the level to be untested: a node
    is a shelf whether or not price has since traded back through it. A peak must
    clear `min_prominence` of the tallest bucket to count (filtering the small
    discretisation peaks the daily-bar smear leaves behind). Returns nodes sorted
    by volume (descending), each: {price, volume}.
    """
    if not profile:
        return []

    hist_df = profile["hist"]
    prices = hist_df["price"].to_numpy(dtype=float)
    vols = hist_df["volume"].to_numpy(dtype=float)
    if len(prices) < 3:
        return []

    peak_floor = vols.max() * min_prominence
    nodes = [
        {"price": float(prices[i]), "volume": float(vols[i])}
        for i in _plateau_peaks(vols, peak_floor)
    ]
    nodes.sort(key=lambda d: d["volume"], reverse=True)
    return nodes
