"""Zone-scan structural context (§4 gate inputs) — persistence + freshness.

The scanner workspace persists per-ticker context (regime, flagged, independent
confluence count, stop_source, DMA trail anchor) after each scan; the risk
workspace's gate check consumes it freshness-guarded. Stale or missing context
must degrade the gates to NA — never feed them last month's structure.
"""

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_trade_journal.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db_file


def _row(**over):
    base = dict(
        ticker="avgo", regime="MOMENTUM", flagged=True, confluence_count=3,
        stop_source="HVN_14d", stop_price=340.0, trail_anchor=300.0, tag="ZONE-MOMO",
    )
    base.update(over)
    return base


def test_round_trip_and_uppercasing(temp_db):
    db.save_scan_context([_row()])
    ctx = db.get_scan_context("AVGO")
    assert ctx["ticker"] == "AVGO"          # stored upper-cased
    assert ctx["regime"] == "MOMENTUM"
    assert ctx["flagged"] is True           # INTEGER coerced back to bool
    assert ctx["confluence_count"] == 3
    assert ctx["stop_source"] == "HVN_14d"
    assert ctx["trail_anchor"] == 300.0
    assert db.get_scan_context("avgo")["ticker"] == "AVGO"  # lookup case-blind


def test_latest_scan_replaces_previous(temp_db):
    db.save_scan_context([_row(flagged=True, confluence_count=3)])
    db.save_scan_context([_row(flagged=False, confluence_count=1, stop_source="")])
    ctx = db.get_scan_context("AVGO")
    assert ctx["flagged"] is False and ctx["confluence_count"] == 1
    # One row per ticker — REPLACE, never accumulate.
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM scan_context").fetchone()[0]
    conn.close()
    assert n == 1


def test_unflagged_row_persists_for_g3(temp_db):
    # G3 (fallback artifact) specifically needs flagged=False + regime.
    db.save_scan_context([_row(flagged=False, stop_source="", stop_price=None)])
    ctx = db.get_scan_context("AVGO", max_age_days=7)
    assert ctx["flagged"] is False and ctx["regime"] == "MOMENTUM"


def test_freshness_window_expires_stale_context(temp_db):
    db.save_scan_context([_row()])
    assert db.get_scan_context("AVGO", max_age_days=7) is not None  # scanned today

    conn = db.get_conn()
    conn.execute("UPDATE scan_context SET scan_date = '2020-01-01'")
    conn.commit()
    conn.close()
    assert db.get_scan_context("AVGO", max_age_days=7) is None      # stale → NA path
    assert db.get_scan_context("AVGO") is not None                  # no window → raw row


def test_malformed_date_treated_as_stale(temp_db):
    db.save_scan_context([_row()])
    conn = db.get_conn()
    conn.execute("UPDATE scan_context SET scan_date = 'not-a-date'")
    conn.commit()
    conn.close()
    assert db.get_scan_context("AVGO", max_age_days=7) is None


def test_missing_ticker_returns_none(temp_db):
    assert db.get_scan_context("NVDA", max_age_days=7) is None
    db.save_scan_context([{"ticker": "", "regime": "NORMAL"}])   # blank ticker skipped
    assert db.get_scan_context("", max_age_days=7) is None
