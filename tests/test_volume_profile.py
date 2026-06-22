import numpy as np
import pandas as pd
import pytest

from core.volume_profile import (
    compute_volume_profile,
    find_high_volume_nodes,
    find_naked_pocs,
)


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


def test_high_volume_nodes_empty_profile():
    assert find_high_volume_nodes({}) == []


def test_high_volume_nodes_finds_both_shelves_sorted_by_volume():
    # Bimodal: a heavy shelf at ~110 and a lighter one at ~90, with quiet bars in
    # between. Both surface as nodes; the heavier one ranks first. (Unlike naked
    # POCs, retesting does not disqualify a node.) A lower prominence floor is used
    # so the secondary shelf clears the bar even when it splits across two buckets.
    rows = [(110.5, 109.5, 110.0, 6000) for _ in range(20)]
    rows += [(100.5, 99.5, 100.0, 50) for _ in range(10)]
    rows += [(90.5, 89.5, 90.0, 5000) for _ in range(20)]
    prof = compute_volume_profile(_bars(rows))
    nodes = find_high_volume_nodes(prof, min_prominence=0.3)
    prices = [n["price"] for n in nodes]
    assert any(abs(p - 110.0) <= prof["bucket_width"] for p in prices)
    assert any(abs(p - 90.0) <= prof["bucket_width"] for p in prices)
    # Sorted by volume desc -> the 110 shelf (heaviest) leads.
    assert abs(nodes[0]["price"] - 110.0) <= prof["bucket_width"]


def test_high_volume_nodes_prominence_filters_minor_peaks():
    # One dominant shelf plus a tiny bump well under the prominence floor. With a
    # high prominence threshold only the dominant shelf qualifies.
    rows = [(100.5, 99.5, 100.0, 5000) for _ in range(30)]
    rows += [(120.5, 119.5, 120.0, 100) for _ in range(2)]
    prof = compute_volume_profile(_bars(rows))
    nodes = find_high_volume_nodes(prof, min_prominence=0.5)
    assert len(nodes) == 1
    assert abs(nodes[0]["price"] - 100.0) <= prof["bucket_width"]
