import pytest
import pandas as pd
from models import Trade
from core.ledger_engine import LedgerEngine


def make_trade(date, side, qty, price, conid="C001", account="U0000001", multiplier=1.0, source="TEST"):
    return Trade(
        date=date, ticker="TEST", side=side, quantity=qty, price=price,
        conid=conid, account_id=account, multiplier=multiplier, source=source
    )


# ---------------------------------------------------------------------------
# Basic buy
# ---------------------------------------------------------------------------

def test_single_buy_creates_position():
    trades = [make_trade("2024-01-01", "BUY", 100, 50.0)]
    positions = LedgerEngine.calculate_positions(trades)

    assert len(positions) == 1
    p = positions[0]
    assert p.qty == 100.0
    assert p.entry_price == pytest.approx(50.0)
    assert p.inception_price == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Weighted Average Cost
# ---------------------------------------------------------------------------

def test_wac_on_scale_in():
    trades = [
        make_trade("2024-01-01", "BUY", 100, 50.0),
        make_trade("2024-01-15", "BUY", 100, 60.0),
    ]
    positions = LedgerEngine.calculate_positions(trades)

    assert len(positions) == 1
    p = positions[0]
    assert p.qty == 200.0
    assert p.entry_price == pytest.approx(55.0)       # (5000 + 6000) / 200
    assert p.inception_price == pytest.approx(50.0)   # first buy price


def test_partial_sell_preserves_wac():
    """Selling shares reduces qty but must not change entry_price (WAC)."""
    trades = [
        make_trade("2024-01-01", "BUY", 100, 50.0),
        make_trade("2024-01-10", "SELL", 40, 70.0),
    ]
    positions = LedgerEngine.calculate_positions(trades)

    assert len(positions) == 1
    p = positions[0]
    assert p.qty == 60.0
    assert p.entry_price == pytest.approx(50.0)   # WAC unchanged by a sell


# ---------------------------------------------------------------------------
# Reset-on-Zero
# ---------------------------------------------------------------------------

def test_full_exit_then_reentry_resets_cost_basis():
    trades = [
        make_trade("2024-01-01", "BUY",  100, 50.0),
        make_trade("2024-01-10", "SELL", 100, 70.0),   # full exit → reset
        make_trade("2024-02-01", "BUY",   50, 80.0),   # fresh entry
    ]
    positions = LedgerEngine.calculate_positions(trades)

    assert len(positions) == 1
    p = positions[0]
    assert p.qty == 50.0
    assert p.entry_price == pytest.approx(80.0)
    assert p.inception_price == pytest.approx(80.0)   # new inception after reset
    # Inception DATE must reset to the re-entry, not the original 2024-01-01 entry.
    # The reconciliation date-healing relies on this (see BXMT regression).
    assert p.date_entry == pd.Timestamp("2024-02-01")


def test_full_exit_produces_no_position():
    trades = [
        make_trade("2024-01-01", "BUY",  100, 50.0),
        make_trade("2024-01-10", "SELL", 100, 70.0),
    ]
    positions = LedgerEngine.calculate_positions(trades)
    assert positions == []


# ---------------------------------------------------------------------------
# Forward split
# ---------------------------------------------------------------------------

def test_forward_split_adjusts_price_and_qty():
    """2-for-1 split: qty doubles, entry_price and inception_price halve."""
    trades = [
        make_trade("2024-01-01", "BUY",   100, 50.0),
        make_trade("2024-06-01", "SPLIT", 100,  0.0),   # +100 shares
    ]
    positions = LedgerEngine.calculate_positions(trades)

    assert len(positions) == 1
    p = positions[0]
    assert p.qty == 200.0
    assert p.entry_price == pytest.approx(25.0)        # 5000 / (200 * 1.0)
    assert p.inception_price == pytest.approx(25.0)    # halved by split ratio


