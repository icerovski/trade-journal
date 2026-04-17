import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

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

    def apply_trade(self, side: str, q: float, p: float, m: float, t_date=None):
        """
        Updates the position based on a single trade.
        Implements Weighted Average Cost (WAC) and Reset-on-Zero.
        """
        side = side.upper()
        if side in ['BUY', 'TRANSFER_IN']:
            if self.qty <= 0.0001:
                self.date_entry = pd.to_datetime(t_date) if t_date else None
                self.inception_price = p
                self.multiplier = m
            
            new_qty = self.qty + q
            # WAC calculation
            if (new_qty * m) != 0:
                self.entry_price = ((self.qty * self.entry_price * self.multiplier) + (q * p * m)) / (new_qty * m)
            self.qty = new_qty
            self.multiplier = m
            
        elif side in ['SELL', 'TRANSFER_OUT']:
            self.qty = max(0, self.qty - q)
            if self.qty <= 0.0001:
                self.reset()
                
        elif side == 'SPLIT':
            # Split increases qty but keeps total cost basis the same
            self.qty += q

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
        years = max(self.age_days / 365.25, 0.04) # Floor at ~2 weeks for AAGR stability
        
        if self.entry_price > 0:
            growth_factor = effective_price / self.entry_price
            if growth_factor > 0:
                self.aagr = ((growth_factor ** (1 / years)) - 1) * 100
            else:
                self.aagr = -100.0
        else:
            self.aagr = 0.0

    def to_dict(self):
        """Converts to a dictionary for DataFrame compatibility."""
        return {
            'Name': self.name,
            'Ticker': self.ticker,
            'conid': self.conid,
            'account_id': self.account_id,
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
            'InceptionATR': self.inception_atr,
            'StopType': self.stop_type,
            'EntryType': self.entry_type,
            'ScaleStep': self.scale_step,
            'MaxRPct': self.max_r_pct,
            'MaxExpPct': self.max_exp_pct,
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
