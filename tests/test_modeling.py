"""The pre-trade modeling engine (`core/modeling.py`).

Extracted from `refresh_risk_checklist`, where it was 200 lines of decision logic
inside a Textual method and could not be executed without mounting the app. The
render is pinned separately by `test_risk_panel_characterization.py`; this file
tests the decisions themselves — what the panel *concludes*, not how it prints it.

The load-bearing rule is the verdict precedence:

    breach → explicit user model (±N / BE) → exit stage → add → trim → hold

Each arm suppresses everything below it. The one that matters most is
exit-stage-over-add: exposure headroom sizes a new position, and is never licence
to add to a winner that has reached a profit-taking stage.
"""

import pandas as pd
import pytest

from core.modeling import (
    ModelInputs,
    build_position_model,
    decide_verdict,
    resolve_effective_atr,
    resolve_tp_multiple,
    solve_breakeven_add,
)
from models import Position

NAV = 1_000_000.0


def _position(**over):
    p = Position(
        name="Test Corp", ticker="TST", conid="999", asset_class="STK", ccy="USD",
        date_entry=pd.Timestamp("2025-06-01"), qty=1000.0, entry_price=100.0,
    )
    p.current_price, p.mark_price, p.max_since_entry = 110.0, 109.0, 120.0
    p.multiplier, p.fx_rate = 1.0, 1.0
    p.atr, p.stop_type, p.sl_price = 8.0, "TRAILING", 95.0
    p.inception_stop, p.inception_atr = 92.0, 10.0
    p.tp_price, p.m1_price, p.m2_price = 130.0, 110.0, 120.0
    p.max_r_pct, p.max_exp_pct = 1.0, 5.0
    p.exit_stage, p.trend_regime, p.exit_shape = "", "NORMAL", "LADDER"
    for k, v in over.items():
        setattr(p, k, v)
    return p


def _model(pos=None, **input_kw):
    nav = input_kw.pop("total_nav", NAV)
    recommender = input_kw.pop("exit_recommender", None)
    return build_position_model(pos or _position(), total_nav=nav,
                                inputs=ModelInputs(**input_kw),
                                exit_recommender=recommender)


def _exit_rec(**over):
    """A stand-in exit recommendation, as _exit_recommendation would return."""
    rec = {"verb": "TRIM", "color": "yellow", "shares": 330, "pct": 0.33,
           "restore_sl": None, "headline": "TRIM ~330 sh (33%)", "reason": "because"}
    rec.update(over)
    return lambda *a, **k: rec


# --------------------------------------------------------------------------
# Verdict precedence — the core contract
# --------------------------------------------------------------------------
def test_breach_outranks_everything():
    # Even with a user model AND an exit stage pending, a breached stop wins and
    # the directive is a full exit.
    m = _model(_position(current_price=90.0, sl_price=95.0, exit_stage="TP"),
               add=500, exit_recommender=_exit_rec())
    assert m.verdict.label == "EXIT NOW — stop breached"
    assert m.verdict.target_qty == 0


def test_user_model_outranks_the_exit_ladder():
    # An explicit ±N is the user overriding the system on purpose.
    m = _model(_position(exit_stage="M2"), add=50, exit_recommender=_exit_rec())
    assert m.verdict.label == "MODELING: ADD 50 sh"
    assert m.verdict.target_qty == 1050


def test_exit_stage_outranks_exposure_headroom():
    # THE rule: headroom sizes a new position; it is never licence to add to a
    # winner at a profit-taking stage. Target quantity must not grow.
    pos = _position(qty=100.0, exit_stage="M2")   # tiny position => lots of room
    m = _model(pos, exit_recommender=_exit_rec())
    assert m.room > 0, "fixture must have headroom for this test to mean anything"
    assert m.verdict.target_qty == 100
    assert "TRIM ~330" in m.verdict.label
    # …and the headroom is still reported, muted, rather than hidden.
    assert "exposure room exists, but no adds at target" in m.verdict.sub


def test_add_when_there_is_room_and_no_exit_stage():
    m = _model(_position(qty=100.0))
    assert m.verdict.label.startswith("ADD +")
    assert m.verdict.target_qty > 100


