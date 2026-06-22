import numpy as np
import pandas as pd
import pytest

from core.zone_scan import (
    _wilder_atr,
    _slice_months,
    _nearest_support,
    _micro_support,
    _breakout_gap_floor,
    scan_ticker,
    build_zone_report,
)

PRESETS = {
    "S": {"label": "Small", "max_r_pct": 0.30, "max_exp_pct": 1.5},
    "B": {"label": "Base", "max_r_pct": 0.60, "max_exp_pct": 3.0},
    "L": {"label": "Large", "max_r_pct": 1.00, "max_exp_pct": 5.0},
}


def _sine_ohlcv(n=300, center=100.0, amp=2.0, period=15.0):
    """Smoothly oscillating bars: clean swings (pivots) with levels (DMAs, POC,
    AVWAP) all clustering around `center`."""
    t = np.arange(n)
    close = center + amp * np.sin(t / period)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.full(n, 1000.0),
    })


def test_wilder_atr_constant_range():
    df = pd.DataFrame({"high": [101] * 30, "low": [99] * 30, "close": [100] * 30})
    # Constant 2-wide bars with no gaps -> ATR converges to 2.
    assert _wilder_atr(df, 14) == pytest.approx(2.0, abs=1e-6)


def test_slice_months_uses_dates():
    df = _sine_ohlcv(n=300)
    six = _slice_months(df, 6)
    assert len(six) < len(df)
    # ~6 months of daily bars (calendar days, weekends included here).
    assert 170 <= len(six) <= 190


def test_nearest_support_picks_tightest_below_price():
    levels = {"VAL_6mo": 90.0, "VAL_12mo": 95.0, "AVWAP_low": 80.0, "VAH_6mo": 110.0}
    stop, src = _nearest_support(levels, price=100.0)
    assert stop == 95.0 and src == "VAL_12mo"  # nearest below price


def test_nearest_support_none_when_all_above():
    stop, src = _nearest_support({"VAL_6mo": 110.0, "AVWAP_low": 120.0}, price=100.0)
    assert stop is None and src is None


def test_thin_data_returns_none():
    df = _sine_ohlcv(n=5)
    assert scan_ticker(df, 1_000_000, PRESETS) is None


def test_flagged_zone_populates_stop_and_sizes():
    df = _sine_ohlcv(n=300, center=100.0)
    # Inject price at the cluster center where DMAs/POCs converge.
    r = scan_ticker(df, nav=1_000_000, presets=PRESETS, ticker="TEST", current_price=100.0)
    assert r is not None and r["flagged"] is True
    assert len(r["entry_signals"]) >= 2
    assert r["stop"] < 100.0
    assert set(r["sizes"]) == {"S", "B", "L"}
    assert all(s["qty"] > 0 for s in r["sizes"].values())


def test_micro_support_from_recent_window_below_price():
    # 6 stale bars at 90, then a 14-bar base climbing 96->100. Price above at 101
    # -> micro VAL/AVWAP sit below price and the stop is tight, not 20% away.
    close = np.concatenate([np.full(6, 90.0), np.linspace(96.0, 100.0, 14)])
    n = len(close)
    df = pd.DataFrame({
        "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": np.full(n, 1000.0),
    })
    stop, src = _micro_support(df, price=101.0, atr=1.0, micro_days=14, buffer_atr=0.25)
    assert src.endswith("14d")
    assert stop < 101.0 and stop > 95.0  # tight micro stop, not far below


def _gap_window(base_high=90.5, gap_low=95.0, n_base=12, base_vol=10000.0, post_vol=100.0):
    """A flat heavy base then an up-gap into a light two-bar shelf. VAL/HVN/AVWAP
    all pin to the heavy base (~90); the gap floor (base high) is the sole support
    above it. Returns a micro-window DataFrame."""
    rows = [(base_high, base_high - 1.0, base_high - 0.5, base_vol) for _ in range(n_base)]
    rows += [(gap_low + 1.0, gap_low, gap_low + 0.5, post_vol)]       # the gap-up bar
    rows += [(gap_low + 1.5, gap_low + 0.5, gap_low + 1.0, post_vol)]  # follow-through
    return pd.DataFrame(rows, columns=["high", "low", "close", "volume"])


def test_breakout_gap_floor_returns_pregap_high():
    df = _gap_window(base_high=90.5, gap_low=95.0)
    floor = _breakout_gap_floor(df, price=97.0, atr=1.0, gap_min_atr=0.5)
    assert floor == pytest.approx(90.5)  # the pre-gap high, not the gap top


