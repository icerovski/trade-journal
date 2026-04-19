import pandas as pd
from typing import List
from models import Position, Trade
from constants import QTY_ZERO_THRESHOLD

class LedgerEngine:
    """
    Core accounting engine for calculating holdings from trade history.
    Implements the 'Reset-on-Zero' logic and supports corporate actions like splits.
    Now uses Trade model objects for type safety.
    """

    @staticmethod
    def calculate_positions(trades: List[Trade]) -> List[Position]:
        """Unified 'Reset-on-Zero' ledger replay. Groups by account+conid, nets transfers, replays state."""
        if not trades:
            return []

        trades_by_key = {}
        for t in trades:
            key = (getattr(t, 'account_id', 'U0000000'), t.conid)
            trades_by_key.setdefault(key, []).append(t)

        open_positions = []
        for (acct_id, conid), group in trades_by_key.items():
            daily_groups = {}
            for t in group:
                daily_groups.setdefault(t.date.split(' ')[0], []).append(t)

            qty, total_cost, first_date, first_price, multiplier = 0.0, 0.0, None, 0.0, 1.0

            for d in sorted(daily_groups):
                for t in LedgerEngine._net_daily_transfers(daily_groups[d]):
                    qty, total_cost, first_date, first_price, multiplier = \
                        LedgerEngine._apply_trade(qty, total_cost, first_date, first_price, multiplier, t)

            if qty > QTY_ZERO_THRESHOLD:
                open_positions.append(
                    LedgerEngine._build_position(acct_id, conid, group, qty, total_cost, first_date, first_price, multiplier)
                )

        return open_positions

    @staticmethod
    def _net_daily_transfers(day_trades: List[Trade]) -> List[Trade]:
        """Nets same-day TRANSFER_IN/OUT pairs into a single synthetic trade. Returns active trades sorted for replay."""
        def _sort_key(t):
            s = t.side.upper()
            if s in ['BUY', 'TRANSFER_IN']: return 0
            if s == 'SPLIT': return 1
            return 2

        other_trades = [t for t in day_trades if t.side not in ['TRANSFER_IN', 'TRANSFER_OUT']]
        transfers    = [t for t in day_trades if t.side in ['TRANSFER_IN', 'TRANSFER_OUT']]

        net_qty = sum(t.quantity if t.side == 'TRANSFER_IN' else -t.quantity for t in transfers)

        inflows = [t for t in transfers if t.side == 'TRANSFER_IN']
        inflow_sum = sum(t.quantity for t in inflows)
        if inflow_sum > QTY_ZERO_THRESHOLD:
            rep_price = sum(t.price * t.quantity for t in inflows) / inflow_sum
        elif transfers:
            rep_price = transfers[0].price
        else:
            rep_price = 0

        active = list(other_trades)
        if abs(net_qty) > QTY_ZERO_THRESHOLD:
            ref = day_trades[0]
            active.append(Trade(
                date=ref.date.split(' ')[0],
                ticker=ref.ticker,
                side='TRANSFER_IN' if net_qty > 0 else 'TRANSFER_OUT',
                quantity=abs(net_qty),
                price=rep_price,
                conid=ref.conid,
                multiplier=ref.multiplier,
            ))

        active.sort(key=_sort_key)
        return active

    @staticmethod
    def _apply_trade(qty, total_cost, first_date, first_price, multiplier, t: Trade):
        """Applies one trade to the running position state. Returns updated (qty, total_cost, first_date, first_price, multiplier)."""
        side = t.side.strip().upper()
        q = abs(t.quantity)
        p = abs(t.price)
        m = float(t.multiplier) if t.multiplier is not None else 1.0

        if 'OPENING_BALANCE' in t.source.upper():
            return q, q * p * m, t.date, p, m

        if side in ['BUY', 'TRANSFER_IN']:
            if qty <= QTY_ZERO_THRESHOLD:
                first_date, first_price, multiplier = t.date, p, m
            total_cost += q * p * m
            qty += q
        elif side in ['SELL', 'TRANSFER_OUT'] and qty > 0:
            total_cost -= q * (total_cost / qty)
            qty -= q
            if qty <= QTY_ZERO_THRESHOLD:
                return 0.0, 0.0, None, 0.0, 1.0
        elif side == 'SPLIT':
            # Signed quantity: positive = forward split, negative = reverse split
            if qty > 0:
                new_qty = qty + t.quantity
                if new_qty > QTY_ZERO_THRESHOLD:
                    first_price = first_price * (qty / new_qty)
                qty = max(0.0, new_qty)
            # total_cost unchanged — corporate action, not a purchase

        return qty, total_cost, first_date, first_price, multiplier

    @staticmethod
    def _build_position(acct_id, conid, group: List[Trade], qty, total_cost, first_date, first_price, multiplier) -> Position:
        """Constructs a Position object from the final accumulated ledger state."""
        latest = group[-1]
        return Position(
            name=latest.description or latest.ticker,
            ticker=latest.ticker,
            conid=str(conid),
            account_id=str(acct_id),
            asset_class=latest.asset_category,
            ccy=latest.currency,
            date_entry=pd.to_datetime(first_date),
            qty=qty,
            # entry_price * qty * multiplier = total_cost (invariant)
            entry_price=total_cost / (qty * multiplier) if (qty * multiplier) != 0 else 0,
            inception_price=first_price,
            multiplier=multiplier,
            mark_price=0.0,
            isin="",
            listing_exchange=latest.listing_exchange,
            underlying_symbol=latest.underlying_symbol,
        )
