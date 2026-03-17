import pandas as pd
from typing import List
from models import Position, Trade

class LedgerEngine:
    """
    Core accounting engine for calculating holdings from trade history.
    Implements the 'Reset-on-Zero' logic and supports corporate actions like splits.
    Now uses Trade model objects for type safety.
    """

    @staticmethod
    def calculate_positions(trades: List[Trade]) -> List[Position]:
        """
        Unified engine for "Reset-on-Zero" ledger replay.
        Supports Transfers and Corporate Actions (Splits).
        """
        if not trades:
            return []
            
        # Group trades by (Account, Conid) manually since they are objects
        trades_by_key = {}
        for t in trades:
            acct = getattr(t, 'account_id', 'U0000000')
            key = (acct, t.conid)
            if key not in trades_by_key:
                trades_by_key[key] = []
            trades_by_key[key].append(t)

        open_positions = []
        for (acct_id, conid), group in trades_by_key.items():
            # Sort by date, then side to prioritize inflows (BUY/TRANSFER_IN) over outflows on same-day trades
            # Side priority: BUY/TRANSFER_IN=0, Others=1
            def trade_sort_key(t):
                side_pri = 0 if t.side.upper() in ['BUY', 'TRANSFER_IN'] else 1
                return (t.date, side_pri)
            
            group.sort(key=trade_sort_key)
            
            qty, total_cost, first_date, first_price, multiplier = 0.0, 0.0, None, 0.0, 1.0
            
            for t in group:
                side = t.side.strip().upper()
                q = abs(t.quantity)
                p = abs(t.price)
                m = float(t.multiplier) if t.multiplier is not None else 1.0
                
                # Special handling for opening balance reset
                if 'OPENING_BALANCE' in t.source.upper():
                    qty, total_cost, first_date, first_price, multiplier = q, q * p * m, t.date, p, m
                    continue
                
                if side in ['BUY', 'TRANSFER_IN']:
                    # Reset point: if we were flat, this is a new inception
                    if qty <= 0.0001:
                        first_date = t.date
                        first_price = p
                        multiplier = m
                    total_cost += q * p * m
                    qty += q
                elif side in ['SELL', 'TRANSFER_OUT'] and qty > 0:
                    # Cost basis reduction (FIFO/WAC style)
                    total_cost -= q * (total_cost / qty)
                    qty -= q
                    # Reset point: if we hit zero, wipe history
                    if qty <= 0.0001:
                        qty, total_cost, first_date, first_price, multiplier = 0.0, 0.0, None, 0.0, 1.0
                elif side == 'SPLIT':
                    # A split changes quantity but keeps total_cost the same.
                    # We must also adjust the inception price proportionally.
                    if qty > 0:
                        split_ratio = qty / (qty + q)
                        first_price = first_price * split_ratio
                    qty += q
            
            if qty > 0.0001:
                latest = group[-1]
                # Entry price should be the average price in 'points' (e.g. 98.5)
                # total_cost is in dollars (Price * Qty * Mult)
                # To get back to 'points', we divide by (Qty * 1.0) because total_cost already has Mult.
                # However, to be consistent with how Position.to_dict() works, 
                # entry_price * Qty * Mult must = total_cost.
                # Therefore: entry_price = total_cost / (qty * multiplier)
                # The issue is that total_cost was ALREADY scaled during ingestion for some sources.
                
                open_positions.append(Position(
                    name=latest.description or latest.ticker,
                    ticker=latest.ticker,
                    conid=str(conid),
                    account_id=str(acct_id),
                    asset_class=latest.asset_category,
                    ccy=latest.currency,
                    date_entry=pd.to_datetime(first_date),
                    qty=qty,
                    entry_price=total_cost / (qty * multiplier) if (qty * multiplier) != 0 else 0,
                    inception_price=first_price,
                    multiplier=multiplier,
                    mark_price=0.0, 
                    isin="", 
                    listing_exchange=latest.listing_exchange,
                    underlying_symbol=latest.underlying_symbol
                ))
        
        return open_positions
