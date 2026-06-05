import pytest
import pandas as pd
from models import Trade, Position
from core.reconciliation_service import ReconciliationService
from core.ledger_engine import LedgerEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_trade(date, side, qty, price, conid="C001", account="U0000001", multiplier=1.0, source="IBKR_CONFIRMATION"):
    return Trade(
        date=date, ticker="TEST", side=side, quantity=qty, price=price,
        conid=conid, account_id=account, multiplier=multiplier, source=source
    )


def make_snapshot(conid, qty, entry, mark=0.0, account="U0000001", date="2024-01-01"):
    key = f"{account}:{conid}"
    return {
        key: {
            "conid": conid,
            "Symbol": "TEST",
            "Description": "Test Asset",
            "AssetClass": "STK",
            "Currency": "USD",
            "ListingExchange": "NASDAQ",
            "UnderlyingSymbol": "",
            "ISIN": "",
            "Qty": qty,
            "Entry": entry,
            "MarkPrice": mark,
            "Date": date,
            "Multiplier": 1.0,
            "FXRateToEUR": 1.0,
            "account_id": account,
        }
    }


REPORT_DATE = pd.Timestamp("2024-01-10")
LEDGER = LedgerEngine()
RECON = ReconciliationService()


# ---------------------------------------------------------------------------
# Snapshot-only (no deltas)
# ---------------------------------------------------------------------------

def test_snapshot_position_passes_through():
    snap = make_snapshot("C001", qty=100, entry=50.0)
    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [], LEDGER)

    assert len(positions) == 1
    assert positions[0].qty == 100.0
    assert positions[0].entry_price == pytest.approx(50.0)


def test_snapshot_zero_qty_excluded():
    snap = make_snapshot("C001", qty=0.0, entry=50.0)
    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [], LEDGER)
    assert positions == []


# ---------------------------------------------------------------------------
# Cost-basis healing from ledger
# ---------------------------------------------------------------------------

def test_global_ledger_heals_stepped_up_entry_price():
    """
    Broker snapshot may show a stepped-up entry after an inter-account transfer.
    The global ledger (all accounts consolidated) should recover the true original cost.
    """
    # History: bought at 40 in account 1, transferred to account 2
    history = [
        make_trade("2023-06-01", "BUY",          100, 40.0, account="U0000001", source="IBKR_TRADES_CSV"),
        make_trade("2023-12-01", "TRANSFER_OUT", 100, 40.0, account="U0000001", source="IBKR_TRADES_CSV"),
        make_trade("2023-12-01", "TRANSFER_IN",  100, 65.0, account="U0000002", source="IBKR_TRADES_CSV"),
    ]
    # Broker snapshot for account 2 shows the transfer price (stepped-up cost basis)
    snap = make_snapshot("C001", qty=100, entry=65.0, account="U0000002")

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, history, LEDGER)

    assert len(positions) == 1
    # Global ledger sees net 100 @ 40 → heals the stepped-up 65 back to 40
    assert positions[0].entry_price == pytest.approx(40.0)


def test_ledger_heals_missing_entry_date():
    """Snapshot with no Date should be healed to the ledger's inception date."""
    history = [make_trade("2023-01-15", "BUY", 100, 50.0, source="IBKR_TRADES_CSV")]
    snap = make_snapshot("C001", qty=100, entry=50.0, date=None)
    snap[f"U0000001:C001"]["Date"] = None

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, history, LEDGER)

    assert len(positions) == 1
    assert positions[0].date_entry is not None


# ---------------------------------------------------------------------------
# Intraday delta application
# ---------------------------------------------------------------------------

def test_confirmation_delta_increases_qty():
    """A BUY confirmation after the report date adds shares to the snapshot position."""
    snap = make_snapshot("C001", qty=100, entry=50.0)
    delta = make_trade("2024-01-11", "BUY", 50, 55.0)  # after REPORT_DATE

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [delta], LEDGER)

    assert len(positions) == 1
    assert positions[0].qty == 150.0


