"""Schema lifecycle: prospect promotion and one-shot startup migrations.

Two invariants that only bite in production, where init_db runs on every launch
and promotion runs on every dashboard render:

  * Promoting a WATCH prospect must carry EVERY decision the user made while the
    idea was on the watch list (preset, classification, exit shape, TP override,
    currency) onto the ACTIVE profile, and must never raise.
  * A data-mutating migration must run exactly once. Its WHERE clause is a
    historical guard, not a permanent invariant, so re-running it can rewrite a
    legitimate row created long after the migration was written.
"""

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_trade_journal.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db_file


def _watch_prospect(**over):
    """A WATCH profile carrying every optional decision field."""
    kwargs = dict(
        conid="PROSPECT:NVDA", ticker="NVDA", atr=120.0, stop_type="FIXED",
        status="WATCH", entry_type="SINGLE", scale_step=0.5,
        max_r_pct=0.60, max_exp_pct=3.0, inception_stop=120.0, inception_atr=9.5,
        profile="B", tp_atr_mult=4.0, classification="THESIS", exit_shape="THESIS",
        ccy="USD",
    )
    kwargs.update(over)
    db.set_position_risk(**kwargs)


def _active_row(conid):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM risk_profiles WHERE conid = ? AND status = 'ACTIVE'", (str(conid),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# --------------------------------------------------------------------------
# Prospect promotion
# --------------------------------------------------------------------------
def test_promotion_carries_every_decision_field(temp_db):
    _watch_prospect()
    db.promote_prospect_to_active("NVDA", "4815162342")

    row = _active_row("4815162342")
    assert row is not None, "promotion must create the ACTIVE profile"
    # The regression: these five were dropped by the old column list, silently
    # discarding a preset tag, a §0a classification, a §5a exit shape and a TP
    # override the moment the idea was filled.
    assert row["profile"] == "B"
    assert row["tp_atr_mult"] == 4.0
    assert row["classification"] == "THESIS"
    assert row["exit_shape"] == "THESIS"
    assert row["ccy"] == "USD"
    # …alongside the risk settings that were already carried.
    assert row["atr_value"] == 120.0
    assert row["stop_type"] == "FIXED"
    assert row["max_r_pct"] == 0.60
    assert row["max_exp_pct"] == 3.0
    assert row["inception_stop"] == 120.0
    assert row["inception_atr"] == 9.5


def test_promotion_retires_the_watch_row(temp_db):
    _watch_prospect()
    db.promote_prospect_to_active("NVDA", "4815162342")
    assert db.get_watch_list_profiles() == []


def test_promotion_starts_the_ratchet_from_zero(temp_db):
    # highest_sl belongs to the lot, not the idea — a new lot starts clean.
    _watch_prospect()
    db.promote_prospect_to_active("NVDA", "4815162342")
    assert _active_row("4815162342")["highest_sl"] == 0.0


def test_promotion_is_a_noop_without_a_prospect(temp_db):
    db.promote_prospect_to_active("NVDA", "4815162342")
    assert _active_row("4815162342") is None


def test_promotion_does_not_clobber_an_existing_active_profile(temp_db):
    # The ACTIVE and WATCH unique indexes are independent, so both rows can exist
    # for one conid. The old INSERT hit idx_active_conid and took the dashboard
    # down, since promotion runs inside get_dashboard_df's consolidation step.
    db.set_position_risk("4815162342", "NVDA", 200.0, "TRAILING", classification="TECHNICAL")
    _watch_prospect()

    db.promote_prospect_to_active("NVDA", "4815162342")  # must not raise

    row = _active_row("4815162342")
    assert row["atr_value"] == 200.0            # the live profile is untouched
    assert row["classification"] == "TECHNICAL"
    assert db.get_watch_list_profiles() == []   # the redundant prospect is retired

    conn = db.get_conn()
    n_active = conn.execute(
        "SELECT COUNT(*) FROM risk_profiles WHERE conid = ? AND status = 'ACTIVE'",
        ("4815162342",)
    ).fetchone()[0]
    conn.close()
    assert n_active == 1


# --------------------------------------------------------------------------
# One-shot migrations
# --------------------------------------------------------------------------
def test_all_migrations_recorded_on_first_init(temp_db):
    conn = db.get_conn()
    recorded = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    conn.close()
    assert recorded == {name for name, _ in db._ONE_SHOT_MIGRATIONS}


def test_fixed_stop_rewrite_cannot_fire_a_second_time(temp_db):
    # A leveraged name that halved and was legitimately re-stopped well below its
    # inception stop matches the historical "looks like an ATR distance" guard.
    # Re-running the migration would restore the old stop AND ratchet highest_sl
    # up to it — a fabricated breach on a position the user just re-stopped.
    db.set_position_risk("999", "AGQ", 60.0, "FIXED", inception_stop=400.0, inception_atr=25.0)

    db.init_db()  # simulate the next app launch

    row = _active_row("999")
    assert row["atr_value"] == 60.0, "the user's stop must survive a restart"
    assert row["highest_sl"] == 0.0, "the ratchet must not be raised by a migration"


def test_manual_trade_purge_does_not_repeat(temp_db):
    # Nothing can create a MANUAL trade any more, but if a future path did, the
    # legacy purge must not silently delete it on the next launch.
    db.add_trade("2026-08-01", "NVDA", "BUY", 10, 100.0, "999",
                 source="MANUAL", external_id="manual-1")

    db.init_db()

    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM trades WHERE source = 'MANUAL'").fetchone()[0]
    conn.close()
    assert n == 1


def test_preset_tagging_does_not_retag_a_deliberate_edit(temp_db):
    # A user who clears a profile tag and lands on the legacy limit combination
    # must not be silently re-tagged (and re-limited) on the next launch.
    db.set_position_risk("777", "IBM", 50.0, "FIXED", max_r_pct=0.50, max_exp_pct=3.0)

    db.init_db()

    row = _active_row("777")
    assert row["profile"] is None
    assert row["max_r_pct"] == 0.50
    assert row["max_exp_pct"] == 3.0


def test_new_migration_runs_once_then_never_again(temp_db, monkeypatch):
    # The append-a-name mechanism: a fresh entry runs on the next launch only.
    monkeypatch.setattr(db, "_ONE_SHOT_MIGRATIONS", db._ONE_SHOT_MIGRATIONS + (
        ("007_test_only", "UPDATE risk_profiles SET ticker = ticker || '!'"),
    ))
    db.set_position_risk("888", "AMD", 50.0, "FIXED")

    db.init_db()
    assert _active_row("888")["ticker"] == "AMD!"

    db.init_db()
    assert _active_row("888")["ticker"] == "AMD!", "a recorded migration must not re-run"
