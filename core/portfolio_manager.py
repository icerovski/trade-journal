import math
import time

import pandas as pd
from data_loader import DataLoader
from services.ticker_mapper import TickerMapper
from .ledger_engine import LedgerEngine
from services.market_data_service import MarketDataService
from .profit_taking import enrich_regime
from .asset_registry import AssetRegistry
from .reconciliation_service import ReconciliationService
from db import get_all_risk_settings, reset_inception_on_reopen, get_setting
from .stop_loss import calculate_position_risk
from models import Position
from logger import logger
from constants import QTY_ZERO_THRESHOLD


# Minor-unit price currencies (Yahoo quotes these in 1/100 of the major unit):
# the ccy->NAV rate for a pence-priced instrument is 0.01 x the major-unit rate.
_MINOR_UNIT_CCY = {"GBp": ("GBP", 0.01), "GBX": ("GBP", 0.01), "ZAc": ("ZAR", 0.01)}

# Session cache for live FX lookups so a donor-less watch name doesn't re-hit
# Yahoo on every dashboard refresh. Failures are not cached.
_FX_CACHE: dict[tuple[str, str], tuple[float, float]] = {}
_FX_CACHE_TTL_S = 900.0


def resolve_prospect_fx(ccy: str, positions, nav_ccy: str | None = None) -> float:
    """Asset-ccy -> NAV-ccy rate for a prospect that has no broker-snapshot row.

    Prefer the snapshot rate carried by a held position in the same currency
    (first match — deterministic, no network); else ask the FX service when the
    NAV currency is known (cached ~15min); else fall back FX-blind, logged.
    Minor-unit codes ('GBp' pence, 'ZAc' cents) resolve via their major unit
    scaled by 0.01 — prices arrive in the minor unit, so the rate must too.
    Single source of truth for prospect fx: the risk-workspace discover flow and
    the watch-list stamping in get_dashboard_df both call this.
    """
    raw = (ccy or "").strip()
    major, scale = _MINOR_UNIT_CCY.get(raw, (raw, 1.0))
    ccy = major.upper()

    for p in positions:
        if p.ccy == ccy and p.fx_rate and math.isfinite(p.fx_rate) and p.fx_rate > 0 and p.fx_rate != 1.0:
            return p.fx_rate * scale
    # Only consult the FX service with a plausible ISO code — a failed NAV fetch
    # hands callers "???", which must not turn into a bogus Yahoo symbol.
    if nav_ccy and len(nav_ccy) == 3 and nav_ccy.isalpha() and ccy.isalpha() and len(ccy) == 3:
        nav_ccy = nav_ccy.upper()
        if ccy == nav_ccy:
            return 1.0 * scale
        cached = _FX_CACHE.get((ccy, nav_ccy))
        if cached and (time.monotonic() - cached[1]) < _FX_CACHE_TTL_S:
            return cached[0] * scale
        from services.market_data_service import fetch_fx_rate
        rate = fetch_fx_rate(ccy, nav_ccy)
        if rate and math.isfinite(rate) and rate > 0:
            _FX_CACHE[(ccy, nav_ccy)] = (float(rate), time.monotonic())
            return float(rate) * scale
        logger.warning(f"FX: no {ccy}->{nav_ccy} rate available; prospect sizing stays FX-blind for this name.")
    # Blind fallback: at least honour the minor-unit scale (pence != pounds).
    return 1.0 * scale


