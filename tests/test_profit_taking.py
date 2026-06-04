"""Tests for the profit-taking / exit-strategy layer.

Covers the four pieces with no prior coverage:
  - Regime classification + reversal hysteresis (classify_regime)
  - Exit milestone ladder anchoring and stage classification (compute_exit_milestones)
  - Entry-anchored TP in calculate_position_risk (regression for the M2/TP collision)
  - TRIM_MATRIX guidance (M2-in-TREND hold)
  - Capital-efficiency "dead money" flag, incl. income-asset exclusion
"""
import pytest
import pandas as pd

from models import Position, RiskProfile
from core.profit_taking import classify_regime, compute_exit_milestones, TRIM_MATRIX
from core.stop_loss import calculate_position_risk
from constants import (
    TP_ATR_MULTIPLE, REGIME_REVERSAL_CONFIRM_DAYS,
    CAPITAL_HURDLE_PCT, STALE_MIN_AGE_DAYS,
)


def _pos(**kw):
    """Minimal Position with sane defaults; override via kwargs."""
    defaults = dict(
        name="Test", ticker="TST", conid="1", asset_class="STK", ccy="USD",
        date_entry=None, qty=10.0, entry_price=100.0,
    )
    defaults.update(kw)
    return Position(**defaults)


def _aged(days):
    return pd.Timestamp.now() - pd.Timedelta(days=days)


# --- Regime classification + hysteresis (Q4) -------------------------------

@pytest.mark.parametrize("direction,days,above,expected", [
    ("UP",   40, True,  "TREND"),
    ("UP",   40, False, "NORMAL"),    # pullback: rising DMA but price below it
    ("UP",   21, True,  "TREND"),     # exact TREND boundary
    ("UP",   20, True,  "NORMAL"),    # just under TREND
    ("UP",   10, True,  "NORMAL"),    # NORMAL lower boundary
    ("UP",    9, True,  "RANGING"),   # fresh, weak up-move
    ("DOWN",  1, True,  "NORMAL"),    # single reversal day -> hysteresis hold
    ("DOWN",  2, True,  "NORMAL"),    # still unconfirmed
    ("DOWN",  3, True,  "RANGING"),   # confirmed reversal
    ("DOWN", 30, True,  "RANGING"),
])
def test_classify_regime(direction, days, above, expected):
    assert classify_regime(direction, days, above) == expected


def test_regime_hysteresis_band_edges():
    """An unconfirmed reversal one day short of the band holds at NORMAL; at the
    band it demotes to RANGING. Guards the single-reversal-day whipsaw."""
    assert classify_regime("DOWN", REGIME_REVERSAL_CONFIRM_DAYS - 1, True) == "NORMAL"
    assert classify_regime("DOWN", REGIME_REVERSAL_CONFIRM_DAYS, True) == "RANGING"


# --- Exit milestone ladder + stage (#1 anchoring) --------------------------

def test_exit_milestone_ladder_is_uniform():
    """M1/M2/TP are entry + 1/2/3 x ATR, with no M2/TP collision."""
    p = _pos(entry_price=100.0, current_price=112.0)
    p.tp_price = 100.0 + TP_ATR_MULTIPLE * 5.0  # entry-anchored = 115
    compute_exit_milestones(p, atr_dist=5.0)
    assert (p.m1_price, p.m2_price, p.tp_price) == (105.0, 110.0, 115.0)
    assert p.m2_price != p.tp_price


@pytest.mark.parametrize("price,stage", [
    (104.0, "PRE-M1"),
    (105.0, "M1"),   # exactly at M1
    (111.0, "M2"),
    (115.0, "TP"),   # exactly at TP
    (120.0, "TP"),
])
def test_exit_stage_classification(price, stage):
    p = _pos(entry_price=100.0, current_price=price)
    p.tp_price = 115.0
    compute_exit_milestones(p, atr_dist=5.0)
    assert p.exit_stage == stage


def test_exit_milestones_no_tp_sets_no_stage():
    p = _pos(entry_price=100.0, current_price=112.0)
    p.tp_price = None
    compute_exit_milestones(p, atr_dist=5.0)
    assert p.exit_stage == ""


def test_exit_milestones_guard_nonpositive_atr():
    p = _pos(entry_price=100.0, current_price=112.0)
    compute_exit_milestones(p, atr_dist=0.0)
    assert p.m1_price == 0.0
    assert p.exit_stage == ""


