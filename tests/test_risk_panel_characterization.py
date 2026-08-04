"""Golden master over the risk-panel render (`refresh_risk_checklist`).

Purpose: make extracting the modeling engine out of `ui/risk_workspace.py` a
provably behaviour-preserving refactor. The method mixes ~200 lines of decision
logic (audit, R-unit/TP resolution, the verdict precedence chain, the sizing
projection) with ~130 lines of markup assembly, and until now none of it could be
executed without mounting a Textual app.

Mechanism mirrors `test_characterization.py`: drive the real method over a fixed
scenario matrix, capture the exact string handed to the `#position-context`
widget, and compare against a committed snapshot. Any change to a rendered
character fails loudly — which is the point. If a diff here is *intended*, delete
the snapshot deliberately and re-generate it in its own commit, never silently.

The scenarios walk every branch of the verdict chain (breach → modeling ±N →
BE goal-seek → exit stage → add → trim → hold) plus the modifiers that alter the
panel around it (prospect vs held, FIXED vs TRAILING, TP override, stale, R
remediation, thin/absent discovery).
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from models import Position
from ui.risk_workspace import RiskWorkspace

GOLDEN = Path(__file__).parent / "snapshots" / "risk_panel_golden.json"


# --------------------------------------------------------------------------
# Harness — drives the real method without a Textual app
# --------------------------------------------------------------------------
class _Widget:
    def __init__(self, value=""):
        self.value = value
        self.rendered = None

    def update(self, text=None):
        self.rendered = text

    def update_cell(self, *args, **kwargs):
        pass

    def clear(self):
        pass


class _Workspace:
    """Minimal stand-in exposing exactly what refresh_risk_checklist reads."""

    def __init__(self, pos, *, total_nav=1_000_000.0, draft=None, discovery=None):
        self.current_conid = str(pos.conid)
        self.positions = [pos]
        self.total_nav = total_nav
        self.nav_ccy = "EUR"
        self.drafts = {str(pos.conid): draft} if draft else {}
        self.discovery_cache = {str(pos.conid): discovery} if discovery else {}
        self._widgets = {"#position-context": _Widget()}

    def query_one(self, selector, _cls=None):
        return self._widgets.setdefault(selector, _Widget())

    def notify(self, *a, **k):
        pass

    def render(self, **kwargs):
        RiskWorkspace.refresh_risk_checklist(self, **kwargs)
        return self._widgets["#position-context"].rendered


# --------------------------------------------------------------------------
# Deterministic fixtures — no network, no DB, no clock
# --------------------------------------------------------------------------
def _position(**over):
    p = Position(
        name="Test Corp", ticker="TST", conid="999", asset_class="STK", ccy="USD",
        date_entry=pd.Timestamp("2025-06-01"), qty=1000.0, entry_price=100.0,
    )
    p.current_price = 110.0
    p.mark_price = 109.0
    p.max_since_entry = 120.0
    p.multiplier = 1.0
    p.fx_rate = 0.92
    p.atr = 8.0
    p.stop_type = "TRAILING"
    p.sl_price = 95.0
    p.inception_stop = 92.0
    p.inception_atr = 10.0
    p.tp_price = 130.0
    p.m1_price, p.m2_price = 110.0, 120.0
    p.max_r_pct, p.max_exp_pct = 1.0, 5.0
    p.aagr, p.age_days, p.pl_pct = 12.0, 200, 10.0
    p.exit_stage = ""
    p.trend_regime = "NORMAL"
    p.exit_shape = "LADDER"
    p.classification = ""
    for k, v in over.items():
        setattr(p, k, v)
    return p


class _Row:
    """Stands in for an ATRDiscoveryRow in the discovery cache."""

    def __init__(self, label, atr):
        self.label = label
        self.atr_wilder = atr
        self.window_shrunk = False


_DISCOVERY = {"current_price": 110.0, "max_price": 120.0,
              "rows": [_Row("14d", 8.0), _Row("12w", 18.0)]}


def _draft(**over):
    d = {"atr": 8.0, "type": "TRAILING", "ticker": "TST", "max_r_pct": 1.0,
         "max_exp_pct": 5.0, "hypo_stop": 95.0, "inception_atr": 10.0,
         "profile": None, "tp_atr_mult": None, "hypo_add": None,
         "goal_seek": None, "classification": "", "gap_price": None,
         "exit_shape": ""}
    d.update(over)
    return d


# Each entry: name -> (position overrides, workspace kwargs, render kwargs).
# Ordered so related branches sit together in the snapshot diff.
SCENARIOS = {
    # --- verdict chain, in precedence order ---------------------------------
    "breach_stop_above_price":      (dict(current_price=90.0, sl_price=95.0), {}, {}),
    "modeling_add":                 ({}, {"draft": _draft(hypo_add=50)}, {}),
    "modeling_trim":                ({}, {"draft": _draft(hypo_add=-200)}, {}),
    # BE is reachable only when buying moves WAC TOWARD the stop without breaching:
    # add = qty·(entry−stop)/(stop−price) > 0 needs entry < stop < price, i.e. a stop
    # already ratcheted above cost. For a loser (entry > stop) you would need
    # price < stop, which is a breach — so that arm reports "not reachable".
    "goal_seek_be_reachable":       (dict(sl_price=105.0),
                                     {"draft": _draft(goal_seek="BE", hypo_stop=105.0)}, {}),
    "goal_seek_be_unreachable_win": ({}, {"draft": _draft(goal_seek="BE")}, {}),
    "goal_seek_be_unreachable_loss": (dict(entry_price=100.0, current_price=95.0, sl_price=90.0),
                                     {"draft": _draft(goal_seek="BE", hypo_stop=90.0)}, {}),
    "exit_stage_m1":                (dict(exit_stage="M1"), {}, {}),
    "exit_stage_m1_locked_in":      (dict(exit_stage="M1", sl_price=105.0), {}, {}),
    "exit_stage_m2_trend":          (dict(exit_stage="M2", trend_regime="TREND", current_price=121.0), {}, {}),
    "exit_stage_m2_normal":         (dict(exit_stage="M2", trend_regime="NORMAL", current_price=121.0), {}, {}),
    "exit_stage_m2_ranging":        (dict(exit_stage="M2", trend_regime="RANGING", current_price=121.0), {}, {}),
    "exit_stage_tp_trend":          (dict(exit_stage="TP", trend_regime="TREND", current_price=131.0), {}, {}),
    "exit_stage_tp_ranging":        (dict(exit_stage="TP", trend_regime="RANGING", current_price=131.0), {}, {}),
    "exit_stage_tp_hard_shape":     (dict(exit_stage="TP", current_price=131.0, exit_shape="HARD"), {}, {}),
    "room_to_add":                  (dict(qty=100.0), {}, {}),
    "over_exposure_trim":           (dict(qty=60000.0), {}, {}),
    "hold_at_max_size":             (dict(qty=1000.0, max_exp_pct=11.0, max_r_pct=1.0), {}, {}),

    # --- position shapes ----------------------------------------------------
    "prospect_no_qty":              (dict(qty=0.0, entry_price=0.0, sl_price=None), {},
                                     {"hypo_stop": 100.0, "hypo_entry": 110.0, "hypo_qty": 400.0}),
    "fixed_stop":                   (dict(stop_type="FIXED", atr=95.0), {"discovery": _DISCOVERY}, {}),
    "fixed_stop_no_discovery":      (dict(stop_type="FIXED", atr=95.0), {}, {}),
    "trailing_with_discovery":      ({}, {"discovery": _DISCOVERY}, {}),

    # --- modifiers ----------------------------------------------------------
    "tp_override_saved":            (dict(tp_atr_mult=5.0, tp_is_override=True), {}, {}),
    "tp_override_modeled":          ({}, {}, {"hypo_tp_mult": 4.0}),
    "tp_override_below_floor":      (dict(tp_atr_mult=1.5, tp_is_override=True, current_price=125.0), {}, {}),
    "stale_position":               (dict(is_stale=True, aagr=2.0, age_days=400), {}, {}),
    "r_budget_breached":            (dict(qty=5000.0, sl_price=80.0, max_r_pct=1.0), {}, {}),
    "no_stop_assigned":             (dict(sl_price=None, exit_stage=""), {}, {}),
    "thesis_shape_no_target":       (dict(exit_shape="THESIS", tp_price=None), {}, {}),
    # NAV unreadable (a failed IBKR sync returns 0.0). Percentages are suppressed,
    # but the stop breach is pure price geometry and must survive.
    "zero_nav":                     ({}, {"total_nav": 0.0}, {}),
    "zero_nav_breached":            (dict(current_price=90.0, sl_price=95.0), {"total_nav": 0.0}, {}),
    "classification_chip":          (dict(classification="THESIS"), {}, {}),
    "gap_sized_chip":               ({}, {"draft": _draft(gap_price=85.0)}, {}),
    "modeling_header_only":         ({}, {"draft": _draft()}, {}),
    "draft_rehydration_bare":       ({}, {"draft": _draft(hypo_add=25)}, {}),
}


def _render(name):
    pos_over, ws_kwargs, render_kwargs = SCENARIOS[name]
    ws = _Workspace(_position(**pos_over), **ws_kwargs)
    return ws.render(**render_kwargs)


def _capture_all():
    return {name: _render(name) for name in SCENARIOS}


# --------------------------------------------------------------------------
# The tripwire
# --------------------------------------------------------------------------
def test_risk_panel_render_matches_golden():
    actual = _capture_all()

    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2, ensure_ascii=False), encoding="utf-8")
        pytest.fail(
            f"Bootstrapped {GOLDEN.name} from the CURRENT render. Inspect it, confirm it "
            f"describes today's behaviour, commit it, then re-run. Failing on bootstrap is "
            f"deliberate: a snapshot that silently arms itself around changed behaviour is "
            f"worse than no snapshot."
        )

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert set(actual) == set(expected), (
        "Scenario set changed. Adding a scenario is fine — regenerate the snapshot in its "
        "own commit so the diff is reviewable."
    )
    for name in expected:
        assert actual[name] == expected[name], (
            f"Risk-panel render changed for '{name}'.\n"
            f"--- expected ---\n{expected[name]}\n"
            f"--- actual ---\n{actual[name]}"
        )


def test_every_scenario_actually_renders():
    # A scenario that returns None passes the comparison vacuously once the
    # snapshot records None — this keeps the matrix honest.
    for name in SCENARIOS:
        assert _render(name), f"scenario '{name}' rendered nothing"


def test_zero_nav_renders_a_degraded_panel_instead_of_crashing():
    """A failed IBKR sync leaves NAV at 0.0. That must degrade, not throw.

    Previously `audit_position_risk` early-returned a four-key dict omitting
    `adjustment`, so selecting a row after a failed sync raised KeyError. Now the
    panel renders and says what it cannot compute.
    """
    panel = _Workspace(_position(), total_nav=0.0).render()
    assert "NAV UNAVAILABLE — sizing suspended" in panel
    assert "R n/a" in panel and "Exp n/a" in panel
    # Never print a percentage that would read as a real, safe measurement.
    # "<pct>%[/][dim]/<limit>" is the signature of the R% and Exp% cells specifically
    # — RR and the stop buffer stay, since neither needs NAV.
    assert "%[/][dim]/" not in panel
    assert "RR [bold" in panel and "buf" in panel
    # No sizing table without a denominator.
    assert "BAL-BEG" not in panel


def test_zero_nav_still_reports_a_stop_breach():
    # The breach is a price comparison and does not need NAV. Losing it would be
    # the most dangerous possible failure mode for a degraded panel.
    panel = _Workspace(_position(current_price=90.0, sl_price=95.0), total_nav=0.0).render()
    assert "EXIT NOW — stop breached" in panel
    assert "BREACH" in panel


def _verdict_line(name):
    """The '▶ ...' directive line — its position shifts when the MODELING header
    is prepended, so locate it rather than indexing a fixed line."""
    return next((l for l in _render(name).splitlines() if l.startswith("▶ ")), "")


def test_verdict_chain_branches_are_all_covered():
    # The directive is the single most consequential string the panel emits.
    # Assert the matrix actually reaches each arm rather than trusting scenario names.
    joined = "\n".join(_verdict_line(n) for n in SCENARIOS)
    for marker in ("EXIT NOW", "MODELING: ADD", "MODELING: TRIM", "(P/L@Stop → 0)",
                   "GOAL-SEEK:", "ADD +", "TRIM", "HOLD"):
        assert marker in joined, f"no scenario reaches the '{marker}' verdict arm"


def test_exit_ladder_arms_are_covered():
    # The exit axis has its own precedence (M1 never sells; TRIM_MATRIX 0.0 == hold;
    # HARD makes TP a full exit). Each must appear in at least one scenario.
    joined = "\n".join(_verdict_line(n) for n in SCENARIOS)
    for marker in ("RAISE STOP to entry", "stop already locks in profit",
                   "let it run", "hard target hit"):
        assert marker in joined, f"no scenario reaches the '{marker}' exit arm"