def test_trim_when_over_the_exposure_limit():
    m = _model(_position(qty=60000.0))
    assert m.verdict.label.startswith("TRIM ")
    assert m.verdict.target_qty < 60000


def test_hold_when_within_all_limits_with_no_room():
    m = _model(_position(qty=1000.0, max_exp_pct=11.0))
    assert m.verdict.label == "HOLD — at max size"
    assert m.verdict.target_qty == 1000


@pytest.mark.parametrize("arm,kwargs,expected", [
    ("breach",   dict(is_breached=True),                      "EXIT NOW — stop breached"),
    ("model",    dict(modeled_add=10),                        "MODELING: ADD 10 sh"),
    ("be_fail",  dict(goal_seek="BE"),                        "GOAL-SEEK: P/L@Stop = 0 not reachable by buying"),
    ("ladder",   dict(has_exit=True),                         "TRIM ~330 sh (33%)"),
    ("add",      dict(room=5),                                "ADD +5 sh"),
    ("trim",     dict(room=-5),                               "TRIM 5 sh"),
    ("hold",     dict(),                                      "HOLD — at max size"),
])
def test_each_verdict_arm_in_isolation(arm, kwargs, expected):
    # decide_verdict is pure, so every arm can be hit directly rather than by
    # constructing a position that happens to reach it.
    audit = {"is_breached": kwargs.get("is_breached", False), "current_exposure_pct": 1.0}
    v = decide_verdict(
        audit=audit, qty=1000.0, price=110.0, max_exp_pct=5.0,
        modeled_add=kwargs.get("modeled_add"), goal_seek=kwargs.get("goal_seek"),
        exit_rec=_exit_rec()() if kwargs.get("has_exit") else None,
        room=kwargs.get("room", 0),
    )
    assert v.label == expected


def test_breakeven_tag_only_on_goal_seek():
    audit = {"is_breached": False, "current_exposure_pct": 1.0}
    solved = decide_verdict(audit=audit, qty=1000.0, price=110.0, max_exp_pct=5.0,
                            modeled_add=200, goal_seek="BE", exit_rec=None, room=0)
    manual = decide_verdict(audit=audit, qty=1000.0, price=110.0, max_exp_pct=5.0,
                            modeled_add=200, goal_seek=None, exit_rec=None, room=0)
    assert solved.label.endswith("(P/L@Stop → 0)")
    assert not manual.label.endswith("(P/L@Stop → 0)")


# --------------------------------------------------------------------------
# Break-even solver
# --------------------------------------------------------------------------
def test_breakeven_reachable_only_for_a_ratcheted_winner():
    # add = qty·(entry−stop)/(stop−price) > 0 needs entry < stop < price. For a
    # loser you would need price < stop, which is a breach — so it is unreachable.
    assert solve_breakeven_add(1000, 100.0, 105.0, 110.0) == 1000   # stop above cost
    assert solve_breakeven_add(1000, 100.0, 95.0, 110.0) is None    # ordinary long
    assert solve_breakeven_add(1000, 100.0, 95.0, 95.0) is None     # price == stop
    assert solve_breakeven_add(0, 100.0, 105.0, 110.0) is None      # nothing held


def test_breakeven_blend_actually_lands_on_the_stop():
    qty, entry, stop, price = 1000.0, 100.0, 105.0, 110.0
    add = solve_breakeven_add(qty, entry, stop, price)
    blended = (entry * qty + price * add) / (qty + add)
    assert blended == pytest.approx(stop)


# --------------------------------------------------------------------------
# ATR and TP resolution
# --------------------------------------------------------------------------
class _Row:
    def __init__(self, label, atr):
        self.label, self.atr_wilder, self.window_shrunk = label, atr, False


def test_fixed_stop_never_uses_atr_field_as_a_distance():
    # For FIXED, position.atr holds the stop PRICE. Using it as a volatility
    # measure would be catastrophic — an ATR of 95 on a 100 stock.
    pos = _position(stop_type="FIXED", atr=95.0)
    disc = {"rows": [_Row("14d", 8.0), _Row("12w", 18.0)]}
    assert resolve_effective_atr(pos, ModelInputs(), disc, 100.0, 95.0) == 8.0