def test_breakout_gap_floor_ignores_subthreshold_gap():
    # A 0.3-wide gap with atr=1 and gap_min_atr=0.5 -> below threshold -> None.
    df = _gap_window(base_high=90.5, gap_low=90.8)
    assert _breakout_gap_floor(df, price=97.0, atr=1.0, gap_min_atr=0.5) is None


def test_breakout_gap_floor_none_when_floor_above_price():
    df = _gap_window(base_high=90.5, gap_low=95.0)
    # Price sitting inside the base, below the gap floor -> floor is not support.
    assert _breakout_gap_floor(df, price=90.0, atr=1.0, gap_min_atr=0.5) is None


def test_micro_support_selects_gap_floor_when_tightest():
    df = _gap_window(base_high=90.5, gap_low=95.0)
    stop, src = _micro_support(df, price=97.0, atr=1.0, micro_days=14, buffer_atr=0.25)
    assert src == "GAP_14d"
    assert stop == pytest.approx(90.5 - 0.25)  # floor minus the ATR buffer


def test_micro_support_selects_hvn_when_tightest():
    # A moderate-volume ramp 90->95 then a heavy shelf at ~96 (the HVN), price 100.
    # The volume spread below the peak pushes VAL down to ~93, so the 96 node is a
    # strictly tighter support than the VAL edge -> HVN wins. No gaps.
    ramp = np.linspace(90.0, 95.0, 9)
    rows = [(c + 0.5, c - 0.5, c, 2000) for c in ramp]
    rows += [(96.5, 95.5, 96.0, 3000) for _ in range(5)]
    df = pd.DataFrame(rows, columns=["high", "low", "close", "volume"])
    stop, src = _micro_support(df, price=100.0, atr=1.0, micro_days=14, buffer_atr=0.25)
    assert src == "HVN_14d"
    assert 95.0 < stop < 96.5  # node ~96 minus the buffer


def test_momentum_regime_tags_and_uses_micro_stop():
    # Parabolic ramp to 195, then a shallow pullback to ~178 (a momentum flag).
    # Price sits at 190 — far above the 6mo VAL (MOMENTUM) and above the recent
    # 14-bar micro structure, so the stop comes from the micro window, not VAL_6mo.
    ramp = np.linspace(50.0, 195.0, 270)
    pullback = np.linspace(195.0, 178.0, 30)
    close = np.concatenate([ramp, pullback])
    n = len(close)
    df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": np.full(n, 1000.0),
    })
    r = scan_ticker(df, 1_000_000, PRESETS, ticker="MOMO",
                    current_price=190.0, min_confluence=1)
    assert r["regime"] == "MOMENTUM"
    assert r["flagged"] is True
    assert r["tag"] == "ZONE-MOMO"
    assert r["stop_source"].endswith("14d")          # micro stop, not VAL_6mo
    assert r["stop"] < 190.0
    # The micro stop is far tighter than the distant 6mo VAL would have been.
    assert (190.0 - r["stop"]) / 190.0 < 0.10
    assert r["stop"] > r["levels"]["VAL_6mo"]         # tighter than the 6mo support


def test_normal_regime_keeps_plain_zone_tag():
    df = _sine_ohlcv(n=300, center=100.0)
    r = scan_ticker(df, 1_000_000, PRESETS, current_price=100.0)
    assert r["regime"] == "NORMAL"
    assert r["tag"] == "ZONE"


def test_no_confluence_when_price_far_from_levels():
    df = _sine_ohlcv(n=300, center=100.0)
    r = scan_ticker(df, 1_000_000, PRESETS, ticker="FAR", current_price=130.0)
    assert r is not None and r["flagged"] is False
    assert "sizes" not in r


def test_size_monotonic_across_presets():
    df = _sine_ohlcv(n=300, center=100.0)
    r = scan_ticker(df, 1_000_000, PRESETS, current_price=100.0)
    s, b, l = (r["sizes"][k]["qty"] for k in ("S", "B", "L"))
    assert s <= b <= l  # larger preset -> at least as many shares


def test_build_report_sorts_flagged_first():
    flagged = _sine_ohlcv(n=300, center=100.0)
    not_flagged = _sine_ohlcv(n=300, center=100.0)

    def loader(item):
        return item["_df"]

    universe = [
        {"ticker": "FAR", "price": 130.0, "_df": not_flagged},
        {"ticker": "HIT", "price": 100.0, "_df": flagged},
    ]
    out = build_zone_report(universe, loader, 1_000_000, PRESETS)
    assert [r["ticker"] for r in out][0] == "HIT"  # flagged sorts first
    assert out[0]["flagged"] and not out[1]["flagged"]
