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
            # 1. Group by Date to net out internal transfers (Washes)
            daily_groups = {}
            for t in group:
                d = t.date.split(' ')[0] # Use date only for grouping
                if d not in daily_groups:
                    daily_groups[d] = []
                daily_groups[d].append(t)
            
            qty, total_cost, first_date, first_price, multiplier = 0.0, 0.0, None, 0.0, 1.0
            
            sorted_dates = sorted(daily_groups.keys())
            for d in sorted_dates:
                day_trades = daily_groups[d]
                
                # Sort day trades: inflows first for individual accounts, 
                # but we need to net out transfers specifically.
                def day_sort_key(t):
                    s = t.side.upper()
                    if s in ['BUY', 'TRANSFER_IN']: return 0
                    if s == 'SPLIT': return 1
                    return 2
                day_trades.sort(key=day_sort_key)

                # Process all non-transfer trades first, then the net transfer
                other_trades = [t for t in day_trades if t.side not in ['TRANSFER_IN', 'TRANSFER_OUT']]
                transfers = [t for t in day_trades if t.side in ['TRANSFER_IN', 'TRANSFER_OUT']]
                
                # Combine others and net transfer
                net_transfer_qty = sum(t.quantity if t.side == 'TRANSFER_IN' else -t.quantity for t in transfers)
                
                # If there are transfers, we pick a representative price (avg of inflows if net > 0)
                inflows = [t for t in transfers if t.side == 'TRANSFER_IN']
                inflow_qty_sum = sum(t.quantity for t in inflows)
                
                if inflow_qty_sum > QTY_ZERO_THRESHOLD:
                    rep_transfer_price = sum(t.price * t.quantity for t in inflows) / inflow_qty_sum
                elif transfers:
                    rep_transfer_price = transfers[0].price
                else:
                    rep_transfer_price = 0
                
                active_day_trades = other_trades
                if abs(net_transfer_qty) > QTY_ZERO_THRESHOLD:
                    # Create a synthetic net transfer trade
                    side = 'TRANSFER_IN' if net_transfer_qty > 0 else 'TRANSFER_OUT'
                    active_day_trades.append(Trade(
                        date=d, ticker=group[0].ticker, side=side, 
                        quantity=abs(net_transfer_qty), price=rep_transfer_price, 
                        conid=conid, multiplier=group[0].multiplier
                    ))
                
                # Re-sort to ensure Inception happens if we were flat
                active_day_trades.sort(key=day_sort_key)

                for t in active_day_trades:
                    side = t.side.strip().upper()
                    q = abs(t.quantity)
                    p = abs(t.price)
                    m = float(t.multiplier) if t.multiplier is not None else 1.0
                    
                    if 'OPENING_BALANCE' in t.source.upper() if hasattr(t, 'source') else False:
                        qty, total_cost, first_date, first_price, multiplier = q, q * p * m, t.date, p, m
                        continue
                    
                    if side in ['BUY', 'TRANSFER_IN']:
                        if qty <= QTY_ZERO_THRESHOLD:
                            first_date = t.date
                            first_price = p
                            multiplier = m
                        total_cost += q * p * m
                        qty += q
                    elif side in ['SELL', 'TRANSFER_OUT'] and qty > 0:
                        total_cost -= q * (total_cost / qty)
                        qty -= q
                        if qty <= QTY_ZERO_THRESHOLD:
                            qty, total_cost, first_date, first_price, multiplier = 0.0, 0.0, None, 0.0, 1.0
                    elif side == 'SPLIT':
                        # Use signed quantity: positive = forward split (more shares, lower price)
                        # negative = reverse split (fewer shares, higher price)
                        split_qty = t.quantity
                        if qty > 0:
                            new_qty = qty + split_qty
                            if new_qty > QTY_ZERO_THRESHOLD:
                                first_price = first_price * (qty / new_qty)
                            qty = max(0.0, new_qty)
                        # total_cost unchanged — corporate action, not a purchase
            
            if qty > QTY_ZERO_THRESHOLD:
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