def test_exit_milestones_falls_back_to_mark_price():
    """When current_price is unavailable, staging uses mark_price."""
    p = _pos(entry_price=100.0, current_price=0.0, mark_price=111.0)
    p.tp_price = 115.0
    compute_exit_milestones(p, atr_dist=5.0)
    assert p.exit_stage == "M2"


# --- TP anchoring in calculate_position_risk (#1 regression) ---------------

def test_trailing_tp_is_entry_anchored(monkeypatch):
    """Regression: TRAILING TP used to be stop-anchored (final_sl + 3*ATR), which at
    inception equals M2. It must be entry-anchored so the ladder stays uniform."""
    monkeypatch.setattr("core.stop_loss.update_high_water_mark", lambda *a, **k: None)
    atr = 5.0
    p = _pos(entry_price=100.0, current_price=112.0, max_since_entry=112.0)
    profile = RiskProfile(conid="1", ticker="TST", atr_value=atr, stop_type="TRAILING",
                          highest_sl=0.0, inception_atr=atr)
    calculate_position_risk(p, {"1": profile})
    assert p.tp_price == pytest.approx(100.0 + TP_ATR_MULTIPLE * atr)  # 115, not 122
    assert p.tp_price != p.m2_price


def test_fixed_tp_is_entry_anchored(monkeypatch):
    monkeypatch.setattr("core.stop_loss.update_high_water_mark", lambda *a, **k: None)
    p = _pos(entry_price=100.0, current_price=112.0)
    # FIXED: atr_value holds the stop *price*; inception_atr is the true ATR distance.
    profile = RiskProfile(conid="1", ticker="TST", atr_value=95.0, stop_type="FIXED",
                          highest_sl=0.0, inception_atr=5.0)
    calculate_position_risk(p, {"1": profile})
    assert p.tp_price == pytest.approx(100.0 + TP_ATR_MULTIPLE * 5.0)  # 115


def test_fixed_tp_fallback_uses_entry_minus_stop(monkeypatch):
    """When inception_atr is missing, the ATR for TP falls back to entry - final_sl."""
    monkeypatch.setattr("core.stop_loss.update_high_water_mark", lambda *a, **k: None)
    p = _pos(entry_price=100.0, current_price=112.0)
    profile = RiskProfile(conid="1", ticker="TST", atr_value=95.0, stop_type="FIXED",
                          highest_sl=0.0, inception_atr=None)
    calculate_position_risk(p, {"1": profile})
    # final_sl = 95, fallback ATR = 100 - 95 = 5 -> TP = 115
    assert p.tp_price == pytest.approx(115.0)


# --- Trim matrix (Q1) ------------------------------------------------------

def test_trim_matrix_trend_m2_holds():
    pct, rationale = TRIM_MATRIX[("M2", "TREND")]
    assert pct == 0.0
    assert "trim" in rationale.lower()


@pytest.mark.parametrize("key,expected_pct", [
    (("M2", "NORMAL"),  0.33),
    (("M2", "RANGING"), 0.50),
    (("TP", "TREND"),   0.20),
    (("TP", "NORMAL"),  0.33),
    (("TP", "RANGING"), 1.00),
])
def test_trim_matrix_other_cells_unchanged(key, expected_pct):
    assert TRIM_MATRIX[key][0] == pytest.approx(expected_pct)


# --- Capital-efficiency / stale flag (Q2) ----------------------------------

def test_stale_flag_flat_old_position():
    p = _pos(date_entry=_aged(240), entry_price=100.0, current_price=101.0)
    p.calculate_financial_metrics()
    assert p.age_days >= STALE_MIN_AGE_DAYS
    assert p.aagr < CAPITAL_HURDLE_PCT
    assert p.is_stale


def test_compounding_old_position_not_stale():
    p = _pos(date_entry=_aged(240), entry_price=100.0, current_price=113.0)
    p.calculate_financial_metrics()
    assert p.aagr >= CAPITAL_HURDLE_PCT
    assert not p.is_stale


def test_young_flat_position_exempt():
    p = _pos(date_entry=_aged(60), entry_price=100.0, current_price=100.5)
    p.calculate_financial_metrics()
    assert p.age_days < STALE_MIN_AGE_DAYS
    assert not p.is_stale


def test_income_asset_excluded_from_stale():
    """A bond flat on price (but earning coupon) must not be flagged: price-only AAGR
    structurally understates income assets."""
    p = _pos(asset_class="BOND", date_entry=_aged(240), entry_price=100.0, current_price=100.5)
    p.calculate_financial_metrics()
    assert not p.is_stale
