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

def test_trailing_ladder_uses_inception_atr_not_live():
    """Regression (AVGO): the TRAILING ladder/TP must use the inception ATR (original R),
    not the live trailing ATR. Otherwise the milestones drift away as volatility expands
    and a healthy winner gets mislabelled as an early stage. The live ATR sets only the
    stop. Also covers the prior stop-anchored TP collision (TP must not equal M2)."""
    p = _pos(entry_price=100.0, current_price=130.0, max_since_entry=140.0)
    # Live ATR (atr_value) = 20 has expanded well beyond the inception ATR (R) = 5.
    profile = RiskProfile(conid="1", ticker="TST", atr_value=20.0, stop_type="TRAILING",
                          highest_sl=0.0, inception_atr=5.0)
    calculate_position_risk(p, {"1": profile})
    assert p.tp_price == pytest.approx(115.0)   # entry + 3*inception, not + 3*live (160)
    assert p.m1_price == pytest.approx(105.0)   # entry + 1*inception, not 120
    assert p.m2_price == pytest.approx(110.0)
    assert p.tp_price != p.m2_price
    # The stop still trails on the live ATR: max_since (140) - live ATR (20) = 120.
    assert p.sl_price == pytest.approx(120.0)


def test_fixed_tp_is_entry_anchored():
    p = _pos(entry_price=100.0, current_price=112.0)
    # FIXED: atr_value holds the stop *price*; inception_atr is the true ATR distance.
    profile = RiskProfile(conid="1", ticker="TST", atr_value=95.0, stop_type="FIXED",
                          highest_sl=0.0, inception_atr=5.0)
    calculate_position_risk(p, {"1": profile})
    assert p.tp_price == pytest.approx(100.0 + TP_ATR_MULTIPLE * 5.0)  # 115


def test_fixed_tp_fallback_uses_entry_minus_stop():
    """When inception_atr is missing, the ATR for TP falls back to entry - final_sl."""
    p = _pos(entry_price=100.0, current_price=112.0)
    profile = RiskProfile(conid="1", ticker="TST", atr_value=95.0, stop_type="FIXED",
                          highest_sl=0.0, inception_atr=None)
    calculate_position_risk(p, {"1": profile})
    # final_sl = 95, fallback ATR = 100 - 95 = 5 -> TP = 115
    assert p.tp_price == pytest.approx(115.0)


# --- TP override (extendable R-ladder) -------------------------------------

def test_tp_override_extends_target():
    """A per-position tp_atr_mult lifts the TP to that multiple of the *inception* ATR,
    leaving M1/M2 on the original 1R/2R rungs and using the frozen ATR (not the live one)."""
    p = _pos(entry_price=100.0, current_price=130.0, max_since_entry=140.0)
    # Live ATR (20) ≫ inception (5): the override must still anchor to inception.
    profile = RiskProfile(conid="1", ticker="TST", atr_value=20.0, stop_type="TRAILING",
                          highest_sl=0.0, inception_atr=5.0, tp_atr_mult=5.0)
    calculate_position_risk(p, {"1": profile})
    assert p.tp_price == pytest.approx(125.0)     # entry + 5 * inception(5), not live(20)
    assert p.m1_price == pytest.approx(105.0)     # unchanged 1R
    assert p.m2_price == pytest.approx(110.0)     # unchanged 2R
    assert p.tp_is_override is True
    assert p.tp_atr_mult == pytest.approx(5.0)


def test_tp_override_none_is_default_3r():
    p = _pos(entry_price=100.0, current_price=112.0)
    profile = RiskProfile(conid="1", ticker="TST", atr_value=95.0, stop_type="FIXED",
                          highest_sl=0.0, inception_atr=5.0, tp_atr_mult=None)
    calculate_position_risk(p, {"1": profile})
    assert p.tp_price == pytest.approx(115.0)      # entry + default 3R
    assert p.tp_is_override is False
    assert p.tp_atr_mult == pytest.approx(TP_ATR_MULTIPLE)


def test_tp_override_recomputes_rr():
    """RR efficiency picks up the overridden target rather than the default 3R."""
    p_def = _pos(entry_price=100.0, current_price=110.0)
    calculate_position_risk(p_def, {"1": RiskProfile(conid="1", ticker="TST", atr_value=90.0,
                            stop_type="FIXED", highest_sl=0.0, inception_atr=5.0)})
    assert p_def.rr_ratio == pytest.approx(0.25)   # (115-110)/(110-90)

    p_ovr = _pos(entry_price=100.0, current_price=110.0)
    calculate_position_risk(p_ovr, {"1": RiskProfile(conid="1", ticker="TST", atr_value=90.0,
                            stop_type="FIXED", highest_sl=0.0, inception_atr=5.0, tp_atr_mult=8.0)})
    assert p_ovr.tp_price == pytest.approx(140.0)  # 100 + 8*5
    assert p_ovr.rr_ratio == pytest.approx(1.5)    # (140-110)/(110-90)


