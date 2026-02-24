import pandas as pd
from typing import List
from models import Position, Trade
from logger import logger
from db import close_risk_profile

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
            
        # Group trades by Conid manually since they are objects
        trades_by_conid = {}
        for t in trades:
            if t.conid not in trades_by_conid:
                trades_by_conid[t.conid] = []
            trades_by_conid[t.conid].append(t)

        open_positions = []
        for conid, group in trades_by_conid.items():
            # Sort by date
            group.sort(key=lambda x: x.date)
            
            qty, total_cost, first_date, multiplier = 0.0, 0.0, None, 1.0
            
            for t in group:
                side = t.side.strip().upper()
                q = abs(t.quantity)
                p = t.price
                m = float(t.multiplier)
                
                # Special handling for opening balance reset
                if 'OPENING_BALANCE' in t.source.upper():
                    qty, total_cost, first_date, multiplier = q, q * p * m, t.date, m
                    continue
                
                if side in ['BUY', 'TRANSFER_IN']:
                    # Reset point: if we were flat, this is a new inception
                    if qty <= 0.0001:
                        first_date = t.date
                        multiplier = m
                    total_cost += q * p * m
                    qty += q
                elif side in ['SELL', 'TRANSFER_OUT'] and qty > 0:
                    # Cost basis reduction (FIFO/WAC style)
                    total_cost -= q * (total_cost / qty)
                    qty -= q
                    # Reset point: if we hit zero, wipe history
                    if qty <= 0.0001:
                        qty, total_cost, first_date, multiplier = 0.0, 0.0, None, 1.0
                elif side == 'SPLIT':
                    # A split changes quantity but keeps total_cost the same.
                    qty += q
            
            if qty > 0.0001:
                latest = group[-1]
                open_positions.append(Position(
                    name=latest.description or latest.ticker,
                    ticker=latest.ticker,
                    conid=str(conid),
                    asset_class=latest.asset_category,
                    ccy=latest.currency,
                    date_entry=pd.to_datetime(first_date),
                    qty=qty,
                    multiplier=multiplier,
                    entry_price=total_cost / (qty * multiplier) if (qty * multiplier) != 0 else 0,
                    mark_price=0.0, # Will be filled by market data or snapshot
                    isin="", 
                    listing_exchange=latest.listing_exchange,
                    underlying_symbol=latest.underlying_symbol
                ))
        
        return open_positions
