"""Phase 3 — THESIS/TECHNICAL classification (carry-only) tests.

Acceptance (docs/ClaudeCode_Implementation_Instructions.md Phase 3):
  * tag sets / reads / persists;
  * untagged trades behave exactly as before (default "" / None, no exit branching).

The classification is stored on risk_profiles, carried onto the Position, and
surfaced/committed in the pre-trade flow — but no exit logic branches on it yet.
"""

import pandas as pd
import pytest

import db
from core import stop_loss
from core.stop_loss import calculate_position_risk
from models import Position, RiskProfile
from ui.risk_workspace import RiskWorkspace, parse_classification


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_trade_journal.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db_file


# --------------------------------------------------------------------------
# Pure command-token parser
# --------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("C:TH", "THESIS"),
    ("C:TE", "TECHNICAL"),
    ("C:THESIS", "THESIS"),
    ("C:TECHNICAL", "TECHNICAL"),
    ("C:-", ""),
])
def test_parse_classification_tokens(raw, expected):
    cls, rest = parse_classification(raw)
    assert cls == expected
    assert rest == ""


def test_parse_classification_absent_returns_none():
    cls, rest = parse_classification("15 T P:L")
    assert cls is None
    assert rest == "15 T P:L"  # untouched


def test_parse_classification_coexists_and_strips():
    cls, rest = parse_classification("15 T C:TH")
    assert cls == "THESIS"
    assert rest == "15 T"


# --------------------------------------------------------------------------
# Persistence on risk_profiles
# --------------------------------------------------------------------------
def test_set_and_read_classification(temp_db):
    db.set_position_risk("555", "NVDA", 90.0, "FIXED", classification="THESIS")
    settings = db.get_all_risk_settings()
    assert settings["555"].classification == "THESIS"


def test_untagged_profile_defaults_none(temp_db):
    db.set_position_risk("556", "IBM", 90.0, "FIXED")
    assert db.get_all_risk_settings()["556"].classification is None


def test_classification_untouched_when_omitted(temp_db):
    db.set_position_risk("557", "AMD", 90.0, "FIXED", classification="TECHNICAL")
    # A later edit that doesn't pass classification must preserve the stored tag (_KEEP).
    db.set_position_risk("557", "AMD", 88.0, "FIXED")
    assert db.get_all_risk_settings()["557"].classification == "TECHNICAL"


def test_classification_can_be_cleared(temp_db):
    db.set_position_risk("558", "TSLA", 90.0, "FIXED", classification="THESIS")
    db.set_position_risk("558", "TSLA", 90.0, "FIXED", classification="")
    assert db.get_all_risk_settings()["558"].classification is None


# --------------------------------------------------------------------------
# Carry onto the Position (no exit branching)
# --------------------------------------------------------------------------
def _position():
    p = Position(
        name="Test", ticker="TST", conid="999", asset_class="STK", ccy="USD",
        date_entry=pd.Timestamp("2025-01-01"), qty=100.0, entry_price=100.0,
    )
    p.current_price = 110.0
    p.mark_price = 108.0
    p.max_since_entry = 115.0
    return p


def test_classification_carried_onto_position():
    profile = RiskProfile(
        conid="999", ticker="TST", atr_value=90.0, stop_type="FIXED",
        highest_sl=0.0, inception_stop=90.0, inception_atr=10.0,
        classification="THESIS",
    )
    p = _position()
    calculate_position_risk(p, {"999": profile})
    assert p.classification == "THESIS"


def test_untagged_position_classification_empty():
    profile = RiskProfile(
        conid="999", ticker="TST", atr_value=90.0, stop_type="FIXED",
        highest_sl=0.0, inception_stop=90.0, inception_atr=10.0,
    )
    p = _position()
    calculate_position_risk(p, {"999": profile})
    # Default carries as "" — identical to pre-Phase-3 behaviour; nothing branches on it.
    assert p.classification == ""


# --------------------------------------------------------------------------
# C:TH → X:T coupling, driven through the real command handler (§0a)
#
# Regression guard for a shipped defect: the coupling block referenced
# `active_shape` ABOVE the line that binds it, so every `C:TH` command raised
# UnboundLocalError. `on_strategy_change` swallows exceptions into the log, so
# the failure was invisible — no draft, no notification, nothing to commit.
# These tests assert the draft that a successful parse must produce, which is
# unreachable if the handler raises.
# --------------------------------------------------------------------------
class _StubWidget:
    """Stands in for the three Textual widgets the handler touches."""

    def __init__(self, value=""):
        self.value = value
        self.cells = {}

    def update(self, *args, **kwargs):
        pass

    def update_cell(self, row_key, column_key, value):
        self.cells[column_key] = value