def test_tp_override_shifts_exit_stage():
    """Extending the target keeps a position that ran past the default 3R in an earlier stage."""
    # current 122 ≥ default TP(115) → would be TP; with a 5R override (125) it is still M2.
    p = _pos(entry_price=100.0, current_price=122.0, max_since_entry=122.0)
    profile = RiskProfile(conid="1", ticker="TST", atr_value=3.0, stop_type="TRAILING",
                          highest_sl=0.0, inception_atr=5.0, tp_atr_mult=5.0)
    calculate_position_risk(p, {"1": profile})
    assert p.tp_price == pytest.approx(125.0)
    assert p.exit_stage == "M2"


# --- Live P/L at stop (degrades on breach, recovers on reclaim) -------------

def _fixed_stop_pos(current_price):
    """FIXED stop at 95, entry 100, 10 shares. risk_val (planned) = -50."""
    p = _pos(entry_price=100.0, current_price=current_price, qty=10.0)
    profile = RiskProfile(conid="1", ticker="TST", atr_value=95.0, stop_type="FIXED",
                          highest_sl=0.0, inception_atr=5.0)
    calculate_position_risk(p, {"1": profile})
    return p


def test_risk_val_live_equals_planned_above_stop():
    """While price holds above the stop, the live figure equals the planned stop-out."""
    p = _fixed_stop_pos(current_price=110.0)
    assert p.risk_val == pytest.approx(-50.0)        # (95 - 100) * 10
    assert p.risk_val_live == pytest.approx(-50.0)   # price above stop -> planned holds


def test_risk_val_live_degrades_below_stop():
    """Once price breaches the stop, the realisable exit is the live price, so the
    figure degrades past the planned stop-out and tracks the price down."""
    p = _fixed_stop_pos(current_price=90.0)          # 5 below the 95 stop
    assert p.risk_val == pytest.approx(-50.0)        # planned unchanged
    assert p.risk_val_live == pytest.approx(-100.0)  # (90 - 100) * 10


def test_risk_val_live_recovers_on_reclaim():
    """Exactly at the stop the live figure snaps back to the planned value."""
    p = _fixed_stop_pos(current_price=95.0)          # back at the stop
    assert p.risk_val_live == pytest.approx(-50.0)


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


# --- RR is informational only — no longer a forced-exit trigger ------------

def _low_rr_pos(stop_type, regime, rr):
    p = _pos(entry_price=100.0, current_price=112.0)
    p.stop_type = stop_type
    p.trend_regime = regime
    p.exit_stage = "M2"
    p.rr_ratio = rr
    p.m1_price, p.m2_price, p.tp_price = 105.0, 110.0, 115.0
    p.sl_price = 108.0  # above entry → profitable stop
    return p


def test_low_rr_does_not_trigger_efficiency_floor_fixed():
    """RR < 1.0 on a FIXED M2/TP no longer forces an exit: the floor is gone and the
    directive follows the regime (M2/TREND → hold). RR is shown elsewhere as info only."""
    from ui.risk_workspace import _exit_guidance_str
    out = _exit_guidance_str(_low_rr_pos("FIXED", "TREND", rr=0.75), 112.0)
    assert "Efficiency floor" not in out
    assert "TREND" in out


def test_low_rr_identical_for_fixed_and_trailing_stop():
    """Stop type no longer changes the directive — neither fires an RR floor."""
    from ui.risk_workspace import _exit_guidance_str
    out = _exit_guidance_str(_low_rr_pos("TRAILING", "TREND", rr=0.75), 112.0)
    assert "Efficiency floor" not in out
    assert "TREND" in out


# --- Break-even goal-seek (Strategy Lab "BE") ------------------------------

def test_solve_breakeven_add_voo_case():
    """VOO: 220 sh @ 520.27, stop 538.68, price 696.05 → add ~26 to push avg cost to the
    stop (P/L @ Stop = 0)."""
    from ui.risk_workspace import solve_breakeven_add
    add = solve_breakeven_add(qty=220, entry=520.27, stop=538.68, price=696.05)
    assert add == 26
    # Verify the blended average cost lands on the stop.
    new_entry = (520.27 * 220 + 696.05 * add) / (220 + add)
    assert new_entry == pytest.approx(538.68, abs=0.5)


def test_solve_breakeven_add_buys_low_to_lower_avg():
    """Avg cost above the stop: buying below the stop averages the cost down onto it."""
    add = _be(qty=100, entry=110.0, stop=100.0, price=90.0)
    assert add == 100
    new_entry = (110.0 * 100 + 90.0 * add) / (100 + add)
    assert new_entry == pytest.approx(100.0)


def test_solve_breakeven_returns_none_when_unreachable_by_buying():
    """Avg above stop but price also above stop: no purchase can pull the avg down to the
    stop (and trimming can't move a WAC), so there is no break-even add."""
    assert _be(qty=100, entry=110.0, stop=100.0, price=120.0) is None


def test_solve_breakeven_no_solution_edge_cases():
    assert _be(qty=100, entry=110.0, stop=100.0, price=100.0) is None  # price == stop
    assert _be(qty=0, entry=110.0, stop=100.0, price=120.0) is None     # no position


def _be(**kw):
    from ui.risk_workspace import solve_breakeven_add
    return solve_breakeven_add(**kw)


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