def test_forward_split_preserves_total_cost():
    """Total cost basis (entry_price × qty × multiplier) must be unchanged by a split."""
    trades = [
        make_trade("2024-01-01", "BUY",   100, 50.0),
        make_trade("2024-06-01", "SPLIT", 100,  0.0),
    ]
    positions = LedgerEngine.calculate_positions(trades)
    p = positions[0]
    cost_before = 100 * 50.0 * 1.0
    cost_after = p.entry_price * p.qty * p.multiplier
    assert cost_after == pytest.approx(cost_before)


# ---------------------------------------------------------------------------
# Reverse split
# ---------------------------------------------------------------------------

def test_reverse_split_adjusts_price_and_qty():
    """1-for-2 reverse split: qty halves, entry_price and inception_price double."""
    trades = [
        make_trade("2024-01-01", "BUY",    100, 50.0),
        make_trade("2024-06-01", "SPLIT",  -50,  0.0),   # −50 shares
    ]
    positions = LedgerEngine.calculate_positions(trades)

    assert len(positions) == 1
    p = positions[0]
    assert p.qty == 50.0
    assert p.entry_price == pytest.approx(100.0)       # 5000 / (50 * 1.0)
    assert p.inception_price == pytest.approx(100.0)   # doubled by split ratio


def test_reverse_split_preserves_total_cost():
    trades = [
        make_trade("2024-01-01", "BUY",    100, 50.0),
        make_trade("2024-06-01", "SPLIT",  -50,  0.0),
    ]
    positions = LedgerEngine.calculate_positions(trades)
    p = positions[0]
    cost_before = 100 * 50.0 * 1.0
    cost_after = p.entry_price * p.qty * p.multiplier
    assert cost_after == pytest.approx(cost_before)


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------

def test_same_day_offsetting_transfers_net_to_zero():
    """TRANSFER_IN and TRANSFER_OUT of equal size on the same day cancel out."""
    trades = [
        make_trade("2024-01-01", "TRANSFER_IN",  100, 50.0, account="U0000001"),
        make_trade("2024-01-01", "TRANSFER_OUT", 100, 50.0, account="U0000001"),
    ]
    positions = LedgerEngine.calculate_positions(trades)
    assert positions == []


def test_intercompany_transfer_moves_position_between_accounts():
    """
    TRANSFER_OUT from Account A, TRANSFER_IN to Account B (same conid).
    Account A ends flat; Account B holds the position.
    """
    trades = [
        make_trade("2024-01-01", "BUY",          100, 50.0, account="U0000001"),
        make_trade("2024-03-01", "TRANSFER_OUT", 100, 50.0, account="U0000001"),
        make_trade("2024-03-01", "TRANSFER_IN",  100, 50.0, account="U0000002"),
    ]
    positions = LedgerEngine.calculate_positions(trades)

    # Only Account B should hold a position
    assert len(positions) == 1
    p = positions[0]
    assert p.account_id == "U0000002"
    assert p.qty == 100.0


# ---------------------------------------------------------------------------
# Multi-account isolation
# ---------------------------------------------------------------------------

def test_separate_accounts_produce_separate_positions():
    trades = [
        make_trade("2024-01-01", "BUY", 100, 50.0, account="U0000001"),
        make_trade("2024-01-01", "BUY",  50, 60.0, account="U0000002"),
    ]
    positions = LedgerEngine.calculate_positions(trades)

    assert len(positions) == 2
    by_account = {p.account_id: p for p in positions}
    assert by_account["U0000001"].qty == 100.0
    assert by_account["U0000002"].qty == 50.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_trade_list_returns_empty():
    assert LedgerEngine.calculate_positions([]) == []


def test_oversell_beyond_held_qty_zeroes_position():
    """Selling more than held should not produce a negative position."""
    trades = [
        make_trade("2024-01-01", "BUY",  100, 50.0),
        make_trade("2024-01-10", "SELL", 150, 70.0),
    ]
    positions = LedgerEngine.calculate_positions(trades)
    assert positions == []
