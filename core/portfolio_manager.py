import pandas as pd
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

    def get_dashboard_df(self, asset_class_filter: str | list[str] | None = None, total_nav: float | None = None, silent: bool = False, account_id: str | None = None, include_watch: bool = False):
        """
        Enriches open positions with market data and risk metrics.
        Uses Hybrid mode (Broker Snapshot + Manual Deltas).
        Returns (DataFrame, List[Position])
        """
        risk_settings = get_all_risk_settings()
        positions = self.get_open_positions_hybrid(asset_class_filter, account_id=account_id)
        
        # Merge Watch List if requested
        if include_watch and not account_id:
            positions.extend(self.get_watch_list_positions(asset_class_filter))
            
        if not positions:
            return pd.DataFrame(), []

        # 1. Metdata Healing & Rule Enrichment
        self._heal_inception_dates(positions, risk_settings)
        for p in positions:
            AssetRegistry.enrich_position_metadata(p)
        
        # 2. Batch Market Data Enrichment
        if not silent:
            logger.info(f"Fetching market data for {len(positions)} unique tickers...")
        enriched_positions = self.market_data.fetch_market_data(positions, self.mapper, silent=silent)
            
        # 3. Financial and Risk Metric Calculation
        self._enrich_metrics(enriched_positions, risk_settings, total_nav)

        # Convert list of objects back to DataFrame for the View layer
        return pd.DataFrame([p.to_dict() for p in enriched_positions]), enriched_positions

    def _heal_inception_dates(self, positions: list[Position], risk_settings: dict):
        """Force priority to Risk Profile Start Date for Inception if available."""
        for p in positions:
            conid_str = str(p.conid)
            if conid_str in risk_settings:
                # settings: (..., start_date) is at index 7
                s = risk_settings[conid_str]
                if len(s) >= 8 and s[7]:
                    profile_date = pd.to_datetime(s[7])
                    if pd.notnull(profile_date):
                        p.date_entry = profile_date

    def _enrich_metrics(self, positions: list[Position], risk_settings: dict, total_nav: float | None):
        """Calculates performance and risk metrics for all positions."""
        # Calculate financial metrics (P/L, AAGR, Age)
        for p in positions:
            p.calculate_financial_metrics()
            self.risk.calculate_position_risk(p, risk_settings)

        # Calculate NAV Exposure %
        total_mv = sum(p.market_value for p in positions)
        denominator = total_nav if (total_nav and total_nav > 0) else total_mv

        for p in positions:
            p.nav_pct = (p.hcm_value / denominator * 100) if denominator != 0 else 0
            
            # Calculate Risk-at-Stop (% of NAV)
            if p.entry_price > 0 and p.sl_price:
                risk_amt = (p.entry_price - p.sl_price) * p.qty * p.multiplier
                p.risk_pct_nav = (risk_amt / denominator) * 100 if denominator != 0 else 0
            else:
                p.risk_pct_nav = 0.0

    def get_open_positions_hybrid(self, asset_class_filter=None, account_id=None) -> list[Position]:
        """
        Hybrid Mode: Starts from IBKR Snapshot + pending MANUAL trades/transfers.
        Consolidates positions across accounts by default unless account_id is provided.
        """
        from db import promote_prospect_to_active
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

        # Consolidation Logic & Prospect Promotion
        if not account_id:
            consolidated = {}
            for p in open_list:
                # Bridge: Promote prospects if a real conid is now present
                promote_prospect_to_active(p.ticker, p.conid)
                
                c_id = str(p.conid) # Force string for robust mapping
                if c_id not in consolidated:
                    consolidated[c_id] = p
                else:
                    existing = consolidated[c_id]
                    old_qty = existing.qty
                    p_qty = p.qty
                    new_qty = old_qty + p_qty

                    if new_qty > 0.0001:
                        # Institutional Weighted Average Cost (WAC)
                        # total_cost = (Q1 * P1 * M1) + (Q2 * P2 * M2)
                        # entry_price = total_cost / (TotalQty * M_final)
                        total_cost = (existing.entry_price * old_qty * existing.multiplier) + \
                                     (p.entry_price * p_qty * p.multiplier)
                        
                        existing.qty = new_qty
                        existing.entry_price = total_cost / (new_qty * existing.multiplier)
                        
                        # Inception Priority: Use the earlier entry date/price
                        if p.date_entry and (not existing.date_entry or p.date_entry < existing.date_entry):
                            existing.date_entry = p.date_entry
                            existing.inception_price = p.inception_price
                    else:
                        existing.qty = 0.0
                        existing.entry_price = 0.0
                    
                    existing.account_id = "CONSOLIDATED"
            open_list = list(consolidated.values())

        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            open_list = [p for p in open_list if p.asset_class.upper() in filters]
            
        if account_id:
            open_list = [p for p in open_list if p.account_id == account_id]
            
        return open_list

    def get_watch_list_positions(self, asset_class_filter=None) -> list[Position]:
        """Returns phantom positions for assets on the Watch List."""
        from db import get_watch_list_profiles
        profiles = get_watch_list_profiles()
        watch_list = []
        for r in profiles:
            p = Position(
                name=f"WATCH: {r['ticker']}",
                ticker=r['ticker'],
                conid=r['conid'],
                asset_class='STK', # Discovery will correct this
                ccy='USD', 
                date_entry=pd.Timestamp.now(),
                qty=0.0, 
                entry_price=0.0,
                account_id='WATCHLIST'
            )
            # Pre-populate risk settings from DB
            p.atr = r['atr_value']
            p.stop_type = r['stop_type']
            p.entry_type = r['entry_type']
            p.scale_step = r['scale_step']
            p.max_r_pct = r['max_r_pct']
            watch_list.append(p)
            
        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            watch_list = [p for p in watch_list if p.asset_class.upper() in filters]
            
        return watch_list

    # --- Account / NAV Methods ---
    def fetch_nav_data(self, force_download=False):
        from config import IBKR_QUERY_ID_NAV, IBKR_NAV_CSV
        from services.ibkr import download_flex_report
        from services.ibkr_parser import IBKRParser
        
        file_path = download_flex_report(IBKR_QUERY_ID_NAV, IBKR_NAV_CSV, force_download=force_download)
        if not file_path:
            return 0.0, "???", [], "Unknown"
        
        return IBKRParser.parse_nav_csv(file_path)
