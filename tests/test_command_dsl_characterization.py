"""Golden master over the Strategy Lab command DSL (`on_strategy_change`).

The command line is the app's densest surface — eleven token families whose parse
is strictly order-dependent (`X:T` must not read as a TRAILING flag; `TP:+35%`
must not read as a `+35` share add; `THM:` contains a T; `TP:3:1` must not read as
the fixed multiple `3`). All of that ordering lives inside a 250-line Textual
event handler and, until now, could not be executed without mounting the app.

This pins the handler's observable output — the draft dict it stores, plus the
messages it emits — across a command matrix, so extracting the parser into
`core/command_parser.py` is provably behaviour-preserving.

Mechanism matches `test_characterization.py` and the risk-panel golden master. A
diff here means a token's meaning changed; if that is intended, delete the
snapshot deliberately and regenerate it in its own commit.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from models import Position
from ui.risk_workspace import RiskWorkspace

GOLDEN = Path(__file__).parent / "snapshots" / "command_dsl_golden.json"


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------
class _Widget:
    def __init__(self, value=""):
        self.value = value
        self.cells = {}

    def update(self, *a, **k):
        pass

    def update_cell(self, row_key, column_key, value):
        self.cells[column_key] = value


class _Workspace:
    def __init__(self, pos, command, *, total_nav=1_000_000.0, discovery=None):
        self.current_conid = str(pos.conid)
        self.positions = [pos]
        self.total_nav = total_nav
        self.nav_ccy = "EUR"
        self.drafts = {}
        self.discovery_cache = {str(pos.conid): discovery} if discovery else {}
        self.messages = []
        self._last_modeling_error = None
        self._widgets = {"#atr-input": _Widget(command)}

    def query_one(self, selector, _cls=None):
        return self._widgets.setdefault(selector, _Widget())

    def notify(self, message, **kwargs):
        self.messages.append(str(message))

    def _notify_snap(self, message):
        self.messages.append(str(message))

    def refresh_risk_checklist(self, *a, **k):
        pass

    def run(self):
        RiskWorkspace.on_strategy_change(self)
        return {
            "draft": self.drafts.get(self.current_conid),
            "messages": self.messages,
            "cells": self._widgets.get("#portfolio-table", _Widget()).cells,
        }


class _Row:
    def __init__(self, label, atr, shrunk=False):
        self.label, self.atr_wilder, self.window_shrunk = label, atr, shrunk


_DISCOVERY = {"current_price": 110.0, "max_price": 125.0,
              "rows": [_Row("14d", 8.0), _Row("12w", 18.0), _Row("12m", 34.0)]}
_THIN_DISCOVERY = {"current_price": 110.0, "max_price": 125.0,
                   "rows": [_Row("14d", 8.0, shrunk=True), _Row("12q", 40.0, shrunk=True)]}


def _position(**over):
    p = Position(
        name="Test Corp", ticker="TST", conid="999", asset_class="STK", ccy="USD",
        date_entry=pd.Timestamp("2025-06-01"), qty=1000.0, entry_price=100.0,
    )
    p.current_price, p.mark_price, p.max_since_entry = 110.0, 109.0, 120.0
    p.multiplier, p.fx_rate = 1.0, 0.92
    p.atr, p.stop_type, p.sl_price = 8.0, "TRAILING", 95.0
    p.inception_stop, p.inception_atr = 92.0, 10.0
    p.max_r_pct, p.max_exp_pct = 1.0, 5.0
    p.tp_price, p.tp_atr_mult, p.tp_is_override = 130.0, 0.0, False
    p.classification, p.exit_shape = "", "LADDER"
    for k, v in over.items():
        setattr(p, k, v)
    return p


# Each entry: name -> (command, position overrides, workspace kwargs)
COMMANDS = {
    # --- stop value forms ---------------------------------------------------
    "trailing_dollar":        ("10 T", {}, {}),
    "trailing_dollar_prefix": ("$10 T", {}, {}),
    "trailing_percent":       ("15% T", {}, {}),
    "trailing_at_price":      ("@100 T", {}, {}),
    "fixed_price":            ("95 F", {}, {}),
    "fixed_price_decimal":    ("291.60 F", {}, {}),
    "value_only_keeps_type":  ("12", {}, {}),

    # --- presets and limits -------------------------------------------------
    "preset_small":           ("10 T P:S", {}, {}),
    "preset_base":            ("10 T P:B", {}, {}),
    "preset_large":           ("10 T P:L", {}, {}),
    "explicit_r":             ("10 T R:0.5", {}, {}),
    "explicit_e":             ("10 T E:2.5", {}, {}),
    "preset_then_override":   ("10 T P:S R:0.9", {}, {}),

    # --- classification (§0a) -----------------------------------------------
    "class_thesis":           ("10 T C:TH", {}, {}),
    "class_technical":        ("10 T C:TE", {}, {}),
    "class_clear":            ("10 T C:-", dict(classification="THESIS"), {}),
    "class_long_forms":       ("10 T C:THESIS", {}, {}),

    # --- journal tags (§7) --------------------------------------------------
    "source_tag":             ("10 T SRC:ZACKS", {}, {}),
    "theme_tag":              ("10 T THM:SEMIS", {}, {}),
    "source_and_theme":       ("10 T SRC:STANSBERRY THM:AI-INFRA", {}, {}),
    # THM contains a T — it must not be read as the TRAILING flag.
    "theme_not_trailing_flag": ("95 F THM:TECH", {}, {}),

    # --- exit shapes (§5a) --------------------------------------------------
    "shape_hard":             ("10 T X:H", {}, {}),
    "shape_thesis":           ("10 T X:T", {}, {}),
    "shape_runner_alias":     ("10 T X:R", {}, {}),
    "shape_ladder":           ("10 T X:L", {}, {}),
    "shape_clear":            ("10 T X:-", dict(exit_shape="HARD"), {}),
    # X:T must not be read as a TRAILING flag on a FIXED command.
    "shape_thesis_on_fixed":  ("95 F X:T", {}, {}),
    # C:TH implies the thesis shape unless X: is typed or a shape is stored.
    "coupling_applies":       ("10 T C:TH", {}, {}),
    "coupling_overridden":    ("10 T C:TH X:H", {}, {}),
    "coupling_respects_stored": ("10 T C:TH", dict(exit_shape="HARD"), {}),

    # --- take-profit override ------------------------------------------------
    "tp_plain":               ("10 T TP:4", {}, {}),
    "tp_r_form":              ("10 T TP:4R", {}, {}),
    "tp_percent":             ("10 T TP:+35%", {}, {}),
    # N:1 is measured from the live price to the MODELED stop, so it only resolves
    # when the stop sits below the price. A 10-wide trail off a 120 high lands
    # exactly on the 110 price — that case must warn, not silently set a target.
    "tp_ratio":               ("20 T TP:3:1", {}, {}),
    "tp_ratio_unresolvable":  ("10 T TP:3:1", {}, {}),
    "tp_clear":               ("10 T TP:-", dict(tp_atr_mult=5.0, tp_is_override=True), {}),
    "tp_dollar_rejected":     ("10 T TP:$60K", {}, {}),
    "tp_keeps_saved_override": ("10 T", dict(tp_atr_mult=5.0, tp_is_override=True), {}),

    # --- quantity modeling ---------------------------------------------------
    "add_shares":             ("10 T +50", {}, {}),
    "trim_shares":            ("10 T -200", {}, {}),
    "goal_seek_be":           ("10 T BE", {}, {}),
    # TP:+35% must not be misread as a +35 share add.
    "tp_percent_not_an_add":  ("10 T TP:+35%", {}, {}),

    # --- gap sizing (§6) -----------------------------------------------------
    "gap_price":              ("10 T G:85", {}, {}),
    "gap_with_add":           ("10 T G:85 +20", {}, {}),

    # --- FIXED inception-ATR snap -------------------------------------------
    "fixed_snap_with_discovery": ("92 F", {}, {"discovery": _DISCOVERY}),
    "fixed_snap_thin_history":   ("92 F", {}, {"discovery": _THIN_DISCOVERY}),
    "fixed_snap_no_discovery":   ("92 F", {}, {}),
    "fixed_snap_no_stored_atr":  ("92 F", dict(inception_atr=None), {"discovery": _THIN_DISCOVERY}),

    # --- prospects and combinations -----------------------------------------
    "prospect_sizing":        ("100 F P:B", dict(qty=0.0, entry_price=0.0), {}),
    "full_house":             ("291.60 F P:B C:TE X:H TP:4R SRC:ZACKS THM:SEMIS G:250", {}, {}),
    "trailing_full_house":    ("12% T P:L C:TH +100 SRC:MOTLEY", {}, {}),
}


def _run(name):
    command, pos_over, ws_kwargs = COMMANDS[name]
    return _Workspace(_position(**pos_over), command, **ws_kwargs).run()


def _capture_all():
    return {name: _run(name) for name in COMMANDS}


# --------------------------------------------------------------------------
# The tripwire
# --------------------------------------------------------------------------
def test_command_dsl_matches_golden():
    actual = _capture_all()

    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True),
                          encoding="utf-8")
        pytest.fail(
            f"Bootstrapped {GOLDEN.name} from the CURRENT parse. Inspect it, confirm it "
            f"describes today's token meanings, commit it, then re-run."
        )

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(actual) == set(expected), (
        "Command set changed. Adding a case is fine — regenerate the snapshot in its own "
        "commit so the diff is reviewable."
    )
    for name in expected:
        assert actual[name] == expected[name], (
            f"Parse changed for '{name}' ({COMMANDS[name][0]!r}).\n"
            f"--- expected ---\n{json.dumps(expected[name], indent=2)}\n"
            f"--- actual ---\n{json.dumps(actual[name], indent=2)}"
        )


def test_every_command_produces_a_draft():
    # A command that silently fails to parse stores nothing — the exact signature of
    # the C:TH defect. Every case in the matrix must reach the draft.
    for name in COMMANDS:
        assert _run(name)["draft"] is not None, f"'{name}' produced no draft"


def test_ordering_hazards_hold():
    # The four parse-order traps, asserted by meaning rather than by snapshot text
    # so a regression names itself.
    assert _run("shape_thesis_on_fixed")["draft"]["type"] == "FIXED"
    assert _run("theme_not_trailing_flag")["draft"]["type"] == "FIXED"
    assert _run("tp_percent_not_an_add")["draft"]["hypo_add"] is None
    # TP:3:1 must not be read as the fixed multiple 3 (which would leave ":1" behind).
    assert _run("tp_ratio")["draft"]["tp_atr_mult"] == 4.0   # 110 + 3×(110−100) = 140 = 4R


def test_unresolvable_tp_ratio_warns_and_sets_nothing():
    result = _run("tp_ratio_unresolvable")
    assert result["draft"]["tp_atr_mult"] is None
    assert any("TP ratio needs the price above the stop" in m for m in result["messages"])
