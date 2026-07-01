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
from ui.risk_workspace import parse_classification


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


def test_classification_carried_onto_position(monkeypatch):
    monkeypatch.setattr(stop_loss, "update_high_water_mark", lambda *a, **k: None)
    profile = RiskProfile(
        conid="999", ticker="TST", atr_value=90.0, stop_type="FIXED",
        highest_sl=0.0, inception_stop=90.0, inception_atr=10.0,
        classification="THESIS",
    )
    p = _position()
    calculate_position_risk(p, {"999": profile})
    assert p.classification == "THESIS"


def test_untagged_position_classification_empty(monkeypatch):
    monkeypatch.setattr(stop_loss, "update_high_water_mark", lambda *a, **k: None)
    profile = RiskProfile(
        conid="999", ticker="TST", atr_value=90.0, stop_type="FIXED",
        highest_sl=0.0, inception_stop=90.0, inception_atr=10.0,
    )
    p = _position()
    calculate_position_risk(p, {"999": profile})
    # Default carries as "" — identical to pre-Phase-3 behaviour; nothing branches on it.
    assert p.classification == ""
