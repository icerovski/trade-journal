"""Connection lifetime in `db.py`.

Every function in db.py used to pair `get_conn()` with a bare `conn.close()` on
the happy path, so any exception in between left the handle open — 33 of them
against a single `try/finally`. The connection then survives inside the
traceback's frame, holding whatever transaction it had begun, on a SQLite file
that OneDrive is also syncing. Under a long-running Textual UI those accumulate.

`db.connect()` is the fix, and these tests are what keep it. The source-level
sweep at the bottom matters most: it is what stops the next function added to
db.py from quietly reintroducing the old pair.
"""

import ast
from pathlib import Path

import pytest

import db


class _TrackedConn:
    """A real connection that remembers whether it was closed."""

    def __init__(self, real):
        self._real = real
        self.closed = False

    def __getattr__(self, name):          # delegate everything else
        return getattr(self._real, name)

    def close(self):
        self.closed = True
        self._real.close()


@pytest.fixture
def opened(tmp_path, monkeypatch):
    """Points db at a temp file and hands back the list of connections opened
    AFTER schema creation, each one tracking its own close()."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_trade_journal.db")
    db.init_db()

    real_get_conn = db.get_conn
    tracked = []

    def _tracking_get_conn():
        conn = _TrackedConn(real_get_conn())
        tracked.append(conn)
        return conn

    monkeypatch.setattr(db, "get_conn", _tracking_get_conn)
    return tracked


# --------------------------------------------------------------------------
# The context manager itself
# --------------------------------------------------------------------------
def test_connect_closes_on_the_happy_path(opened):
    with db.connect() as conn:
        conn.execute("SELECT 1")
    assert [c.closed for c in opened] == [True]


def test_connect_closes_when_the_body_raises(opened):
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("SELECT 1")
            raise RuntimeError("boom")
    assert [c.closed for c in opened] == [True]


def test_connect_does_not_commit_for_you(opened):
    """`with connect()` is NOT sqlite3's own `with conn:` — that one commits or
    rolls back and leaves the handle OPEN, the exact inverse of what is wanted
    here. Commits stay explicit, so an uncommitted write must not land."""
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('probe', 'x')")
    assert db.get_setting("probe", "absent") == "absent"


# --------------------------------------------------------------------------
# Real call sites
# --------------------------------------------------------------------------
def test_a_write_that_raises_mid_body_still_closes(opened):
    """THE REGRESSION. `set_position_risk` opens a connection, runs its SELECT,
    and only then coerces its arguments — so a bad `atr` raises with the handle
    open and a read transaction already started. Before `connect()` there was no
    `finally` here at all."""
    with pytest.raises(ValueError):
        db.set_position_risk(conid="99", ticker="TEST", atr="not-a-number", stop_type="FIXED")
    assert opened and all(c.closed for c in opened)


def test_an_early_return_closes_the_connection(opened):
    """`get_conid_for_ticker` returns from inside the block when the asset master
    already knows the ticker — the path a `finally` catches and a trailing
    `close()` on the last line does not."""
    db.save_ticker_info(conid="4815162342", ticker_ibkr="NVDA")
    assert db.get_conid_for_ticker("NVDA") == "4815162342"
    assert opened and all(c.closed for c in opened)


def test_the_no_op_promotion_early_return_closes(opened):
    db.promote_prospect_to_active("NOSUCHTICKER", "1234")   # returns immediately
    assert opened and all(c.closed for c in opened)


def test_every_public_read_and_write_closes_what_it_opens(opened):
    """A sweep rather than one case per function: any of these leaking would
    otherwise only show up as a locked database on a machine that has been
    running for hours."""
    db.set_position_risk(conid="1", ticker="AAA", atr=5.0, stop_type="FIXED")
    db.add_trade(date="2026-01-02", ticker="AAA", side="BUY", quantity=10,
                 price=100.0, conid="1", external_id="X-1")
    db.save_setting("k", "v")
    db.save_scan_context([{"ticker": "AAA", "regime": "TREND"}])
    entry_id = db.add_trade_log_entry({"ticker": "AAA", "status": "TAKEN"})
    db.update_trade_log_entry(entry_id, realized_r=1.5)
    db.update_high_water_marks([("1", 95.0)])

    db.get_all_risk_settings()
    db.get_watch_list_profiles()
    db.get_all_monitored_profiles()
    db.get_presets()
    db.get_setting("k")
    db.get_ticker_info("1")
    db.get_trades_for_conid("1")
    db.get_trade_log_entries()
    db.get_scan_context("AAA")
    db.avg_sell_price_since("1", "2026-01-01")
    db.find_open_trade_log_id("1")
    db.trade_exists("X-1")

    assert len(opened) >= 19, "the sweep should have opened a connection per call"
    assert all(c.closed for c in opened)


# --------------------------------------------------------------------------
# The durable guard
# --------------------------------------------------------------------------
def test_connect_is_the_only_caller_of_get_conn():
    """Source-level, because a runtime test can only cover the functions it
    happens to name. `get_conn` stays the single chokepoint tests patch to prove
    a read path opens nothing (test_write_boundaries); `connect` is the only
    thing allowed to call it, and manual `conn.close()` is what it replaced."""
    tree = ast.parse(Path(db.__file__).read_text(encoding="utf-8"))

    bypassed, manual_close = [], []
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if func.name in ("get_conn", "connect"):
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            if isinstance(callee, ast.Name) and callee.id == "get_conn":
                bypassed.append(func.name)
            if (isinstance(callee, ast.Attribute) and callee.attr == "close"
                    and isinstance(callee.value, ast.Name) and callee.value.id == "conn"):
                manual_close.append(func.name)

    assert bypassed == [], f"call db.connect() instead of get_conn(): {bypassed}"
    assert manual_close == [], f"let db.connect() close it: {manual_close}"
