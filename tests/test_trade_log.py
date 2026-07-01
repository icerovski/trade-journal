"""Phase 2 — trade-log schema (additive) tests.

Acceptance (per docs/ClaudeCode_Implementation_Instructions.md Phase 2):
  * old logs load: a row from a table missing the new columns still loads/saves;
  * new fields persist;
  * skipped source picks can be logged;
  * no change to trade logic (covered by the untouched golden master).

All tests run against a throwaway SQLite file — never the real trade_journal.db.
"""

import sqlite3

import pytest

import db
from core.trade_log import (
    TradeLogEntry,
    STATUS_TAKEN,
    STATUS_SKIPPED,
    CLASS_TECHNICAL,
    PERSISTED_FIELDS,
    COLUMN_TYPES,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point db at an isolated file and initialise the schema."""
    db_file = tmp_path / "test_trade_journal.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db_file


def test_dataclass_and_schema_agree():
    # The dataclass must declare every persisted column (single source of truth).
    for name in COLUMN_TYPES:
        assert hasattr(TradeLogEntry(), name)


def test_full_entry_round_trips(temp_db):
    entry = TradeLogEntry(
        date="2025-06-01", ticker="avgo", status=STATUS_TAKEN, conid="123",
        source="Newsletter X", took_independently=False, theme="AI Semis",
        classification=CLASS_TECHNICAL, regime="MOMENTUM", archetype="Continuation pullback",
        stop_source="HVN_14d", flagged=True, confluence_count=3, event_adjacent=False,
        entry=365.0, stop=350.0, r1=15.0, r_pct=0.5, atr_period="ATR14-daily",
        atr_value=19.64, realized_r=None, notes="scale-out planned",
    )
    row_id = db.add_trade_log_entry(entry)
    assert row_id > 0

    loaded = db.get_trade_log_entries(ticker="AVGO")
    assert len(loaded) == 1
    e = loaded[0]
    assert e.ticker == "AVGO"                 # uppercased on insert
    assert e.status == STATUS_TAKEN
    assert e.classification == CLASS_TECHNICAL
    assert e.stop_source == "HVN_14d"
    assert e.entry == 365.0 and e.stop == 350.0 and e.r1 == 15.0
    assert e.confluence_count == 3
    # Booleans survive the INTEGER round-trip as real bools.
    assert e.flagged is True and e.took_independently is False and e.event_adjacent is False


def test_minimal_entry_defaults_empty(temp_db):
    db.add_trade_log_entry({"date": "2025-06-02", "ticker": "IBM"})
    e = db.get_trade_log_entries(ticker="IBM")[0]
    assert e.date == "2025-06-02"
    # Every unspecified field is empty/None — nothing fabricated.
    assert e.entry is None and e.stop is None and e.realized_r is None
    assert e.classification == "" and e.source == ""
    assert e.flagged is None


def test_skipped_source_pick_logs_date_and_price(temp_db):
    # §0a: log skipped picks so the funnel itself can be benchmarked.
    db.add_trade_log_entry(TradeLogEntry(
        date="2025-06-03", ticker="TSLA", status=STATUS_SKIPPED,
        source="Newsletter X", entry=250.0, notes="failed G2 basis",
    ))
    db.add_trade_log_entry(TradeLogEntry(date="2025-06-04", ticker="MSFT", status=STATUS_TAKEN))

    skipped = db.get_trade_log_entries(status=STATUS_SKIPPED)
    assert [e.ticker for e in skipped] == ["TSLA"]
    assert skipped[0].entry == 250.0


def test_outcome_fields_backfill(temp_db):
    row_id = db.add_trade_log_entry(TradeLogEntry(date="2025-06-05", ticker="NVDA", r1=10.0))
    db.update_trade_log_entry(
        row_id, realized_r=2.3, realized_return_base=1840.0,
        result_vs_benchmark=0.8, mae_r=-0.6, mfe_r=2.9,
    )
    e = db.get_trade_log_entries(ticker="NVDA")[0]
    assert e.realized_r == 2.3 and e.mae_r == -0.6 and e.mfe_r == 2.9
    assert e.result_vs_benchmark == 0.8


def test_update_ignores_unknown_keys(temp_db):
    row_id = db.add_trade_log_entry(TradeLogEntry(date="2025-06-06", ticker="AMD"))
    # Passing a non-column key must not raise (callers can pass a superset).
    db.update_trade_log_entry(row_id, realized_r=1.1, not_a_column="x")
    assert db.get_trade_log_entries(ticker="AMD")[0].realized_r == 1.1


def test_old_row_without_new_columns_still_loads_and_saves(temp_db, monkeypatch):
    """The core Phase-2 acceptance: a pre-existing table missing the new columns
    is migrated in place; its old rows load (new fields NULL) and remain saveable."""
    # Simulate a legacy table with only a subset of columns and a row in it.
    conn = sqlite3.connect(temp_db)
    conn.execute("DROP TABLE IF EXISTS trade_log")
    conn.execute(
        "CREATE TABLE trade_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "date TEXT, ticker TEXT, entry REAL)"
    )
    conn.execute("INSERT INTO trade_log (date, ticker, entry) VALUES ('2024-01-01', 'OLD', 100.0)")
    conn.commit()
    conn.close()

    # Re-run init: the per-column ALTER loop adds every missing column.
    db.init_db()

    entries = db.get_trade_log_entries(ticker="OLD")
    assert len(entries) == 1
    e = entries[0]
    assert e.entry == 100.0                    # legacy data intact
    assert e.realized_r is None                # new column defaulted to NULL
    assert e.classification is None or e.classification == ""

    # Old row is still fully saveable through the new columns.
    db.update_trade_log_entry(e.id, realized_r=1.5, classification=CLASS_TECHNICAL)
    e2 = db.get_trade_log_entries(ticker="OLD")[0]
    assert e2.realized_r == 1.5 and e2.classification == CLASS_TECHNICAL
