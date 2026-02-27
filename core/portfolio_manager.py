import pandas as pd
import numpy as np
import yfinance as yf
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from data_loader import DataLoader
from services.ticker_mapper import TickerMapper
from .ledger_engine import LedgerEngine
from services.market_data_service import MarketDataService
from .risk_engine import RiskEngine
from .asset_registry import AssetRegistry
from .reconciliation_service import ReconciliationService
from db import get_all_risk_settings
from models import Position
from logger import logger, log_system_milestone

# Log the recent architectural improvements
log_system_milestone("Migrated to Batch Market Data Fetching via yfinance (Phase 2 Refactor)")
log_system_milestone("Formalized 'Position' and 'Trade' models using Dataclasses")

class PortfolioManager:
    """
    Core engine for calculating portfolio metrics and risk.
    """
    
    def __init__(self, loader=None, mapper=None, ledger=None, market_data=None, risk=None, recon=None):
        self._loader = loader
        self._mapper = mapper
        self._ledger = ledger
        self._market_data = market_data
        self._risk = risk
        self._recon = recon

    @property
    def loader(self):
        return self._loader or DataLoader()

    @property
    def mapper(self):
        return self._mapper or TickerMapper()

    @property
    def ledger(self):
        return self._ledger or LedgerEngine()

    @property
    def market_data(self):
        return self._market_data or MarketDataService()

    @property
    def risk(self):
        return self._risk or RiskEngine()

    @property
    def recon(self):
        return self._recon or ReconciliationService()

    def get_dashboard_df(self, asset_class_filter=None, total_nav=None, silent=False):
        """
        Enriches open positions with market data and risk metrics.
        Uses Hybrid mode (Broker Snapshot + Manual Deltas).
        """
        risk_settings = get_all_risk_settings()
        positions = self.get_open_positions_hybrid(asset_class_filter)
            
        if not positions: return pd.DataFrame()

        # Fix Multipliers and apply Asset-Specific metadata rules
        for p in positions:
            AssetRegistry.enrich_position_metadata(p)
        
        # Batch Market Data Enrichment
        if not silent:
            logger.info(f"Fetching market data for {len(positions)} unique tickers...")
        enriched_positions = self.market_data.fetch_market_data(positions, self.mapper, silent=silent)
            
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
            
            # Risk Metrics (Delegated to RiskEngine)
            self.risk.calculate_position_risk(p, risk_settings)

        # Final pass for NAV %
        total_mv = sum(p.market_value for p in enriched_positions)
        denominator = total_nav if (total_nav and total_nav > 0) else total_mv
        for p in enriched_positions:
            p.nav_pct = (p.market_value / denominator) * 100
            # Calculate R (% of NAV)
            if p.entry_price > 0 and p.sl_price:
                risk_amt = (p.entry_price - p.sl_price) * p.qty * p.multiplier
                p.risk_pct_nav = (risk_amt / denominator) * 100
            else:
                p.risk_pct_nav = 0.0

        # Convert list of objects back to DataFrame for the View layer
        return pd.DataFrame([p.to_dict() for p in enriched_positions])

    def get_open_positions_hybrid(self, asset_class_filter=None) -> list[Position]:
        """
        Hybrid Mode: Starts from IBKR Snapshot + pending MANUAL trades/transfers.
        """
        broker_snapshot, report_date = self.loader.get_broker_verified_snapshot()
        all_trades = self.loader.get_trades_as_models()
        
        open_list = self.recon.reconcile_hybrid(
            broker_snapshot, 
            report_date, 
            all_trades, 
            self.ledger
        )

        if not open_list:
            logger.warning("No open positions found in Hybrid mode.")

        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            open_list = [p for p in open_list if p.asset_class.upper() in filters]
            
        return open_list

    # --- Account / NAV Methods ---
    def fetch_nav_data(self, force_download=False):
        from config import IBKR_QUERY_ID_NAV, IBKR_NAV_CSV
        from services.ibkr import download_flex_report
        from services.ibkr_parser import IBKRParser
        
        file_path = download_flex_report(IBKR_QUERY_ID_NAV, IBKR_NAV_CSV, force_download=force_download)
        if not file_path: return None
        
        return IBKRParser.parse_nav_csv(file_path)
