import pandas as pd
from typing import List, Dict, Tuple, Optional
from models import Position, Trade
from logger import logger

class ReconciliationService:
    """
    Handles the reconciliation between broker-verified snapshots and manual trades.
    Treats the broker snapshot as a 'Checkpoint' and manual trades as a 'Delta'.
    """

    @staticmethod
    def reconcile_hybrid(
        broker_snapshot: Dict, 
        report_date: Optional[pd.Timestamp], 
        all_trades: List[Trade],
        ledger_engine
    ) -> List[Position]:
        """
        Merges broker-verified positions with pending manual trades.
        """
        # 1. Filter for manual trades occurring AFTER the report date
        def is_pending_manual(t):
            t_date = pd.to_datetime(t.date)
            is_manual = t.source == 'MANUAL'
            if report_date:
                # Use a small buffer or same-day inclusion logic if needed
                return is_manual and t_date > report_date
            return is_manual

        pending_manual = [t for t in all_trades if is_pending_manual(t)]

        open_list = []
        matched_conids = set()

        # 2. Pre-calculate ledger positions for cost-basis recovery
        # (The broker snapshot often lacks the original entry date/multiplier)
        ledger_positions = {p.conid: p for p in ledger_engine.calculate_positions(all_trades)}

        # 3. Process Broker Snapshot
        for conid, v in broker_snapshot.items():
            ticker, qty, entry, first_date = v['Symbol'], v['Qty'], v['Entry'], v['Date']
            multiplier = v.get('Multiplier', 1.0)
            
            # Enrich with ledger history if available
            if conid in ledger_positions:
                lp = ledger_positions[conid]
                if not entry or entry == 0:
                    entry = lp.entry_price
                first_date = lp.date_entry
                multiplier = lp.multiplier

            # 4. Apply 'Delta' (Pending Manual Adjustments)
            adjustments = [t for t in pending_manual if t.conid == conid]
            for t in adjustments:
                side, q, p, m = t.side.upper(), t.quantity, t.price, t.multiplier
                if side in ['BUY', 'TRANSFER_IN']:
                    new_qty = qty + q
                    # WAC (Weighted Average Cost) adjustment
                    entry = ((qty * entry * multiplier) + (q * p * m)) / (new_qty * m) if (new_qty * m) != 0 else 0
                    qty = new_qty
                    multiplier = m
                    if not first_date: first_date = t.date
                elif side in ['SELL', 'TRANSFER_OUT']:
                    qty = max(0, qty - q)
                    if qty <= 0: 
                        qty, entry, first_date = 0, 0, None
                elif side == 'SPLIT':
                    qty += q

            if qty > 0.0001:
                open_list.append(Position(
                    name=v['Description'], ticker=ticker, conid=str(conid),
                    listing_exchange=v['ListingExchange'], asset_class=v['AssetClass'],
                    underlying_symbol=v['UnderlyingSymbol'], ccy=v['Currency'], isin=str(v.get('ISIN', '')),
                    date_entry=pd.to_datetime(first_date), qty=qty, entry_price=entry, 
                    multiplier=multiplier, mark_price=v['MarkPrice']
                ))
            matched_conids.add(str(conid))

        # 5. Add manual trades for assets NOT in IBKR snapshot
        remaining_manual = [t for t in pending_manual if t.conid not in matched_conids]
        if remaining_manual:
            open_list.extend(ledger_engine.calculate_positions(remaining_manual))

        return open_list
