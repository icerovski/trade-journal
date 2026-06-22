import numpy as np
import pandas as pd
import pytest

from core.anchored_vwap import find_pivots, anchored_vwap, compute_anchored_vwaps


def _df(highs, lows, closes, vols=None, dates=False):
    n = len(closes)
    vols = vols if vols is not None else [1000] * n
    data = {"high": highs, "low": lows, "close": closes, "volume": vols}
    df = pd.DataFrame(data)
    if dates:
        df["date"] = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
    return df


def test_insufficient_data_no_pivots():
    df = _df([1, 2, 3], [1, 2, 3], [1, 2, 3])
    assert find_pivots(df, window=10) == ([], [])


def test_finds_v_shaped_swing_low():
    # Descend to a trough at index 10, then ascend — a clean swing low.
    lows = list(range(20, 9, -1)) + list(range(11, 21))  # min at idx 10 (value 10)
    highs = [x + 1 for x in lows]
    closes = lows
    pivot_lows, _ = find_pivots(_df(highs, lows, closes), window=5)
    assert 10 in pivot_lows


def test_finds_inverted_v_swing_high():
    highs = list(range(10, 21)) + list(range(19, 9, -1))  # max at idx 10 (value 20)
    lows = [x - 1 for x in highs]
    closes = highs
    _, pivot_highs = find_pivots(_df(highs, lows, closes), window=5)
    assert 10 in pivot_highs


def test_avwap_of_flat_price_equals_price():
    df = _df([100] * 30, [100] * 30, [100] * 30)
    assert anchored_vwap(df, 0) == pytest.approx(100.0)


def test_avwap_is_volume_weighted():
    # Two bars: cheap bar with tiny volume, expensive bar with huge volume.
    df = _df([10, 100], [10, 100], [10, 100], vols=[1, 999])
    # Typical price = price here; AVWAP pulled toward the heavy 100 bar.
    expected = (10 * 1 + 100 * 999) / 1000
    assert anchored_vwap(df, 0) == pytest.approx(expected)


def test_avwap_respects_anchor_start():
    df = _df([10, 20, 30], [10, 20, 30], [10, 20, 30], vols=[1000, 1000, 1000])
    # Anchoring at the last bar should return just that bar's typical price.
    assert anchored_vwap(df, 2) == pytest.approx(30.0)


def test_compute_returns_most_recent_anchors_with_dates():
    lows = list(range(20, 9, -1)) + list(range(11, 21))
    highs = [x + 1 for x in lows]
    closes = lows
    out = compute_anchored_vwaps(_df(highs, lows, closes, dates=True), window=5)
    assert out["low_anchor"] is not None
    assert isinstance(out["low_anchor"]["date"], str)
    assert out["low_anchor"]["price"] == pytest.approx(10.0)


def test_compute_empty_frame():
    out = compute_anchored_vwaps(pd.DataFrame())
    assert out == {"low_anchor": None, "high_anchor": None}
