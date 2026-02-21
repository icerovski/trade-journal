import pandas as pd
import numpy as np
import yfinance as yf
from rich.table import Table
from rich.console import Console
from rich import box
from models import Position
from db import update_high_water_mark
from services.price_service import PriceService

console = Console()

class RiskEngine:
    """
    Core engine for calculating risk metrics, Stop Losses, and Take Profits.
    """

    @staticmethod
    def calculate_position_risk(position: Position, risk_settings: dict):
        """
        Enriches a Position object with risk metrics based on provided settings.
        Implements the 'Ratchet' rule: Stop Loss only moves in the trader's favor.
        """
        if position.ticker in risk_settings:
            atr, s_type, highest_sl = risk_settings[position.ticker]
            
            # 1. Base Stop Loss Calculation
            # Stop Base is Entry Price (Fixed) or Max Price Since Entry (Trailing)
            stop_base = position.max_since_entry if s_type == 'TRAILING' else position.entry_price
            calculated_sl = stop_base - atr
            
            # Populate raw fields for easier dashboard access
            position.atr = atr
            position.stop_type = s_type
            
            # 2. Ratchet Rule (High-Water Mark)
            final_sl = max(calculated_sl, highest_sl)
            
            # Update high-water mark in DB if we reached a new high
            if final_sl > highest_sl:
                update_high_water_mark(position.ticker, final_sl)
            
            position.sl_price = final_sl
            
            # 3. Take Profit (Standard 3x ATR from SL)
            position.tp_price = position.sl_price + (3 * atr)
            
            # 4. Percentage Metrics
            if position.current_price > 0:
                position.down_pct = ((position.current_price - position.sl_price) / position.current_price * 100)
                position.up_pct = ((position.tp_price - position.current_price) / position.current_price * 100)
            
            # 5. Outcome at Stop/Target (Total P/L relative to Entry)
            position.risk_val = (position.sl_price - position.entry_price) * position.qty * position.multiplier
            position.reward_val = (position.tp_price - position.entry_price) * position.qty * position.multiplier
            
            # 6. Current Efficiency (Remaining Reward / Current Risk)
            dist_to_stop = (position.current_price - position.sl_price)
            dist_to_target = (position.tp_price - position.current_price)
            
            if dist_to_stop != 0:
                position.rr_ratio = dist_to_target / dist_to_stop
            else:
                position.rr_ratio = 0.0
            
            # ATR as % of Stop Base
            atr_base_pct = (atr / stop_base * 100) if stop_base > 0 else 0
            position.atr_display = f"{s_type}|{atr:.2f}|{atr_base_pct:.1f}%"
        
        return position

def calculate_atr_metrics(ticker_symbol, entry_date_str, entry_price, multiplier=1.0, conid=None):
    """
    Calculates ATR across multiple timeframes for visual analysis.
    Supports frequency scaling and optional multiplier for noise buffering.
    Returns (Rich.Table, dict of {label: value})
    """
    from .portfolio_manager import PortfolioManager
    try:
        # 1. Resolve Ticker
        manager = PortfolioManager()
        yf_ticker = manager.mapper.resolve_yf_ticker(ticker_symbol)
        
        # 2. Fetch History from Local DB (Fallback to Yahoo via fetch_and_store)
        price_service = PriceService()
        
        # If conid is not provided, we try to get it from mapper (if possible)
        # However, it's safer to have conid from the position
        if not conid:
            # Fallback for manual ATR calculation without conid
            # Just use Yahoo directly (no local caching) or try to find conid
            console.print(f"-> [yellow]Warning:[/yellow] No conid provided for {ticker_symbol}. Using direct Yahoo fetch.")
            ticker_obj = yf.Ticker(yf_ticker)
            df_daily = ticker_obj.history(period="3y")
        else:
            console.print(f"-> Resolved [bold]{ticker_symbol}[/bold] (conid:{conid}) to Yahoo Ticker: [bold cyan]{yf_ticker}[/bold cyan]")
            df_daily = price_service.fetch_and_store(conid, yf_ticker)
        
        if df_daily.empty:
            return f"[red]Error: No data found for {yf_ticker}[/red]", {}

        # 3. Handle Max Price since Entry Date
        entry_date_dt = pd.to_datetime(entry_date_str)
        max_price = price_service.highest_high_since(conid, entry_date_str) or entry_price
        max_price = max(entry_price, max_price)

        # 4. Define Timeframes and Frequencies
        intervals = [
            ("14d", 14, 'daily'),
            ("6m", 26, 'weekly'),
            ("8q", 24, 'monthly')
        ]
        raw_values = {}

        # 5. Build Table
        title = f"ATR Gauge for {ticker_symbol} (Entry {entry_price:,.2f} on {entry_date_dt.strftime('%Y-%m-%d')}, Max {max_price:,.2f})"
        if multiplier != 1.0:
            title += f" [bold yellow](Buffer: {multiplier}x)[/bold yellow]"
            
        table = Table(title=title, header_style="bold cyan", box=None)
        table.add_column("Label", style="bold")
        table.add_column(f"ATR ({multiplier}x)", justify="right", style="yellow")
        table.add_column("Base (F)", justify="right", style="dim")
        table.add_column("Fixed SL", justify="right", style="green")
        table.add_column("ATR/Base %", justify="right", style="dim")
        table.add_column("Base (T)", justify="right", style="dim")
        table.add_column("Trail SL", justify="right", style="magenta")
        table.add_column("ATR/Base %", justify="right", style="dim")

        # 6. Process each frequency
        for label, window, tf in intervals:
            # Fetch resampled data from PriceService
            df = price_service.get_prices(conid, timeframe=tf)
            
            if len(df) < window + 1: continue

            df['PrevClose'] = df['Close'].shift(1)
            df['TR'] = np.maximum(df['High'] - df['Low'], 
                        np.maximum(abs(df['High'] - df['PrevClose']), 
                                   abs(df['Low'] - df['PrevClose'])))

            atr_sma = df['TR'].rolling(window=window).mean().iloc[-1]
            # Use Wilder's Smoothing as standard
            atr_wilder = df['TR'].ewm(com=window - 1, min_periods=window, adjust=False).mean().iloc[-1]

            for method, val in [("SMA", atr_sma), ("Wilder", atr_wilder)]:
                # Apply Multiplier
                final_val = val * multiplier
                
                full_label = f"ATR_{label}_{tf[:1].upper()}_{method}"
                raw_values[full_label] = final_val
                
                # Calculations
                fixed_sl = entry_price - final_val
                trail_sl = max_price - final_val
                
                # Percentage of ATR relative to the specific Base
                fixed_atr_pct = (final_val / entry_price * 100) if entry_price > 0 else 0
                trail_atr_pct = (final_val / max_price * 100) if max_price > 0 else 0
                
                table.add_row(
                    full_label,
                    f"{final_val:.2f}",
                    f"{entry_price:,.2f}",
                    f"{fixed_sl:.2f}",
                    f"{fixed_atr_pct:.1f}%",
                    f"{max_price:,.2f}",
                    f"{trail_sl:.2f}",
                    f"{trail_atr_pct:.1f}%"
                )
            
        return table, raw_values

    except Exception as e:
        return f"[red]Error calculating ATR: {e}[/red]", {}
