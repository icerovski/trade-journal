import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from constants import QTY_ZERO_THRESHOLD, AAGR_MIN_YEARS

@dataclass
class Trade:
    """Represents a single execution or broker-provided trade record."""
    date: str
    ticker: str
    side: str  # BUY / SELL
    quantity: float
    price: float
    conid: str
    account_id: str = "U0000000"
    multiplier: float = 1.0
    description: str = ""
    asset_category: str = "STK"
    listing_exchange: str = ""
    currency: str = "USD"
    underlying_symbol: str = ""
    isin: str = ""
    source: str = "UNKNOWN"
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
    qty: float = 0.0

@dataclass
class RiskProfile:
    """Represents a position's risk configuration from the database."""
    conid: str
    ticker: str
    atr_value: float
    stop_type: str
    id: Optional[int] = None
    stop_price: Optional[float] = None
    highest_sl: float = 0.0
    entry_type: str = "SINGLE"
    scale_step: float = 0.5
    max_r_pct: float = 1.0
    max_exp_pct: float = 5.0
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    inception_stop: Optional[float] = None
    inception_atr: Optional[float] = None
    status: str = "ACTIVE"

@dataclass
class Position:
    """Represents an aggregated holding derived from trade history."""
    name: str
    ticker: str
    conid: str
    asset_class: str
    ccy: str
    date_entry: Optional[datetime]
    qty: float
    entry_price: float
    inception_price: float = 0.0
    multiplier: float = 1.0
    mark_price: float = 0.0
    isin: str = ""
    listing_exchange: str = ""
    underlying_symbol: str = ""
    account_id: str = "U0000000"
    fx_rate: float = 1.0  # Rate to convert CCY to NAV Currency (e.g. USD -> EUR)
    
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
    scale_step: float = 0.5
    sl_price: Optional[float] = None
    inception_stop: Optional[float] = None
    inception_atr: Optional[float] = None
    tp_price: Optional[float] = None
    down_pct: float = 0.0
    up_pct: float = 0.0
    risk_val: float = 0.0
    reward_val: float = 0.0
    rr_ratio: float = 0.0
    sl_pct_base: float = 0.0
    risk_pct_nav: float = 0.0  # R (% of NAV)
    max_r_pct: float = 1.0
    max_exp_pct: float = 5.0

    # Exit Planning
    exit_stage: str = ""         # PRE-M1 / M1 / M2 / TP (empty = no stop assigned)
    m1_price: float = 0.0
    m2_price: float = 0.0
    trend_regime: str = "NORMAL"      # TREND / NORMAL / RANGING
    regime_ratio: float = 0.0        # quarterly_atr / weekly_atr (neutral baseline ≈ 3.5)
    regime_dma: str = ""             # e.g. "BUY (43d)" or "NEUTRAL (7d)"
    regime_weekly_atr: float = 0.0   # raw weekly ATR (Wilder 12-period)
    regime_quarterly_atr: float = 0.0 # raw quarterly ATR (Wilder 12-period)
    regime_dma200: float = 0.0       # current 200-DMA price level

    @property
    def hcm_value(self) -> float:
        """Higher of Cost Value (Entry) or Market Value (Current) for conservative exposure."""
        return max(self.entry_price, self.current_price) * self.qty * self.multiplier

    def reset(self):
        """Clears all position data (used when quantity hits zero)."""
        self.qty = 0.0
        self.entry_price = 0.0
        self.inception_price = 0.0
        self.date_entry = None

    def calculate_financial_metrics(self):
        """Calculates core P/L and growth metrics."""
        # Institutional Fallback: Use mark_price if current_price (YF) is unavailable
        effective_price = self.current_price if (self.current_price and self.current_price > 0) else self.mark_price
        
        self.market_value = effective_price * self.qty * self.multiplier
        self.unrealized_pl = (effective_price - self.entry_price) * self.qty * self.multiplier
        self.pl_pct = ((effective_price - self.entry_price) / self.entry_price * 100) if self.entry_price > 0 else 0
        
        # Daily performance (Compared to last close / mark_price from DB)
        self.daily_pl = (effective_price - self.mark_price) * self.qty * self.multiplier if self.mark_price > 0 else 0
        self.daily_pl_pct = ((effective_price - self.mark_price) / self.mark_price * 100) if self.mark_price > 0 else 0
        
        # Age & Growth
        today = pd.Timestamp.now()
        self.age_days = (today - self.date_entry).days if pd.notnull(self.date_entry) else 0
        years = max(self.age_days / 365.25, AAGR_MIN_YEARS)
        
        if self.entry_price > 0:
            growth_factor = effective_price / self.entry_price
            if growth_factor > 0:
                self.aagr = ((growth_factor ** (1 / years)) - 1) * 100
            else:
                self.aagr = -100.0
        else:
            self.aagr = 0.0

    # Maps Position field name → DataFrame column name consumed by the view layer.
    # Update this mapping when renaming a field; column names are part of the UI contract.
    _COLUMN_MAP = {
        'name': 'Name', 'ticker': 'Ticker', 'conid': 'conid',
        'account_id': 'account_id', 'date_entry': 'Date', 'qty': 'Qty',
        'multiplier': 'Multiplier', 'entry_price': 'Entry',
        'inception_price': 'Inception', 'market_value': 'MarketValue',
        'unrealized_pl': 'PL_Inc', 'pl_pct': 'PL_Inc_Pct',
        'daily_pl': 'PL_Daily', 'daily_pl_pct': 'PL_Daily_Pct',
        'aagr': 'AAGR', 'age_days': 'Age_Days', 'ccy': 'CCY',
        'asset_class': 'AssetClass', 'atr': 'ATR', 'inception_atr': 'InceptionATR',
        'stop_type': 'StopType', 'entry_type': 'EntryType', 'scale_step': 'ScaleStep',
        'max_r_pct': 'MaxRPct', 'max_exp_pct': 'MaxExpPct',
        'sl_price': 'SL_Price', 'tp_price': 'TP_Price',
        'down_pct': 'Down_Pct', 'up_pct': 'Up_Pct',
        'risk_val': 'Risk_Val', 'reward_val': 'Reward_Val', 'rr_ratio': 'RR_Ratio',
        'sl_pct_base': 'sl_pct_base', 'risk_pct_nav': 'risk_pct_nav',
        'max_since_entry': 'MaxSinceEntry', 'nav_pct': 'NavPct',
        'listing_exchange': 'ListingExchange',
        'underlying_symbol': 'UnderlyingSymbol', 'isin': 'ISIN',
        'fx_rate': 'FXRate',
        'exit_stage': 'ExitStage', 'm1_price': 'M1_Price',
        'm2_price': 'M2_Price', 'trend_regime': 'TrendRegime',
        'regime_ratio': 'RegimeRatio', 'regime_dma': 'RegimeDMA',
    }

    def to_dict(self):
        """Converts to a dictionary for DataFrame compatibility."""
        result = {col: getattr(self, field) for field, col in self._COLUMN_MAP.items()}
        # Computed and special-case fields not directly mapped from a single attribute
        result['Price'] = self.current_price or self.mark_price
        result['CostBasis'] = self.entry_price * self.qty * self.multiplier
        return result
