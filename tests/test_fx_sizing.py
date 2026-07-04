"""FX-normalized sizing (assessment Must-fix #1).

The sizer's caps (max_r_pct / max_exp_pct) are fractions of a NAV held in the
base currency, but entry/stop are in the asset currency. `fx_rate` (asset ccy ->
NAV ccy, same convention as audit_position_risk) converts the per-share risk and
exposure into base currency before they meet the caps. Default 1.0 reproduces
the prior behaviour byte-for-byte — the characterization snapshot must not move.
"""

import numpy as np
import pandas as pd
import pytest

from core.sizing import compute_position_size, compute_position_size_gap
from core.zone_scan import build_zone_report, scan_ticker

PRESETS = {
    "S": {"label": "Small", "max_r_pct": 0.30, "max_exp_pct": 1.5},
    "B": {"label": "Base", "max_r_pct": 0.60, "max_exp_pct": 3.0},
    "L": {"label": "Large", "max_r_pct": 1.00, "max_exp_pct": 5.0},
}


def _sine_ohlcv(n=300, center=100.0, amp=2.0, period=15.0):
    """Oscillating bars whose levels cluster around `center` (same shape as the
    zone-scan tests) so scan_ticker reliably flags a zone at the center price."""
    t = np.arange(n)
    close = center + amp * np.sin(t / period)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.full(n, 1000.0),
    })


# --- Default keeps prior behaviour --------------------------------------------
def test_fx_default_is_identity():
    args = (1_000_000, 100.0, 90.0, 1.0, 1.0, 5.0)
    assert compute_position_size(*args, fx_rate=1.0) == compute_position_size(*args)
    assert compute_position_size_gap(1_000_000, 100.0, 90.0, None, 1.0, 1.0, 5.0, fx_rate=1.0) \
        == compute_position_size_gap(1_000_000, 100.0, 90.0, None, 1.0, 1.0, 5.0)


# --- Risk-capped branch scales by 1/fx ----------------------------------------
def test_fx_scales_risk_capped_size():
    # EUR NAV, USD asset at fx 0.8 (1 USD = 0.80 EUR): a $10 stop distance risks
    # only EUR 8, so the same budget buys 1/0.8 = 1.25x the shares.
    blind = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 1.0, 100.0)
    fx = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 1.0, 100.0, fx_rate=0.8)
    assert blind == 1000
    assert fx == 1250


def test_fx_review_example_eurusd():
    # The audited failure mode: EUR/USD 1.08 -> fx (USD->EUR) = 1/1.08. The
    # fx-blind path treats $1 of risk as EUR 1 and under-sizes by ~8%.
    # Literal expectation (not a parallel float pipeline): int() truncation of a
    # near-integer product is knife-edge, so don't re-derive it in the assertion.
    fx = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 1.0, 100.0, fx_rate=1 / 1.08)
    assert fx == 1080  # blind path gives 1000; fx-correct buys 8% more


def test_degenerate_fx_degrades_to_par():
    # Bad snapshot data (0 / None / NaN / negative fx) must not crash the sizer —
    # it degrades to 1.0 (the pre-FX behaviour) instead of dividing by zero or
    # overflowing on int(min(inf, nan)).
    base = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 1.0, 5.0)
    for bad in (0.0, None, float("nan"), -0.5):
        assert compute_position_size(1_000_000, 100.0, 90.0, 1.0, 1.0, 5.0, fx_rate=bad) == base


# --- Exposure-capped branch scales too ----------------------------------------
def test_fx_scales_exposure_capped_size():
    # Risk cap non-binding (999%): exposure budget EUR 20k over $100/share at fx
    # 0.8 = EUR 80/share -> 250 shares, not 200.
    blind = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 999.0, 2.0)
    fx = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 999.0, 2.0, fx_rate=0.8)
    assert blind == 200
    assert fx == 250


# --- Exposure reference price override ----------------------------------------
def test_exposure_price_pins_exposure_leg_only():
    # Risk leg on entry-stop (non-binding here); exposure leg on the supplied
    # reference instead of entry: EUR 20k / $200 = 100 shares.
    q = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 999.0, 2.0, exposure_price=200.0)
    assert q == 100
    # Default (None) falls back to entry_price.
    assert compute_position_size(1_000_000, 100.0, 90.0, 1.0, 999.0, 2.0, exposure_price=None) \
        == compute_position_size(1_000_000, 100.0, 90.0, 1.0, 999.0, 2.0)


# --- Gap path threads fx through ----------------------------------------------
def test_gap_sizing_threads_fx():
    gapped = compute_position_size_gap(1_000_000, 100.0, 90.0, 80.0, 1.0, 1.0, 100.0, fx_rate=0.8)
    assert gapped == compute_position_size(1_000_000, 100.0, 80.0, 1.0, 1.0, 100.0, fx_rate=0.8)