def test_confirmation_delta_wac_updates_entry_price():
    """A BUY delta should update entry_price via WAC."""
    snap = make_snapshot("C001", qty=100, entry=50.0)
    delta = make_trade("2024-01-11", "BUY", 100, 60.0)

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [delta], LEDGER)

    # WAC: (100*50 + 100*60) / 200 = 55.0
    assert positions[0].entry_price == pytest.approx(55.0)


def test_confirmation_delta_sell_reduces_qty():
    snap = make_snapshot("C001", qty=100, entry=50.0)
    delta = make_trade("2024-01-11", "SELL", 40, 70.0)

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [delta], LEDGER)

    assert positions[0].qty == 60.0


def test_confirmation_delta_full_sell_removes_position():
    snap = make_snapshot("C001", qty=100, entry=50.0)
    delta = make_trade("2024-01-11", "SELL", 100, 70.0)

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [delta], LEDGER)

    assert positions == []


def test_delta_before_report_date_ignored():
    """Confirmations ON or before the report date must not be applied as deltas."""
    snap = make_snapshot("C001", qty=100, entry=50.0)
    stale_delta = make_trade("2024-01-10", "BUY", 50, 55.0)  # same day as REPORT_DATE

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [stale_delta], LEDGER)

    assert positions[0].qty == 100.0  # unchanged


def test_delta_for_different_conid_not_applied():
    snap = make_snapshot("C001", qty=100, entry=50.0)
    delta = make_trade("2024-01-11", "BUY", 50, 55.0, conid="C999")

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [delta], LEDGER)

    assert positions[0].qty == 100.0  # unaffected


# ---------------------------------------------------------------------------
# Assets not in snapshot (pure delta path)
# ---------------------------------------------------------------------------

def test_position_not_in_snapshot_built_from_deltas():
    """A new trade confirmed after the snapshot date creates a fresh position."""
    snap = {}  # empty snapshot
    delta = make_trade("2024-01-11", "BUY", 75, 80.0)

    positions = RECON.reconcile_hybrid(snap, REPORT_DATE, [delta], LEDGER)

    assert len(positions) == 1
    assert positions[0].qty == 75.0
    assert positions[0].entry_price == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Inception date healing
# ---------------------------------------------------------------------------

def _mk_pos(conid="C001", date_entry=None, entry=0.0, inception=0.0, qty=200.0):
    p = Position(name="Test", ticker="TEST", conid=conid, asset_class="STK", ccy="USD",
                 date_entry=date_entry, qty=qty, entry_price=entry)
    p.inception_price = inception
    return p


def test_inception_date_healed_from_global_ledger():
    """Regression (BXMT): a position accumulated across many dates must take its inception
    DATE — not just its price — from the consolidated global ledger. A recent re-entry or
    broker-snapshot date must not override the true first-entry date of a continuous hold."""
    snap = _mk_pos(date_entry=pd.Timestamp("2026-04-07"), entry=18.50, inception=18.50)
    gp = _mk_pos(date_entry=pd.Timestamp("2024-09-05"), entry=18.29, inception=18.01)

    RECON._heal_from_ledger(snap, {}, {}, {"C001": gp})

    assert snap.date_entry == pd.Timestamp("2024-09-05")      # healed, not the 2026 re-entry
    assert snap.inception_price == pytest.approx(18.01)
    assert snap.entry_price == pytest.approx(18.29)           # global cost basis


def test_snapshot_date_preserved_when_no_global_match():
    """With no ledger history to heal from, the snapshot's own date is left intact."""
    snap = _mk_pos(date_entry=pd.Timestamp("2026-04-07"), entry=18.50, inception=18.50)

    RECON._heal_from_ledger(snap, {}, {}, {})

    assert snap.date_entry == pd.Timestamp("2026-04-07")
