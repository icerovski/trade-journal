import pandas as pd
import numpy as np
import yfinance as yf
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from data_loader import DataLoader
from ticker_mapper import TickerMapper
from db import get_all_risk_settings
from models import Position
from logger import logger, log_system_milestone

# Log the recent improvements
log_system_milestone("Implemented parallel market data fetching via ThreadPoolExecutor")
log_system_milestone("Formalized 'Position' and 'Trade' models using Dataclasses")

class PortfolioManager:
    """
    Core engine for calculating portfolio metrics and risk.
    """
    
    def __init__(self, loader=None, mapper=None):
        self._loader = loader
        self._mapper = mapper

    @property
    def loader(self):
        return self._loader or DataLoader()

    @property
    def mapper(self):
        return self._mapper or TickerMapper()

    def _fetch_single_market_data(self, position: Position):
        """Helper to fetch price and max high for a single position object."""
        yf_ticker = self.mapper.resolve_yf_ticker(position.ticker, position.isin)
        
        if yf_ticker:
            try:
                data = yf.Ticker(yf_ticker)
                # fast_info is very quick but sometimes missing
                price = data.fast_info.get('last_price', np.nan)
                
                if np.isnan(price):
                    hist = data.history(period="1d")
                    if not hist.empty:
                        price = hist['Close'].iloc[-1]
                
                # Fetch history for trailing stop (Max High)
                full_hist = data.history(start=position.date_entry)
                if not full_hist.empty:
                    max_p = full_hist['High'].max()
                else:
                    max_p = price
                
                position.current_price = price
                position.max_since_entry = max_p
            except Exception as e:
                logger.warning(f"Failed to fetch market data for {yf_ticker}: {e}")
        
        # Fallbacks if YF fails
        if not position.current_price or np.isnan(position.current_price):
            position.current_price = position.mark_price
        if not position.max_since_entry or np.isnan(position.max_since_entry):
            position.max_since_entry = position.current_price
            
        return position

    def calculate_positions(self, trades_df) -> list[Position]:
        """
        Unified engine for "Reset-on-Zero" ledger replay.
        Expects a cleaned DataFrame of trades.
        Returns a list of Position objects.
        """
        if trades_df.empty:
            return []
            
        open_positions = []
        for conid, group in trades_df.groupby('Conid'):
            # Copy to avoid SettingWithCopyWarning
            group = group.copy().sort_values('TradeDate')
            
            qty, total_cost, first_date, multiplier = 0.0, 0.0, None, 1.0
            
            for _, row in group.iterrows():
                side = str(row['Buy/Sell']).strip().upper()
                q = abs(row['Quantity'])
                p = row['Price']
                m = float(row.get('Multiplier', 1.0))
                
                # Special handling for opening balance reset
                if 'OPENING_BALANCE' in str(row.get('source', '')).upper():
                    qty, total_cost, first_date, multiplier = q, q * p * m, row['TradeDate'], m
                    continue
                
                if side == 'BUY':
                    if qty <= 0.0001:
                        first_date = row['TradeDate']
                        multiplier = m # Set multiplier on first buy
                    total_cost += q * p * m
                    qty += q
                elif side == 'SELL' and qty > 0:
                    # Cost basis reduction (FIFO/WAC style)
                    total_cost -= q * (total_cost / qty)
                    qty -= q
                    
                    # RESET ON ZERO logic
                    if qty <= 0.0001:
                        qty, total_cost, first_date, multiplier = 0.0, 0.0, None, 1.0
            
            if qty > 0.0001:
                latest = group.iloc[-1]
                open_positions.append(Position(
                    name=latest.get('Description', latest['Symbol']),
                    ticker=latest['Symbol'],
                    conid=str(conid),
                    asset_class=latest.get('AssetClass', 'STK'),
                    ccy=latest.get('CurrencyPrimary', 'USD'),
                    date_entry=pd.to_datetime(first_date),
                    qty=qty,
                    multiplier=multiplier,
                    entry_price=total_cost / (qty * multiplier) if (qty * multiplier) != 0 else 0,
                    mark_price=latest.get('Price', 0.0),
                    isin=str(latest.get('ISIN', '')),
                    listing_exchange=latest.get('ListingExchange', ''),
                    underlying_symbol=latest.get('UnderlyingSymbol', '')
                ))
        return open_positions

    def get_open_positions_hybrid(self, asset_class_filter=None) -> list[Position]:
        """
        Hybrid Mode: Starts from IBKR Snapshot + pending MANUAL trades.
        """
        broker_verified, report_date = self.loader.get_broker_verified_snapshot()
        all_trades = self.loader.load_trades_from_db()
        
        # Filter for manual trades occurring AFTER the report date
        pending_manual = all_trades[
            (all_trades['source'] == 'MANUAL') & 
            (all_trades['TradeDate'] > report_date)
        ] if report_date else all_trades[all_trades['source'] == 'MANUAL']

        open_list = []
        matched_conids = set()

        # 1. Start with Broker Verified
        ledger_positions = {p.conid: p for p in self.calculate_positions(all_trades)}

        for conid, v in broker_verified.items():
            ticker, qty, entry, first_date = v['Symbol'], v['Qty'], v['Entry'], v['Date']
            multiplier = v.get('Multiplier', 1.0)
            
            # Smart Fallback: 
            # Prefer Ledger for both Entry Price and Entry Date if available, 
            # as the Ledger contains the complete historical record.
            if conid in ledger_positions:
                lp = ledger_positions[conid]
                # Fallback entry price if broker returns 0
                if not entry or entry == 0:
                    entry = lp.entry_price
                    logger.info(f"Using Ledger fallback for {ticker} cost basis: {entry:,.2f}")
                
                # ALWAYS prefer Ledger for Entry Date to avoid "Report Date" (today) from snapshot
                first_date = lp.date_entry
                multiplier = lp.multiplier # Prefer ledger multiplier
                logger.debug(f"Using Ledger entry date for {ticker}: {first_date}")

            # Apply any pending manual adjustments
            adjustments = pending_manual[pending_manual['Conid'] == conid]
            for _, row in adjustments.iterrows():
                side, q, p, m = row['Buy/Sell'], row['Quantity'], row['Price'], row.get('Multiplier', 1.0)
                if side == 'BUY':
                    new_qty = qty + q
                    # entry_price = total_cost / (qty * multiplier)
                    # new_total_cost = (qty * entry * multiplier) + (q * p * m)
                    entry = ((qty * entry * multiplier) + (q * p * m)) / (new_qty * m) if (new_qty * m) != 0 else 0
                    qty = new_qty
                    multiplier = m
                    if not first_date: first_date = row['TradeDate']
                else:
                    qty = max(0, qty - q)
                    if qty <= 0: qty, entry, first_date = 0, 0, None

            if qty > 0.0001:
                open_list.append(Position(
                    name=v['Description'], ticker=ticker, conid=str(conid),
                    listing_exchange=v['ListingExchange'], asset_class=v['AssetClass'],
                    underlying_symbol=v['UnderlyingSymbol'], ccy=v['Currency'], isin=str(v.get('ISIN', '')),
                    date_entry=pd.to_datetime(first_date), qty=qty, entry_price=entry, 
                    multiplier=multiplier, mark_price=v['MarkPrice']
                ))
            matched_conids.add(str(conid))

        # 2. Add manual trades for assets NOT in IBKR snapshot
        remaining_manual = pending_manual[~pending_manual['Conid'].astype(str).isin(matched_conids)]
        if not remaining_manual.empty:
            open_list.extend(self.calculate_positions(remaining_manual))

        if not open_list:
            logger.warning("No open positions found in Hybrid mode.")

        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            open_list = [p for p in open_list if p.asset_class.upper() in filters]
            
        return open_list

    def get_open_positions_ledger(self, asset_class_filter=None) -> list[Position]:
        """
        Ledger Mode: Full database replay.
        """
        all_trades = self.loader.load_trades_from_db()
        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            all_trades = all_trades[all_trades['AssetClass'].isin(filters)]
            
        return self.calculate_positions(all_trades)

    def get_dashboard_df(self, asset_class_filter=None, total_nav=None, use_ledger=False):
        """
        Enriches open positions with market data and risk metrics.
        Uses parallel fetching for price updates.
        """
        risk_settings = get_all_risk_settings()
        
        if use_ledger:
            positions = self.get_open_positions_ledger(asset_class_filter)
        else:
            positions = self.get_open_positions_hybrid(asset_class_filter)
            
        if not positions: return pd.DataFrame()

        # Fix Multipliers for Bonds before calculations
        for p in positions:
            # HEURISTIC: IBKR often reports multiplier 1 for Bonds, but they are priced 
            # in % of par (usually $1000). So multiplier should be 10.
            if p.asset_class == 'BOND' and p.multiplier == 1.0:
                p.multiplier = 10.0
                logger.info(f"Applied Bond Multiplier Correction (1.0 -> 10.0) for {p.ticker}")
        
        # Parallel Market Data Enrichment
        logger.info(f"Fetching market data for {len(positions)} positions in parallel...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            enriched_positions = list(executor.map(self._fetch_single_market_data, positions))
            
        # Calculate Metrics for each position
        today = pd.Timestamp.now()
        for p in enriched_positions:
            # Basic financial math (Since Inception)
            p.market_value = p.current_price * p.qty * p.multiplier
            p.unrealized_pl = (p.current_price - p.entry_price) * p.qty * p.multiplier
            p.pl_pct = ((p.current_price - p.entry_price) / p.entry_price * 100) if p.entry_price > 0 else 0
            
            # Daily performance (Compared to last close / mark_price from DB)
            p.daily_pl = (p.current_price - p.mark_price) * p.qty * p.multiplier if p.mark_price > 0 else 0
            p.daily_pl_pct = ((p.current_price - p.mark_price) / p.mark_price * 100) if p.mark_price > 0 else 0
            
            # Age & Growth
            p.age_days = (today - p.date_entry).days
            years = max(p.age_days / 365.25, 0.04)
            p.aagr = (((p.current_price / p.entry_price) ** (1 / years)) - 1) * 100 if p.entry_price > 0 else 0
            
            # Risk
            if p.ticker in risk_settings:
                atr, s_type = risk_settings[p.ticker]
                p.sl_price = (p.max_since_entry if s_type == 'TRAILING' else p.entry_price) - atr
                p.tp_price = p.sl_price + (3 * atr)
                
                p.down_pct = ((p.current_price - p.sl_price) / p.current_price * 100) if p.current_price > 0 else 0
                p.up_pct = ((p.tp_price - p.current_price) / p.current_price * 100) if p.current_price > 0 else 0
                p.risk_val = (p.current_price - p.sl_price) * p.qty * p.multiplier
                p.rr_ratio = (p.tp_price - p.current_price) / (p.current_price - p.sl_price) if (p.current_price - p.sl_price) != 0 else 0
                p.atr_display = f"{atr:.2f} ({s_type[0]})"

        # Final pass for NAV %
        total_mv = sum(p.market_value for p in enriched_positions)
        denominator = total_nav if (total_nav and total_nav > 0) else total_mv
        for p in enriched_positions:
            p.nav_pct = (p.market_value / denominator) * 100

        # Convert list of objects back to DataFrame for the View layer
        return pd.DataFrame([p.to_dict() for p in enriched_positions])

    # --- Account / NAV Methods ---
    def fetch_nav_data(self, force_download=False):
        from config import IBKR_QUERY_ID_NAV, IBKR_NAV_CSV
        from ibkr import download_flex_report
        from ibkr_parser import IBKRParser
        
        file_path = download_flex_report(IBKR_QUERY_ID_NAV, IBKR_NAV_CSV, force_download=force_download)
        if not file_path: return None
        
        return IBKRParser.parse_nav_csv(file_path)