# --- Zone scanner threads fx into preset sizes --------------------------------
def test_scan_ticker_fx_sizes_match_sizer():
    df = _sine_ohlcv()
    r = scan_ticker(df, nav=1_000_000, presets=PRESETS, ticker="T",
                    current_price=100.0, fx_rate=0.8)
    assert r is not None and r["flagged"] is True
    for key, p in PRESETS.items():
        assert r["sizes"][key]["qty"] == compute_position_size(
            1_000_000, 100.0, r["stop"], 1.0, p["max_r_pct"], p["max_exp_pct"], fx_rate=0.8
        )


def test_build_zone_report_threads_item_fx():
    df = _sine_ohlcv()
    universe = [{"ticker": "T", "price": 100.0, "fx_rate": 0.8, "_df": df}]
    out = build_zone_report(universe, lambda item: item["_df"], 1_000_000, PRESETS)
    assert out and out[0]["flagged"]
    expected = scan_ticker(df, 1_000_000, PRESETS, ticker="T",
                           current_price=100.0, fx_rate=0.8)
    assert out[0]["sizes"] == expected["sizes"]


# --- Prospect fx resolution (core.portfolio_manager.resolve_prospect_fx) ------
def _held(ccy, fx):
    from types import SimpleNamespace
    return SimpleNamespace(ccy=ccy, fx_rate=fx)


def test_resolve_prospect_fx_borrows_held_book(monkeypatch):
    # A held position in the same currency donates its broker-snapshot rate —
    # no network call may happen on this path.
    import services.market_data_service as mds
    from core.portfolio_manager import resolve_prospect_fx
    monkeypatch.setattr(mds, "fetch_fx_rate",
                        lambda a, b: (_ for _ in ()).throw(AssertionError("network hit")))
    held = [_held("EUR", 1.0), _held("USD", 0.92)]
    assert resolve_prospect_fx("USD", held, "EUR") == 0.92


def test_resolve_prospect_fx_same_ccy_is_par(monkeypatch):
    import services.market_data_service as mds
    from core.portfolio_manager import resolve_prospect_fx
    monkeypatch.setattr(mds, "fetch_fx_rate",
                        lambda a, b: (_ for _ in ()).throw(AssertionError("network hit")))
    assert resolve_prospect_fx("EUR", [], "EUR") == 1.0


def test_resolve_prospect_fx_live_fallback(monkeypatch):
    # No donor in the book: the FX service closes the gap instead of silently 1.0.
    import services.market_data_service as mds
    from core.portfolio_manager import resolve_prospect_fx
    monkeypatch.setattr(mds, "fetch_fx_rate",
                        lambda a, b: 0.9 if (a, b) == ("USD", "EUR") else None)
    assert resolve_prospect_fx("USD", [], "EUR") == 0.9


def test_resolve_prospect_fx_garbage_nav_ccy_stays_blind(monkeypatch):
    # A failed NAV fetch hands callers "???" — never turned into a Yahoo symbol.
    import services.market_data_service as mds
    from core.portfolio_manager import resolve_prospect_fx
    monkeypatch.setattr(mds, "fetch_fx_rate",
                        lambda a, b: (_ for _ in ()).throw(AssertionError("network hit")))
    assert resolve_prospect_fx("USD", [], "???") == 1.0
    assert resolve_prospect_fx("USD", [], None) == 1.0


def test_resolve_prospect_fx_ignores_degenerate_donor(monkeypatch):
    # A NaN/zero/negative snapshot rate must never be donated to prospects —
    # NaN is truthy and != 1.0, so a naive filter would pass it straight through.
    import services.market_data_service as mds
    from core.portfolio_manager import resolve_prospect_fx
    monkeypatch.setattr(mds, "fetch_fx_rate", lambda a, b: 0.9)
    held = [_held("USD", float("nan")), _held("USD", 0.0), _held("USD", -0.5)]
    assert resolve_prospect_fx("USD", held, "EUR") == 0.9  # falls through to the FX service


def test_resolve_prospect_fx_pence_scaled(monkeypatch):
    # Yahoo prices LSE names in PENCE ('GBp'): the ccy->NAV rate is 0.01 x the
    # pounds rate — upper-casing GBp to GBP would mis-size by 100x.
    import services.market_data_service as mds
    from core.portfolio_manager import resolve_prospect_fx
    monkeypatch.setattr(mds, "fetch_fx_rate",
                        lambda a, b: 1.17 if (a, b) == ("GBP", "EUR") else None)
    # Held GBP donor (broker rate in pounds): pence prospect scales it by 0.01.
    held = [_held("GBP", 1.17)]
    assert resolve_prospect_fx("GBp", held, "EUR") == pytest.approx(0.0117)
    # No donor: live pounds rate, still scaled.
    assert resolve_prospect_fx("GBp", [], "EUR") == pytest.approx(0.0117)
    # Blind (no nav ccy): at least honour the minor-unit scale.
    assert resolve_prospect_fx("GBp", [], None) == pytest.approx(0.01)
