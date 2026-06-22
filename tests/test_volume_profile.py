import numpy as np
import pandas as pd
import pytest

from core.volume_profile import compute_volume_profile, find_naked_pocs


def _bars(rows):
    """rows: list of (high, low, close, volume)."""
    return pd.DataFrame(rows, columns=["high", "low", "close", "volume"])


def test_empty_returns_empty():
    assert compute_volume_profile(pd.DataFrame()) == {}
    assert compute_volume_profile(_bars([])) == {}


def test_zero_volume_returns_empty():
    df = _bars([(101, 99, 100, 0), (102, 100, 101, 0)])
    assert compute_volume_profile(df) == {}


def test_poc_at_dominant_price_level():
    # 50 quiet bars around 100, then heavy volume concentrated at ~120.
    rows = [(100.5, 99.5, 100.0, 100) for _ in range(50)]
    rows += [(120.2, 119.8, 120.0, 5000) for _ in range(10)]
    prof = compute_volume_profile(_bars(rows))
    assert prof  # non-empty
    assert prof["poc"] == pytest.approx(120.0, abs=prof["bucket_width"])


def test_value_area_brackets_poc_and_holds_target_volume():
    rng = np.random.default_rng(0)
    closes = rng.normal(100, 2, 400)
    rows = [(c + 0.5, c - 0.5, c, 1000) for c in closes]
    prof = compute_volume_profile(_bars(rows), value_area_pct=0.70)
    assert prof["val"] <= prof["poc"] <= prof["vah"]

    # Volume inside [VAL, VAH] should be ~70% of the total (>= by construction,
    # since the loop stops as soon as it crosses the target).
    hist = prof["hist"]
    inside = hist[(hist["price"] >= prof["val"]) & (hist["price"] <= prof["vah"])]
    frac = inside["volume"].sum() / prof["total_volume"]
    assert 0.70 <= frac <= 0.85


def test_close_weighting_skews_mass_toward_close():
    # Identical wide range every bar, but close pinned near the high. The POC
    # should land near the close, not the geometric midpoint of the range.
    rows = [(110.0, 90.0, 109.0, 1000) for _ in range(30)]
    prof = compute_volume_profile(_bars(rows))
    assert prof["poc"] > 105.0  # skewed up toward the 109 close, not ~100 midpoint


def test_zero_range_bar_does_not_crash():
    rows = [(100.0, 100.0, 100.0, 500)] + [(101, 99, 100, 100) for _ in range(10)]
    prof = compute_volume_profile(_bars(rows))
    assert prof["poc"] == pytest.approx(100.0, abs=prof["bucket_width"] * 2)


def test_naked_poc_flags_abandoned_shelf():
    # Heavy accumulation at ~100 early, then a clean trend up to ~130 that never
    # retests 100. The 100 shelf should surface as a naked level below price.
    rows = [(100.5, 99.5, 100.0, 5000) for _ in range(20)]
    rows += [(100.0 + i, 99.0 + i, 99.5 + i, 200) for i in range(1, 31)]
    df = _bars(rows)
    prof = compute_volume_profile(df)
    naked = find_naked_pocs(df, prof)
    assert any(n["side"] == "below" and 99 <= n["price"] <= 101 for n in naked)
