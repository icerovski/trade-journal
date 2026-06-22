"""Anchored VWAP from auto-detected swing pivots.

Anchored VWAP is the volume-weighted average price from a chosen anchor bar to
the present — "what the average participant has paid since <event>". Anchoring to
the most recent significant swing low gives a dynamic support line for longs;
anchoring to the most recent swing high gives a resistance reference.

Pure functions, no I/O. Daily typical price (H+L+C)/3 weighted by daily volume,
consistent with the daily-bar basis of core/volume_profile.py.
"""

import numpy as np
import pandas as pd

from constants import PIVOT_WINDOW


def find_pivots(df: pd.DataFrame, window: int = PIVOT_WINDOW) -> tuple[list[int], list[int]]:
    """Locate swing pivots via a symmetric fractal test.

    A bar is a swing low if its low is strictly below every low within `window`
    bars on both sides; a swing high is the symmetric condition on highs. Bars
    within `window` of either end cannot be confirmed and are skipped.

    Returns (pivot_low_positions, pivot_high_positions) as integer row offsets,
    each in ascending order.
    """
    n = len(df)
    if n < 2 * window + 1:
        return [], []

    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    pivot_lows, pivot_highs = [], []

    for i in range(window, n - window):
        lo = lows[i]
        if lo < lows[i - window:i].min() and lo < lows[i + 1:i + window + 1].min():
            pivot_lows.append(i)
        hi = highs[i]
        if hi > highs[i - window:i].max() and hi > highs[i + 1:i + window + 1].max():
            pivot_highs.append(i)

    return pivot_lows, pivot_highs


def anchored_vwap(df: pd.DataFrame, anchor_idx: int) -> float:
    """Volume-weighted average of daily typical price from `anchor_idx` to the
    last bar. Returns the current (most recent) AVWAP value.
    """
    seg = df.iloc[anchor_idx:]
    typical = (seg["high"] + seg["low"] + seg["close"]) / 3.0
    vol = seg["volume"].astype(float)
    total_vol = vol.sum()
    if total_vol <= 0:
        return float(seg["close"].iloc[-1])
    return float((typical * vol).sum() / total_vol)


def compute_anchored_vwaps(df: pd.DataFrame, window: int = PIVOT_WINDOW) -> dict:
    """Compute anchored VWAPs from the most recent swing low and swing high.

    Returns {'low_anchor': {...} | None, 'high_anchor': {...} | None}, where each
    entry is {date, price, vwap} — the anchor bar's date and pivot price, and the
    current AVWAP from that anchor. `date` falls back to the integer offset when
    the frame has no 'date' column.
    """
    result = {"low_anchor": None, "high_anchor": None}
    if df is None or df.empty:
        return result

    pivot_lows, pivot_highs = find_pivots(df, window)
    has_date = "date" in df.columns

    def _anchor(idx: int, price_col: str) -> dict:
        return {
            "date": str(df["date"].iloc[idx]) if has_date else idx,
            "price": float(df[price_col].iloc[idx]),
            "vwap": anchored_vwap(df, idx),
        }

    if pivot_lows:
        result["low_anchor"] = _anchor(pivot_lows[-1], "low")
    if pivot_highs:
        result["high_anchor"] = _anchor(pivot_highs[-1], "high")
    return result