class PortfolioManager:
    """
    Core engine for calculating portfolio metrics and risk.
    """
    
    def __init__(self, loader=None, mapper=None, ledger=None, market_data=None, recon=None):
        self._loader = loader
        self._mapper = mapper
        self._ledger = ledger
        self._market_data = market_data
        self._recon = recon

    @property
    def loader(self):
        if self._loader is None:
            self._loader = DataLoader()
        return self._loader

    @property
    def mapper(self):
        if self._mapper is None:
            self._mapper = TickerMapper()
        return self._mapper

    @property
    def ledger(self):
        if self._ledger is None:
            self._ledger = LedgerEngine()
        return self._ledger

    @property
    def market_data(self):
        if self._market_data is None:
            self._market_data = MarketDataService()
        return self._market_data

    @property
    def recon(self):
        if self._recon is None:
            self._recon = ReconciliationService()
        return self._recon

    def get_dashboard_df(self, asset_class_filter: str | list[str] | None = None, total_nav: float | None = None, silent: bool = False, account_id: str | None = None, include_watch: bool = False, nav_ccy: str | None = None):
        """
        Enriches open positions with market data and risk metrics.
        Uses Hybrid mode (Broker Snapshot + Manual Deltas).
        Returns (DataFrame, List[Position])
        """
        risk_settings = get_all_risk_settings()
        positions = self.get_open_positions_hybrid(asset_class_filter, account_id=account_id)
        
        # Merge Watch List if requested
        if include_watch and not account_id:
            watch = self.get_watch_list_positions(asset_class_filter)
            # Watch phantoms never appear in the broker snapshot, so their fx_rate
            # is the dataclass default (1.0). Resolve each phantom's ccy -> NAV rate
            # (held-book borrow first, live FX fallback when nav_ccy is known) so
            # prospect sizing risks the real base-ccy budget.
            fx_cache: dict[str, float] = {}
            for p in watch:
                if not p.fx_rate or p.fx_rate == 1.0:
                    if p.ccy not in fx_cache:
                        fx_cache[p.ccy] = resolve_prospect_fx(p.ccy, positions, nav_ccy)
                    p.fx_rate = fx_cache[p.ccy]
            positions.extend(watch)
            
        if not positions:
            return pd.DataFrame(), []

        # 1. Metadata Healing & Rule Enrichment
        self._heal_inception_dates(positions, risk_settings)
        self._enrich_asset_metadata(positions)
        
        # 2. Batch Market Data Enrichment
        if not silent:
            logger.info(f"Fetching market data for {len(positions)} unique tickers...")
        enriched_positions = self.market_data.fetch_market_data(positions, self.mapper, silent=silent)
            
        # 3. Financial and Risk Metric Calculation
        self._enrich_metrics(enriched_positions, risk_settings, total_nav)

        # 4. Trend Regime (200-DMA consecutive rising days; opt-in horizon lens
        # matches the DMA to each stop's volatility horizon — default unchanged)
        lens_mode = (get_setting('regime_lens', 'default') or 'default').strip().lower()
        enrich_regime(enriched_positions, self.mapper, lens_mode=lens_mode)

        # Convert list of objects back to DataFrame for the View layer
        return pd.DataFrame([p.to_dict() for p in enriched_positions]), enriched_positions

    def _enrich_asset_metadata(self, positions: list[Position]):
        """Applies asset-registry rules (multipliers, asset class corrections) to each position."""
        for p in positions:
            AssetRegistry.enrich_position_metadata(p)

    def _heal_inception_dates(self, positions: list[Position], risk_settings: dict):
        """Prefer the Risk Profile start date for inception — but never let it predate the
        current ledger lot. A position that went flat and reopened (reset-on-zero) carries a
        stale profile start_date from the PRIOR lot; forcing it would backdate the position,
        dragging an old price peak into the high-water mark and fabricating a stop breach
        (e.g. AGQ/UGL: profile 2026-02-23 vs ledger reopening 2026-06-15). The reset-on-zero
        ledger date is authoritative in that case."""
        for p in positions:
            conid_str = str(p.conid)
            if conid_str in risk_settings:
                profile = risk_settings[conid_str]
                if profile.start_date:
                    profile_date = pd.to_datetime(profile.start_date)
                    if pd.notnull(profile_date):
                        if p.date_entry and pd.notnull(p.date_entry) and profile_date < p.date_entry:
                            # The current ledger lot is newer than the profile: the position
                            # went flat (reset-on-zero) and reopened, so the profile's ratchet
                            # and frozen inception belong to the CLOSED lot. Reset them (DB +
                            # in-memory) and re-anchor to the new lot; the ledger date wins.
                            new_date = p.date_entry.strftime('%Y-%m-%d')
                            reset_inception_on_reopen(p.conid, new_date)
                            profile.highest_sl = 0.0
                            profile.inception_stop = None
                            profile.inception_atr = None
                            profile.start_date = new_date
                            continue
                        p.date_entry = profile_date

    def _enrich_metrics(self, positions: list[Position], risk_settings: dict, total_nav: float | None):
        """Calculates performance and risk metrics for all positions."""
        # Calculate financial metrics (P/L, AAGR, Age)
        for p in positions:
            p.calculate_financial_metrics()
            calculate_position_risk(p, risk_settings)

        # Calculate NAV Exposure %
        total_mv = sum(p.market_value * p.fx_rate for p in positions)
        denominator = total_nav if (total_nav and total_nav > 0) else total_mv

        for p in positions:
            # HCM Exposure (Normalized to NAV Currency)
            p.nav_pct = (p.hcm_value * p.fx_rate / denominator * 100) if denominator != 0 else 0
            
            # Risk-at-Stop (Normalized to NAV Currency)
            if p.entry_price > 0 and p.sl_price:
                risk_amt = (p.entry_price - p.sl_price) * p.qty * p.multiplier
                p.risk_pct_nav = (risk_amt * p.fx_rate / denominator) * 100 if denominator != 0 else 0
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
            open_list = self._consolidate_positions(open_list)

        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            open_list = [p for p in open_list if p.asset_class.upper() in filters]
            
        if account_id:
            open_list = [p for p in open_list if p.account_id == account_id]

        return open_list

    def _consolidate_positions(self, open_list: list[Position]) -> list[Position]:
        """Merges positions sharing the same conid across accounts using WAC."""
        from db import promote_prospect_to_active
        consolidated = {}
        for p in open_list:
            promote_prospect_to_active(p.ticker, p.conid)
            c_id = str(p.conid)
            if c_id not in consolidated:
                consolidated[c_id] = p
            else:
                existing = consolidated[c_id]
                old_qty = existing.qty
                p_qty = p.qty
                new_qty = old_qty + p_qty

                if new_qty > QTY_ZERO_THRESHOLD:
                    total_cost = (existing.entry_price * old_qty * existing.multiplier) + \
                                 (p.entry_price * p_qty * p.multiplier)
                    existing.qty = new_qty
                    existing.entry_price = total_cost / (new_qty * existing.multiplier)
                    if p.date_entry and (not existing.date_entry or p.date_entry < existing.date_entry):
                        existing.date_entry = p.date_entry
                        existing.inception_price = p.inception_price
                else:
                    existing.qty = 0.0
                    existing.entry_price = 0.0

                existing.account_id = "CONSOLIDATED"
        return list(consolidated.values())

    def get_watch_list_positions(self, asset_class_filter=None) -> list[Position]:
        """Returns phantom positions for assets on the Watch List."""
        from db import get_watch_list_profiles
        profiles = get_watch_list_profiles()
        watch_list = []
        for r in profiles:
            p = Position(
                name=f"WATCH: {r.ticker}",
                ticker=r.ticker,
                conid=r.conid,
                asset_class='STK',
                # Real pricing ccy resolved at add time (risk_profiles.ccy); legacy
                # rows predate the column and keep the historical USD assumption.
                ccy=(r.ccy or 'USD'),
                date_entry=pd.Timestamp.now(),
                qty=0.0,
                entry_price=0.0,
                account_id='WATCHLIST'
            )
            p.atr = r.atr_value
            p.stop_type = r.stop_type
            p.entry_type = r.entry_type
            p.scale_step = r.scale_step
            p.max_r_pct = r.max_r_pct
            p.max_exp_pct = r.max_exp_pct
            p.inception_stop = r.inception_stop
            p.inception_atr = r.inception_atr
            p.profile = r.profile
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