def test_fixed_stop_falls_back_to_inception_then_distance():
    pos = _position(stop_type="FIXED", atr=95.0, inception_atr=11.0)
    assert resolve_effective_atr(pos, ModelInputs(), None, 100.0, 95.0) == 11.0
    pos.inception_atr = 0.0
    assert resolve_effective_atr(pos, ModelInputs(), None, 100.0, 92.0) == pytest.approx(8.0)


def test_trailing_stop_uses_the_live_atr():
    assert resolve_effective_atr(_position(), ModelInputs(), None, 100.0, 95.0) == 8.0


def test_modeled_atr_wins_over_everything():
    pos = _position(stop_type="FIXED", atr=95.0)
    assert resolve_effective_atr(pos, ModelInputs(atr=12.0), None, 100.0, 95.0) == 12.0


def test_tp_multiple_precedence():
    saved = _position(tp_atr_mult=5.0, tp_is_override=True)
    assert resolve_tp_multiple(saved, ModelInputs()) == 5.0                 # saved override
    assert resolve_tp_multiple(saved, ModelInputs(tp_mult=4.0)) == 4.0      # modeled wins
    assert resolve_tp_multiple(saved, ModelInputs(tp_mult=None)) == 3       # modeled clear -> default
    assert resolve_tp_multiple(_position(), ModelInputs()) == 3             # nothing set


def test_reward_ladder_is_anchored_to_the_inception_atr_not_the_live_one():
    # The live ATR governs the stop; letting it move the target would drift the
    # ladder away as volatility expands.
    m = _model(_position(inception_atr=10.0, atr=25.0))
    assert m.r_unit == 10.0
    assert m.tp_target == pytest.approx(100.0 + 3 * 10.0)


# --------------------------------------------------------------------------
# Pricing rules
# --------------------------------------------------------------------------
def test_held_position_prices_at_market_never_at_entry():
    # Pricing a winner at entry would fabricate a breach when its stop sits above cost.
    m = _model(_position(entry_price=100.0, current_price=110.0, sl_price=105.0))
    assert m.price == 110.0
    assert not m.audit["is_breached"]


def test_prospect_prices_at_the_hypothetical_entry():
    pos = _position(qty=0.0, entry_price=0.0, sl_price=None)
    m = _model(pos, entry=200.0, stop=180.0, qty=10.0)
    assert m.price == 200.0


def test_quantity_modeling_transacts_at_the_live_price():
    # An add must reflect what you would actually pay now, not the modeled entry.
    m = _model(_position(current_price=110.0), entry=100.0, add=50)
    assert m.price == 110.0


# --------------------------------------------------------------------------
# Sizing projection
# --------------------------------------------------------------------------
def test_no_projection_when_no_transaction_is_implied():
    assert _model(_position(qty=1000.0, max_exp_pct=11.0)).sizing is None   # HOLD → no action
    assert _model(_position(qty=0.0, entry_price=0.0, sl_price=None),
                  entry=100.0, stop=90.0).sizing is None                     # nothing held yet


# --------------------------------------------------------------------------
# NAV unavailable (a failed IBKR sync returns 0.0)
# --------------------------------------------------------------------------
def test_zero_nav_suspends_sizing_rather_than_asserting_safety():
    # "HOLD — within all limits" would assert a limit check that never ran.
    m = _model(total_nav=0.0)
    assert m.verdict.label == "NAV UNAVAILABLE — sizing suspended"
    assert m.verdict.target_qty == 1000       # no trade suggested
    assert m.room == 0
    assert m.sizing is None                   # no projection without a denominator
    assert m.audit["nav_known"] is False


def test_zero_nav_still_detects_a_breach():
    # Pure price geometry — losing this would be the worst failure of a degraded panel.
    m = _model(_position(current_price=90.0, sl_price=95.0), total_nav=0.0)
    assert m.audit["is_breached"] is True
    assert m.verdict.label == "EXIT NOW — stop breached"
    assert m.verdict.target_qty == 0


