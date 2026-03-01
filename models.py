from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import pandas as pd

@dataclass
class Trade:
    """Represents a single execution or manual trade entry."""
    date: str
    ticker: str
    side: str  # BUY / SELL
    quantity: float
    price: float
    conid: str
    multiplier: float = 1.0
    description: str = ""
    asset_category: str = "STK"
    listing_exchange: str = ""
    currency: str = "USD"
    underlying_symbol: str = ""
    isin: str = ""
    source: str = "MANUAL"
    external_id: Optional[str] = None
    notes: str = ""

@dataclass
class ATRDiscoveryRow:
    """Represents a single row in the ATR analysis table."""
    label: str
    stop_type: str  # FIXED / TRAILING
    atr_wilder: float
    atr_sma: float
    stop_price: float
    atr_base_pct: float
    pl_at_stop: float
    buffer_pct: float
    pl_pct_nav: float

@dataclass
class Position:
    """Represents an aggregated holding derived from trade history."""
    name: str
    ticker: str
    conid: str
    asset_class: str
    ccy: str
    date_entry: datetime
    qty: float
    entry_price: float
    inception_price: float = 0.0
    multiplier: float = 1.0
    mark_price: float = 0.0
    isin: str = ""
    listing_exchange: str = ""
    underlying_symbol: str = ""
    
    # Market Data (Enriched later)
    current_price: float = 0.0
    max_since_entry: float = 0.0
    
    # Calculated Metrics
    market_value: float = 0.0
    unrealized_pl: float = 0.0
    pl_pct: float = 0.0
    daily_pl: float = 0.0
    daily_pl_pct: float = 0.0
    aagr: float = 0.0
    nav_pct: float = 0.0  # Exposure % of NAV
    age_days: int = 0
    
    # Risk Metrics
    atr: float = 0.0
    stop_type: str = "FIXED"
    entry_type: str = "SINGLE"
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    down_pct: float = 0.0
    up_pct: float = 0.0
    risk_val: float = 0.0
    reward_val: float = 0.0
    rr_ratio: float = 0.0
    sl_pct_base: float = 0.0
    risk_pct_nav: float = 0.0  # R (% of NAV)

    def to_dict(self):
        """Converts to a dictionary for DataFrame compatibility."""
        return {
            'Name': self.name,
            'Ticker': self.ticker,
            'conid': self.conid,
            'Date': self.date_entry,
            'Qty': self.qty,
            'Multiplier': self.multiplier,
            'Entry': self.entry_price,
            'Inception': self.inception_price,
            'Price': self.current_price or self.mark_price,
            'MarketValue': self.market_value,
            'CostBasis': self.entry_price * self.qty * self.multiplier,
            'PL_Inc': self.unrealized_pl,
            'PL_Inc_Pct': self.pl_pct,
            'PL_Daily': self.daily_pl,
            'PL_Daily_Pct': self.daily_pl_pct,
            'AAGR': self.aagr,
            'Age_Days': self.age_days,
            'CCY': self.ccy,
            'AssetClass': self.asset_class,
            'ATR': self.atr,
            'StopType': self.stop_type,
            'EntryType': self.entry_type,
            'SL_Price': self.sl_price,
            'TP_Price': self.tp_price,
            'Down_Pct': self.down_pct,
            'Up_Pct': self.up_pct,
            'Risk_Val': self.risk_val,
            'Reward_Val': self.reward_val,
            'RR_Ratio': self.rr_ratio,
            'sl_pct_base': self.sl_pct_base,
            'risk_pct_nav': self.risk_pct_nav,
            'MaxSinceEntry': self.max_since_entry,
            'NavPct': self.nav_pct,
            'ListingExchange': self.listing_exchange,
            'UnderlyingSymbol': self.underlying_symbol,
            'ISIN': self.isin
        }
