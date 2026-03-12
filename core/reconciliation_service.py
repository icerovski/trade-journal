import pandas as pd
from typing import List, Dict, Optional, Tuple
from models import Position, Trade

class ReconciliationService:
    """
    Handles the reconciliation between broker-verified snapshots and manual trades.
    Treats the broker snapshot as a 'Checkpoint' and manual trades/confirmations as a 'Delta'.
    """

    def reconcile_hybrid(
        self,
        broker_snapshot: Dict, 
        report_date: Optional[pd.Timestamp], 
        all_trades: List[Trade],
        ledger_engine
    ) -> List[Position]:
        """
        Merges broker-verified positions with pending delta trades (Manual + Confirmations).
        Returns a list of enriched Position objects.
        """
        # 1. Filter for trades occurring AFTER the report date
        pending_deltas = self._filter_pending_deltas(all_trades, report_date)

        # 2. Pre-calculate ledger positions for cost-basis recovery
        ledger_by_key, ledger_by_conid = self._prepare_ledger_lookups(all_trades, ledger_engine)

        open_list = []
        matched_keys = set()

        # 3. Process Broker Snapshot
        for key, v in broker_snapshot.items():
            pos = self._create_position_from_snapshot(key, v)
            
            # --- COST BASIS RECOVERY (HEALING) ---
            self._heal_from_ledger(pos, ledger_by_key, ledger_by_conid)

            # --- APPLY INTRADAY DELTAS ---
            self._apply_intraday_deltas(pos, pending_deltas)

            if pos.qty > 0.0001:
                # Final fallback for date if still missing
                if not pos.date_entry or pd.isna(pos.date_entry):
                    pos.date_entry = report_date
                open_list.append(pos)
                
            matched_keys.add(key)

        # 4. Add delta trades for assets NOT in IBKR snapshot
        remaining_deltas = [t for t in pending_deltas if f"{t.account_id}:{t.conid}" not in matched_keys]
        if remaining_deltas:
            open_list.extend(ledger_engine.calculate_positions(remaining_deltas))

        return open_list

    def _filter_pending_deltas(self, trades: List[Trade], report_date: Optional[pd.Timestamp]) -> List[Trade]:
        """Filters for trades that should be applied as deltas on top of the snapshot."""
        def is_pending(t):
            # Only IBKR confirmations are currently treated as pending deltas
            if t.source != 'IBKR_CONFIRMATION':
                return False
            if not report_date:
                return True
            return pd.to_datetime(t.date) > report_date
            
        return [t for t in trades if is_pending(t)]

    def _prepare_ledger_lookups(self, trades: List[Trade], engine) -> Tuple[Dict, Dict]:
        """Generates lookup maps for exact and fallback cost-basis recovery."""
        all_ledger_pos = engine.calculate_positions(trades)
        
        # Exact match map: Account:Conid
        by_key = {f"{p.account_id}:{p.conid}": p for p in all_ledger_pos}
        
        # Fallback map: Conid only (EARLIEST entry for true inception healing)
        by_conid = {}
        # Sort by date_entry ascending, but handle None by putting them at the end
        def sort_by_date(p):
            if p.date_entry and pd.notnull(p.date_entry):
                return p.date_entry
            return pd.Timestamp.max
            
        for p in sorted(all_ledger_pos, key=sort_by_date):
            c_str = str(p.conid)
            if c_str not in by_conid:
                by_conid[c_str] = p
            
        return by_key, by_conid

    def _create_position_from_snapshot(self, key: str, v: Dict) -> Position:
        """Initializes a Position object from a broker snapshot dictionary."""
        conid = str(v.get('conid', key.split(':')[-1]))
        return Position(
            name=v['Description'],
            ticker=v['Symbol'],
            conid=conid,
            account_id=v.get('account_id', 'U0000000'),
            listing_exchange=v['ListingExchange'],
            asset_class=v['AssetClass'],
            underlying_symbol=v['UnderlyingSymbol'],
            ccy=v['Currency'],
            isin=str(v.get('ISIN', '')),
            date_entry=pd.to_datetime(v['Date']) if v.get('Date') else None,
            qty=v['Qty'],
            entry_price=v['Entry'],
            inception_price=0.0,
            multiplier=v.get('Multiplier', 1.0),
            mark_price=v['MarkPrice']
        )

    def _heal_from_ledger(self, pos: Position, by_key: Dict, by_conid: Dict):
        """Attempts to recover missing metadata (entry date, cost basis) from the ledger."""
        key = f"{pos.account_id}:{pos.conid}"
        lp = by_key.get(key) or by_conid.get(pos.conid)
        
        if lp:
            if not pos.entry_price or pos.entry_price == 0:
                pos.entry_price = lp.entry_price
            if not pos.date_entry or pd.isna(pos.date_entry):
                pos.date_entry = lp.date_entry
            if not pos.multiplier or pos.multiplier == 1.0:
                pos.multiplier = lp.multiplier
            pos.inception_price = lp.inception_price

    def _apply_intraday_deltas(self, pos: Position, deltas: List[Trade]):
        """Applies relevant intraday trades to a position's quantity and cost basis."""
        adjustments = [t for t in deltas if str(t.conid) == pos.conid and t.account_id == pos.account_id]
        for t in adjustments:
            pos.apply_trade(
                side=t.side,
                q=t.quantity,
                p=t.price,
                m=t.multiplier,
                t_date=t.date
            )