def test_zero_nav_preserves_the_arms_that_do_not_need_nav():
    # A user model is arithmetic on quantity; the ladder reads stage and regime.
    assert _model(total_nav=0.0, add=50).verdict.label == "MODELING: ADD 50 sh"
    laddered = _model(_position(exit_stage="M2"), total_nav=0.0, exit_recommender=_exit_rec())
    assert laddered.verdict.label == "TRIM ~330 sh (33%)"


def test_zero_nav_audit_dict_has_the_same_keys_as_a_normal_one():
    # The original defect was a PARTIAL dict. Key parity is the actual fix.
    from core.stop_loss import audit_position_risk
    normal = audit_position_risk(110.0, 95.0, 100.0, 1000.0, 1.0, NAV)
    degraded = audit_position_risk(110.0, 95.0, 100.0, 1000.0, 1.0, 0.0)
    assert set(degraded) == set(normal)


def test_zero_nav_never_suggests_a_size():
    from core.stop_loss import audit_position_risk
    degraded = audit_position_risk(110.0, 95.0, 100.0, 1000.0, 1.0, 0.0)
    assert degraded["adjustment"] == 0.0
    assert degraded["stop_to_restore"] is None and degraded["shares_to_trim"] is None
    assert degraded["status_color"] == "GRAY"      # not assessable, not "fine"


def test_add_projection_blends_the_average_cost():
    m = _model(_position(qty=1000.0, entry_price=100.0, current_price=110.0), add=1000)
    sz = m.sizing
    assert sz.net_action == 1000
    assert sz.new_qty == 2000
    assert sz.new_entry == pytest.approx(105.0)          # WAC of 1000@100 + 1000@110


def test_trim_projection_leaves_average_cost_alone():
    # Selling cannot move a weighted-average cost.
    m = _model(_position(qty=1000.0, entry_price=100.0), add=-400)
    assert m.sizing.new_qty == 600
    assert m.sizing.new_entry == pytest.approx(100.0)


def test_add_column_contributions_sum_to_the_balance():
    # The panel's ADD column must reconcile: BEG + ADD == BALANCE, or the table lies.
    m = _model(_position(qty=1000.0, entry_price=100.0, current_price=110.0), add=500)
    sz, audit = m.sizing, m.audit
    assert audit["current_risk_pct"] + sz.r_add_pct == pytest.approx(sz.new_r_pct, abs=1e-9)


def test_trailing_sl_percent_is_flat_across_the_transaction():
    # The ATR width does not change when you buy shares.
    m = _model(_position(stop_type="TRAILING", qty=1000.0), add=500)
    sz = m.sizing
    assert sz.sl_pct_beg == sz.sl_pct_add == sz.sl_pct_bal


def test_fixed_sl_percent_measures_from_each_basis():
    m = _model(_position(stop_type="FIXED", atr=90.0, qty=1000.0,
                         entry_price=100.0, current_price=110.0),
               stop=90.0, add=500)
    sz = m.sizing
    assert sz.sl_pct_beg == pytest.approx(10.0)                 # (100-90)/100
    assert sz.sl_pct_add == pytest.approx(100 * 20 / 110)       # (110-90)/110
    assert sz.sl_pct_beg != sz.sl_pct_bal


def test_hcm_basis_flips_between_cost_and_market():
    winner = _model(_position(entry_price=100.0, current_price=110.0), add=100)
    loser = _model(_position(entry_price=100.0, current_price=90.0, sl_price=80.0), add=100)
    assert winner.sizing.beg_is_market is True
    assert loser.sizing.beg_is_market is False


# --------------------------------------------------------------------------
# Degenerate inputs
# --------------------------------------------------------------------------
def test_no_stop_and_no_entry_yields_no_model():
    pos = _position(qty=0.0, entry_price=0.0, sl_price=None,
                    current_price=0.0, mark_price=0.0)
    assert build_position_model(pos, total_nav=NAV, inputs=ModelInputs()) is None


def test_missing_stop_falls_back_to_entry_making_risk_zero():
    m = _model(_position(sl_price=None))
    assert m.stop == m.entry
    assert m.audit["current_risk_pct"] == pytest.approx(0.0)
