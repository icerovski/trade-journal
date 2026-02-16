import pandas as pd
import numpy as np
import yfinance as yf
from rich.table import Table
from rich.console import Console
from portfolio_manager import PortfolioManager

console = Console()

def calculate_atr_metrics(ticker_symbol, entry_date_str, entry_price):
    """
    Calculates ATR across multiple timeframes using ISIN resolution for Yahoo Finance.
    """
    try:
        # 1. Resolve Ticker using ISIN from open_positions.csv
        manager = PortfolioManager()
        yf_ticker = manager.resolve_yf_ticker(ticker_symbol)
        
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