class _StubWorkspace:
    """Drives RiskWorkspace.on_strategy_change without mounting a Textual app.

    The command DSL and the modeling maths live inside a 250-line UI method, so
    this harness is the only way to test their branches. If that logic is ever
    extracted into a core module, point these tests at it instead.
    """

    def __init__(self, position, command, total_nav=1_000_000.0):
        self.current_conid = str(position.conid)
        self.positions = [position]
        self.discovery_cache = {}
        self.drafts = {}
        self.total_nav = total_nav
        self.messages = []
        self._last_modeling_error = None
        self._widgets = {
            "#atr-input": _StubWidget(command),
            "#preset-legend": _StubWidget(),
            "#portfolio-table": _StubWidget(),
        }

    def query_one(self, selector, _widget_cls=None):
        return self._widgets[selector]

    def notify(self, message, **kwargs):
        self.messages.append(message)

    def _notify_snap(self, message):
        self.messages.append(message)

    def refresh_risk_checklist(self, *args, **kwargs):
        pass

    def run(self, command=None):
        if command is not None:
            self._widgets["#atr-input"].value = command
        RiskWorkspace.on_strategy_change(self)
        return self.drafts.get(self.current_conid)


def _draft_for(command, **position_over):
    pos = _position()
    for field, value in position_over.items():
        setattr(pos, field, value)
    return _StubWorkspace(pos, command).run()


def test_thesis_tag_produces_a_draft_at_all():
    # The defect's signature: the handler raised, so no draft was ever recorded.
    draft = _draft_for("10 T C:TH")
    assert draft is not None, "C:TH must not abort the modeling pass"
    assert draft["classification"] == "THESIS"


def test_thesis_tag_implies_thesis_exit_shape():
    draft = _draft_for("10 T C:TH")
    assert draft["exit_shape"] == "THESIS"


def test_explicit_exit_shape_overrides_the_thesis_default():
    # X: typed in the same edit wins — the coupling is a default, not a law.
    draft = _draft_for("10 T C:TH X:H")
    assert draft["classification"] == "THESIS"
    assert draft["exit_shape"] == "HARD"


def test_stored_non_default_shape_is_not_overridden():
    draft = _draft_for("10 T C:TH", exit_shape="HARD")
    assert draft["exit_shape"] == "HARD"


def test_technical_tag_leaves_the_shape_alone():
    draft = _draft_for("10 T C:TE")
    assert draft["classification"] == "TECHNICAL"
    assert draft["exit_shape"] == "LADDER"  # the Position default, carried unchanged


def test_untagged_command_touches_neither_field():
    draft = _draft_for("10 T")
    assert draft["classification"] == ""
    assert draft["exit_shape"] == "LADDER"


# --------------------------------------------------------------------------
# A modeling failure must reach the user
#
# on_strategy_change catches everything so a half-typed command can't crash the
# app. That is right, but a bare logger.error is not: the command was NOT
# applied, no draft exists to commit, and the table still shows the previous
# model — indistinguishable from success. Input.Changed fires per keystroke, so
# the report has to be deduped rather than dropped.
# --------------------------------------------------------------------------
BAD_COMMAND = "1.2.3"   # float("1.2.3") — a realistic typo, raises inside the parse


def test_modeling_failure_is_reported_to_the_user():
    ws = _StubWorkspace(_position(), BAD_COMMAND)
    assert ws.run() is None                       # nothing staged, as before
    assert ws.messages, "a failed command must not fail silently"
    assert "not applied" in ws.messages[0].lower()
    assert "ValueError" in ws.messages[0]         # names the actual fault


def test_repeated_failure_is_reported_once():
    # Typing one bad character at a time must not stack a toast per keystroke.
    ws = _StubWorkspace(_position(), BAD_COMMAND)
    ws.run()
    ws.run()
    ws.run()
    assert len(ws.messages) == 1


def test_failure_is_reported_again_after_a_good_command():
    # Dedup is per distinct fault, not once ever — a recurring fault still speaks up.
    ws = _StubWorkspace(_position(), BAD_COMMAND)
    ws.run()
    ws.run("10 T")                  # a clean parse clears the memo
    ws.run(BAD_COMMAND)
    assert len(ws.messages) == 2


def test_successful_command_says_nothing():
    ws = _StubWorkspace(_position(), "10 T")
    assert ws.run() is not None
    assert ws.messages == []
