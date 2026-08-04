"""Where the app is allowed to write, and where it is not.

Three DB writes used to sit inside read paths — the trailing ratchet inside a
per-position enrichment loop, prospect promotion inside a WAC merge, and the asset
master inside CSV parsing. Read paths that write are the hardest class of bug to
reason about, and the ratchet is the dangerous one: it is monotonic and persisted,
so a transient bad price becomes permanent state that quietly raises a stop.

These tests pin both halves of the contract:
  * the calculation itself performs NO database I/O, and
  * the value it computes is still persisted, once, by the caller that owns writes.

The second half matters more than the first. Making the calculation pure is easy;
losing the write while doing it would mean stops silently stop ratcheting, and the
symptom would surface weeks later as a stale stop nobody can explain.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import core.portfolio_manager as pm_module
from core.portfolio_manager import PortfolioManager
from models import Position, RiskProfile


def _position(**over):
    p = Position(
        name="Test Corp", ticker="TST", conid="999", asset_class="STK", ccy="USD",
        date_entry=pd.Timestamp("2025-06-01"), qty=1000.0, entry_price=100.0,
    )
    p.current_price, p.mark_price, p.max_since_entry = 130.0, 129.0, 130.0
    p.multiplier, p.fx_rate = 1.0, 1.0
    for k, v in over.items():
        setattr(p, k, v)
    return p


def _profile(**over):
    kwargs = dict(conid="999", ticker="TST", atr_value=10.0, stop_type="TRAILING",
                  highest_sl=100.0, inception_stop=90.0, inception_atr=10.0)
    kwargs.update(over)
    return RiskProfile(**kwargs)


# --------------------------------------------------------------------------
# The calculation is pure
# --------------------------------------------------------------------------
def test_calculate_position_risk_performs_no_database_io(monkeypatch):
    # Every DB access in the app goes through db.get_conn, so breaking it catches
    # any write regardless of how the module happens to import things.
    import db
    from core.stop_loss import calculate_position_risk

    def _forbidden():
        raise AssertionError("risk calculation opened a database connection")

    monkeypatch.setattr(db, "get_conn", _forbidden)
    calculate_position_risk(_position(), {"999": _profile()})


def test_stop_loss_module_does_not_depend_on_the_database():
    # Structural, not mocked: the pure risk layer should have no reason to know
    # the database exists. If this fails, an I/O call crept back in.
    import ast
    import inspect

    from core import stop_loss

    tree = ast.parse(inspect.getsource(stop_loss))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "db" not in imported


def test_a_rising_stop_is_reported_rather_than_written():
    from core.stop_loss import calculate_position_risk

    # HWM 130 − ATR 10 = 120, above the stored 100 → the ratchet should advance.
    p = calculate_position_risk(_position(), {"999": _profile(highest_sl=100.0)})
    assert p.sl_price == pytest.approx(120.0)
    assert p.pending_ratchet == pytest.approx(120.0)


def test_a_stop_that_does_not_advance_reports_nothing_to_persist():
    from core.stop_loss import calculate_position_risk

    # Stored 150 already exceeds the computed 120 — the ratchet holds.
    p = calculate_position_risk(_position(), {"999": _profile(highest_sl=150.0)})
    assert p.sl_price == pytest.approx(150.0)
    assert p.pending_ratchet is None, "an unchanged ratchet must not trigger a write"


def test_a_position_without_a_profile_reports_nothing():
    from core.stop_loss import calculate_position_risk

    p = calculate_position_risk(_position(), {})
    assert getattr(p, "pending_ratchet", None) is None


# --------------------------------------------------------------------------
# …and the caller still persists it
# --------------------------------------------------------------------------
def test_enrichment_persists_the_advanced_ratchet_once():
    """The regression that would otherwise be silent: purity without persistence.

    A dropped write here does not fail anything visible — the panel still shows the
    ratcheted stop, because it was computed in memory. It would only surface later,
    as a stop that reverted after a restart.
    """
    pm = PortfolioManager()
    positions = [_position()]

    with patch.object(pm_module, "update_high_water_marks") as writer:
        pm._enrich_metrics(positions, {"999": _profile(highest_sl=100.0)}, 1_000_000.0)

    writer.assert_called_once()
    assert list(writer.call_args.args[0]) == [("999", pytest.approx(120.0))]


def test_enrichment_writes_nothing_when_no_stop_advanced():
    pm = PortfolioManager()

    with patch.object(pm_module, "update_high_water_marks") as writer:
        pm._enrich_metrics([_position()], {"999": _profile(highest_sl=150.0)}, 1_000_000.0)

    # An idle refresh must be read-only end to end.
    writer.assert_not_called()


def test_enrichment_batches_every_advanced_ratchet_into_one_call():
    # 45 positions on the live book previously meant up to 45 connections.
    pm = PortfolioManager()
    positions, settings = [], {}
    for i in range(5):
        conid = str(1000 + i)
        positions.append(_position(conid=conid))
        settings[conid] = _profile(conid=conid, highest_sl=100.0)

    with patch.object(pm_module, "update_high_water_marks") as writer:
        pm._enrich_metrics(positions, settings, 1_000_000.0)

    writer.assert_called_once()
    assert len(writer.call_args.args[0]) == 5


def test_ratchet_is_monotonic_end_to_end(tmp_path, monkeypatch):
    """Against a real database: the stop advances and never retreats."""
    import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    db.set_position_risk("999", "TST", 10.0, "TRAILING", inception_stop=90.0,
                         inception_atr=10.0)

    pm = PortfolioManager()

    # Price rallies to 130 → stop ratchets to 120.
    pm._enrich_metrics([_position()], db.get_all_risk_settings(), 1_000_000.0)
    assert db.get_all_risk_settings()["999"].highest_sl == pytest.approx(120.0)

    # Price falls back to 105 → the stored ratchet must hold at 120.
    pm._enrich_metrics([_position(current_price=105.0, max_since_entry=105.0)],
                       db.get_all_risk_settings(), 1_000_000.0)
    assert db.get_all_risk_settings()["999"].highest_sl == pytest.approx(120.0)


# --------------------------------------------------------------------------
# Batched writers
# --------------------------------------------------------------------------
def test_update_high_water_marks_only_ever_raises_a_stop(tmp_path, monkeypatch):
    import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    db.set_position_risk("999", "TST", 10.0, "TRAILING")
    db.update_high_water_marks([("999", 120.0)])
    assert db.get_all_risk_settings()["999"].highest_sl == pytest.approx(120.0)

    db.update_high_water_marks([("999", 80.0)])          # a lower stop is ignored
    assert db.get_all_risk_settings()["999"].highest_sl == pytest.approx(120.0)


def test_batched_writers_tolerate_an_empty_batch(tmp_path, monkeypatch):
    import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    db.update_high_water_marks([])        # must not open a connection or raise
    db.save_ticker_info_bulk([])


def test_save_ticker_info_bulk_upserts_every_row(tmp_path, monkeypatch):
    import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    db.save_ticker_info_bulk([
        {"conid": "1", "ticker_ibkr": "AAPL", "asset_class": "STK", "currency": "USD"},
        {"conid": "2", "ticker_ibkr": "MSFT", "asset_class": "STK", "currency": "USD"},
    ])
    assert db.get_ticker_info("1")["ticker_ibkr"] == "AAPL"
    assert db.get_ticker_info("2")["ticker_ibkr"] == "MSFT"

    # Re-ingesting the same snapshot updates in place rather than duplicating.
    db.save_ticker_info_bulk([{"conid": "1", "ticker_ibkr": "AAPL",
                               "description": "Apple Inc"}])
    assert db.get_ticker_info("1")["description"] == "Apple Inc"


# --------------------------------------------------------------------------
# Parsing is a pure transform
# --------------------------------------------------------------------------
def test_snapshot_parsing_writes_the_asset_master_exactly_once(tmp_path, monkeypatch):
    import config
    from data_loader import DataLoader

    header = ("ClientAccountID,LevelOfDetail,Symbol,Conid,Quantity,CostBasisPrice,MarkPrice,"
              "Multiplier,PercentOfNAV,FXRateToBase,AssetClass,Description,ListingExchange,"
              "CurrencyPrimary,UnderlyingSymbol,ISIN,ReportDate,OpenDateTime")
    rows = "\n".join(
        f"U1,SUMMARY,T{i},{1000+i},100,150.0,160.0,1,5.0,0.92,STK,Corp {i},"
        f"NASDAQ,USD,,US{i},2026-07-30," for i in range(4)
    )
    path = tmp_path / "open_positions_lbd.csv"
    path.write_text(f"{header}\n{rows}\n")
    monkeypatch.setattr(config, "IBKR_OPEN_POSITIONS_CSV", path)

    with patch("data_loader.db", MagicMock()) as fake_db:
        data, _ = DataLoader.get_broker_verified_snapshot()

    assert len(data) == 4
    # One bulk write for the whole file, not one per row.
    fake_db.save_ticker_info_bulk.assert_called_once()
    assert len(fake_db.save_ticker_info_bulk.call_args.args[0]) == 4
    assert not fake_db.save_ticker_info.called


def test_consolidation_does_not_promote_prospects(tmp_path, monkeypatch):
    # Promotion is a state transition, not part of a weighted-average merge.
    pm = PortfolioManager()
    with patch("db.promote_prospect_to_active") as promote:
        pm._consolidate_positions([_position(), _position(account_id="U2")])
    promote.assert_not_called()
