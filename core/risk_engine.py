import pandas as pd
import numpy as np
import yfinance as yf
from rich.table import Table
from rich.console import Console
from models import Position

console = Console()

class RiskEngine:
    """
    Core engine for calculating risk metrics, Stop Losses, and Take Profits.
    """

    @staticmethod
    def calculate_position_risk(position: Position, risk_settings: dict):
        """
        Enriches a Position object with risk metrics based on provided settings.
        """
        if position.ticker in risk_settings:
            atr, s_type = risk_settings[position.ticker]
            
            # 1. Stop Loss Calculation (Trailing vs Fixed)
            anchor_price = position.max_since_entry if s_type == 'TRAILING' else position.entry_price
            position.sl_price = anchor_price - atr
            
            # 2. Take Profit (Standard 3x ATR from SL)
            position.tp_price = position.sl_price + (3 * atr)
            
            # 3. Percentage Metrics
            if position.current_price > 0:
                position.down_pct = ((position.current_price - position.sl_price) / position.current_price * 100)
                position.up_pct = ((position.tp_price - position.current_price) / position.current_price * 100)
            
            # 4. Value at Risk & Reward/Risk Ratio
            risk_per_unit = (position.current_price - position.sl_price)
            reward_per_unit = (position.tp_price - position.current_price)
            
            position.risk_val = risk_per_unit * position.qty * position.multiplier
            
            if risk_per_unit != 0:
                position.rr_ratio = reward_per_unit / risk_per_unit
            else:
                position.rr_ratio = 0.0
                
            position.atr_display = f"{atr:.2f} ({s_type[0]})"
        
        return position

def calculate_atr_metrics(ticker_symbol, entry_date_str, entry_price):
    """
    Legacy/Display helper: Calculates ATR across multiple timeframes for visual analysis.
    Uses the TickerMapper logic via PortfolioManager to resolve symbols.
    """
    from .portfolio_manager import PortfolioManager
    try:
        # 1. Resolve Ticker
        manager = PortfolioManager()
        yf_ticker = manager.mapper.resolve_yf_ticker(ticker_symbol)
        
        console.print(f"-> Resolved [bold]{ticker_symbol}[/bold] to Yahoo Ticker: [bold cyan]{yf_ticker}[/bold cyan]")

        # 2. Fetch History
        ticker_obj = yf.Ticker(yf_ticker)
        df = ticker_obj.history(period="3y")
        if df.empty:
            return f"[red]Error: No data found for {yf_ticker}[/red]"

        # 3. Calculate True Range (TR)
        df['PrevClose'] = df['Close'].shift(1)
        df['TR'] = np.maximum(df['High'] - df['Low'], 
                    np.maximum(abs(df['High'] - df['PrevClose']), 
                               abs(df['Low'] - df['PrevClose'])))

        # 4. Find Max Price since Entry Date
        entry_date = pd.to_datetime(entry_date_str)
        mask = df.index >= entry_date.tz_localize(df.index.tz) if df.index.tz else df.index >= entry_date
        df_since_entry = df.loc[mask]
        max_price = df_since_entry['High'].max() if not df_since_entry.empty else entry_price

        # 5. Define Timeframes
        intervals = [("21d", 21), ("12w", 60), ("6m", 126), ("8q", 504)]

        # 6. Build Table
        table = Table(title=f"ATR gauge for {ticker_symbol} (Entry {entry_price:,.2f}, Max {max_price:,.2f})", 
                      header_style="bold cyan", box=None)
        table.add_column("Label", style="bold")
        table.add_column("ATR", justify="right")
        table.add_column("Fixed SL", justify="right", style="green")
        table.add_column("Fixed %", justify="right", style="dim")
        table.add_column("Trail SL", justify="right", style="magenta")
        table.add_column("Trail %", justify="right", style="dim")

        for label, window in intervals:
            if len(df) < window: continue
            atr_sma = df['TR'].rolling(window=window).mean().iloc[-1]
            atr_ema = df['TR'].ewm(span=window, adjust=False).mean().iloc[-1]

            for method, val in [("SMA", atr_sma), ("EMA", atr_ema)]:
                table.add_row(
                    f"ATR_{label}_{method}",
                    f"{val:.2f}",
                    f"{entry_price - val:.2f}",
                    f"{(val/entry_price)*100:.2f}%",
                    f"{max_price - val:.2f}",
                    f"{(val/max_price)*100:.2f}%"
                )
            
        return table

    except Exception as e:
        return f"[red]Error calculating ATR: {e}[/red]"
