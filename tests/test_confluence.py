import pytest

from core.confluence import evaluate_confluence


def test_empty_or_zero_atr_returns_empty():
    assert evaluate_confluence(100, 95, {}, 2.0)["strength"] == 0
    out = evaluate_confluence(100, 95, {"DMA50": 100}, 0.0)
    assert out == {"strength": 0, "levels": [], "zones": []}


def test_level_in_zone_of_price_counts():
    # DMA50 sits 0.1 ATR from price (within 0.25 threshold) -> one ENTRY hit.
    out = evaluate_confluence(price=100.0, stop_price=80.0,
                              levels={"DMA50": 100.2}, atr=2.0)
    assert out["strength"] == 1
    z = out["zones"][0]
    assert z["type"] == "ENTRY" and z["name"] == "DMA50"


def test_price_and_stop_counted_independently():
    # One level near price, another near the stop -> strength 2.
    out = evaluate_confluence(price=100.0, stop_price=90.0,
                              levels={"POC": 100.1, "VAL": 90.1}, atr=2.0)
    assert out["strength"] == 2
    types = sorted(z["type"] for z in out["zones"])
    assert types == ["ENTRY", "STOP"]


def test_none_levels_are_skipped():
    out = evaluate_confluence(100, 90, {"DMA10": None, "DMA50": 100.1}, 2.0)
    names = [lvl["name"] for lvl in out["levels"]]
    assert names == ["DMA50"]  # None entry dropped


def test_fortress_flag_within_tight_threshold():
    # 0.05 ATR away -> inside the 0.10 fortress band.
    out = evaluate_confluence(100.0, 80.0, {"AVWAP": 100.1}, 2.0)
    assert out["zones"][0]["is_fortress"] is True


def test_levels_preserve_input_order():
    levels = {"DMA200": 50, "EMA200": 51, "DMA50": 52}
    out = evaluate_confluence(100, 90, levels, 2.0)
    assert [lvl["name"] for lvl in out["levels"]] == ["DMA200", "EMA200", "DMA50"]


def test_custom_threshold_widens_zone():
    # 0.4 ATR away: outside default 0.25, inside a 0.5 threshold.
    near = evaluate_confluence(100.0, 80.0, {"DMA50": 100.8}, 2.0)
    wide = evaluate_confluence(100.0, 80.0, {"DMA50": 100.8}, 2.0, threshold=0.5)
    assert near["strength"] == 0
    assert wide["strength"] == 1


def test_percent_distance_reported():
    out = evaluate_confluence(100.0, 80.0, {"DMA50": 105.0}, 2.0)
    lvl = out["levels"][0]
    assert lvl["price_pct"] == pytest.approx(5.0)
    assert lvl["price_atr"] == pytest.approx(2.5)
