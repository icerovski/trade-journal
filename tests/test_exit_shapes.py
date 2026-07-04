"""Phase 7 — exit shapes (§5a) tests.

Acceptance (docs/ClaudeCode_Implementation_Instructions.md Phase 7):
  * current exit behaviour reproducible as the default;
  * the three new shapes are selectable and tested;
  * NO time stop — no shape forces an exit on elapsed time.
"""

import pandas as pd
import pytest

from core import stop_loss
from core.stop_loss import calculate_position_risk
from core.exit_shapes import (
    normalize_shape,
    suppresses_price_target,
    is_hard_target,
    SHAPE_LADDER,
    SHAPE_HARD_TARGET,
    SHAPE_SCALE_RUNNER,
    SHAPE_THESIS,
)
from ui.risk_workspace import _exit_recommendation
from models import Position, RiskProfile


# --------------------------------------------------------------------------
# Shape normalisation
# --------------------------------------------------------------------------
@pytest.mark.parametrize("token,expected", [
    (None, SHAPE_LADDER), ("", SHAPE_LADDER), ("L", SHAPE_LADDER), ("ladder", SHAPE_LADDER),
    ("H", SHAPE_HARD_TARGET), ("hard", SHAPE_HARD_TARGET), ("TARGET", SHAPE_HARD_TARGET),
    # RUNNER was cut as a distinct shape (it *is* the default ladder): the token and
    # stored legacy values normalize straight to LADDER, so no chip/label survives.
    ("R", SHAPE_LADDER), ("runner", SHAPE_LADDER), (SHAPE_SCALE_RUNNER, SHAPE_LADDER),
    ("T", SHAPE_THESIS), ("thesis", SHAPE_THESIS),
    ("bogus", SHAPE_LADDER),   # unknown → default
])
def test_normalize_shape(token, expected):
    assert normalize_shape(token) == expected


def test_predicates():
    assert suppresses_price_target(SHAPE_THESIS) is True
    assert suppresses_price_target(SHAPE_LADDER) is False
    assert is_hard_target(SHAPE_HARD_TARGET) is True
    assert is_hard_target(SHAPE_THESIS) is False


# --------------------------------------------------------------------------
# calculate_position_risk: default unchanged, THESIS drops the target
# --------------------------------------------------------------------------
def _position(cur=110.0):
    p = Position(name="T", ticker="TST", conid="1", asset_class="STK", ccy="USD",
                 date_entry=pd.Timestamp("2025-01-01"), qty=100.0, entry_price=100.0)
    p.current_price = cur
    p.mark_price = cur - 2
    p.max_since_entry = cur + 5
    return p


def _profile(exit_shape=None):
    return RiskProfile(conid="1", ticker="TST", atr_value=90.0, stop_type="FIXED",
                       highest_sl=0.0, inception_stop=90.0, inception_atr=10.0,
                       exit_shape=exit_shape)


def test_default_shape_keeps_target(monkeypatch):
    monkeypatch.setattr(stop_loss, "update_high_water_mark", lambda *a, **k: None)
    p = _position()
    calculate_position_risk(p, {"1": _profile(None)})
    assert p.exit_shape == SHAPE_LADDER
    assert p.tp_price == pytest.approx(130.0)   # entry + 3R, unchanged
    assert p.exit_stage in ("M1", "M2", "PRE-M1", "TP")


def test_thesis_shape_drops_target(monkeypatch):
    monkeypatch.setattr(stop_loss, "update_high_water_mark", lambda *a, **k: None)
    p = _position()
    calculate_position_risk(p, {"1": _profile(SHAPE_THESIS)})
    assert p.exit_shape == SHAPE_THESIS
    assert p.tp_price is None                    # no guessed-at-entry target
    assert p.exit_stage == ""                    # target-driven ladder stays quiet
    assert p.reward_val == 0.0
    assert p.sl_price == pytest.approx(90.0)      # stop still governs the exit


def test_hard_and_runner_keep_target(monkeypatch):
    monkeypatch.setattr(stop_loss, "update_high_water_mark", lambda *a, **k: None)
    for shape in (SHAPE_HARD_TARGET, SHAPE_SCALE_RUNNER):
        p = _position()
        calculate_position_risk(p, {"1": _profile(shape)})
        assert p.tp_price == pytest.approx(130.0)


# --------------------------------------------------------------------------
# _exit_recommendation: HARD exits full at TP; default unchanged
# --------------------------------------------------------------------------
def _rec(stage, shape="", regime="TREND", qty=100.0):
    return _exit_recommendation(stage, regime, qty, 100.0, 95.0, 130.0, 128.0, 2.0,
                                "FIXED", exit_shape=shape)


def test_hard_target_full_exit_at_tp():
    rec = _rec("TP", shape=SHAPE_HARD_TARGET)
    assert rec["verb"] == "TRIM" and rec["pct"] == 1.0
    assert rec["shares"] == 100
    assert "hard target" in rec["headline"].lower()


def test_default_tp_matches_pre_phase7():
    # With no shape, a TP in TREND is the modest 20% trim from TRIM_MATRIX — unchanged.
    default = _rec("TP", shape="")
    runner = _rec("TP", shape=SHAPE_SCALE_RUNNER)
    assert default["verb"] == "TRIM" and default["pct"] == pytest.approx(0.20)
    assert runner == default   # RUNNER is exactly today's ladder


def test_hard_target_only_changes_tp_stage():
    # M1 stays risk-free regardless of shape (hard target changes only the TP action).
    m1_default = _rec("M1", shape="")
    m1_hard = _rec("M1", shape=SHAPE_HARD_TARGET)
    assert m1_hard == m1_default


# --------------------------------------------------------------------------
# No time stop
# --------------------------------------------------------------------------
def test_no_time_stop_ancient_position_not_forced_out(monkeypatch):
    """A very old position with an intact stop and (thesis) no target is never forced
    out by elapsed time — no shape adds a time-based exit."""
    monkeypatch.setattr(stop_loss, "update_high_water_mark", lambda *a, **k: None)
    p = _position()
    p.date_entry = pd.Timestamp("2000-01-01")   # decades old
    calculate_position_risk(p, {"1": _profile(SHAPE_THESIS)})
    # No exit stage, no target — the only exit is the price stop, not the clock.
    assert p.exit_stage == ""
    assert _exit_recommendation(p.exit_stage, "RANGING", p.qty, p.entry_price,
                                p.sl_price, p.tp_price, p.current_price, 0.0,
                                "FIXED", exit_shape=p.exit_shape) is None
