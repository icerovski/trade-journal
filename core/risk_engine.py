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
        if str(position.conid) in risk_settings:
            atr, s_type, highest_sl = risk_settings[str(position.conid)]
            
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
                update_high_water_mark(position.conid, final_sl)
            
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

def calculate_atr_metrics(ticker_symbol, entry_date_str, entry_price, multiplier=1.0, conid=None, stop_type='TRAILING', qty=0.0, inst_multiplier=1.0, total_nav=0.0):
    """
    Calculates ATR across multiple timeframes for visual analysis.
    Prioritizes Wilder ATR with SMA in brackets for audit.
    """
    from .portfolio_manager import PortfolioManager
    try:
        # 1. Resolve Ticker
        manager = PortfolioManager()
        yf_ticker = manager.mapper.resolve_yf_ticker(ticker_symbol, conid=conid)
        price_service = PriceService()
        
        # 2. Fetch/Prepare Data
        if conid:
            console.print(f"-> Resolved [bold]{ticker_symbol}[/bold] (conid:{conid}) to Yahoo Ticker: [bold cyan]{yf_ticker}[/bold cyan]")
            df_daily = price_service.fetch_and_store(conid, yf_ticker)
        else:
            console.print(f"-> [yellow]Warning:[/yellow] No conid provided for {ticker_symbol}. Using direct Yahoo fetch.")
            df_daily = yf.Ticker(yf_ticker).history(period="3y")
        
        if df_daily.empty:
            return f"[red]Error: No data found for {yf_ticker}[/red]", {}

        # 3. Handle Max Price since Entry Date
        if conid:
            max_price = price_service.highest_high_since(conid, entry_date_str) or entry_price
        else:
            try:
                entry_dt = pd.to_datetime(entry_date_str).tz_localize(df_daily.index.tz) if df_daily.index.tz else pd.to_datetime(entry_date_str)
                df_since = df_daily[df_daily.index >= entry_dt]
                max_price = df_since['High'].max() if not df_since.empty else entry_price
            except:
                max_price = entry_price
        
        max_price = max(entry_price, max_price)

        # 4. Define Timeframes (Added Weekly 12)
        intervals = [
            ("14d", 14, 'daily'),
            ("12w", 12, 'weekly'),
            ("12m", 12, 'monthly'),
            ("8q", 8, 'quarterly')
        ]
        raw_values = {}

        # 5. Build Table
        stop_type = stop_type.upper()
        mode_str = "TRAILING" if stop_type == 'TRAILING' else "FIXED"
        base_price = max_price if stop_type == 'TRAILING' else entry_price
        
        title = f"ATR Gauge for {ticker_symbol} ({mode_str} Stop)"
        if multiplier != 1.0: title += f" [bold yellow](Buffer: {multiplier}x)[/bold yellow]"
            
        table = Table(title=title, header_style="bold cyan", box=None, 
                      caption=f"\n[dim]Base Price for {mode_str}: {base_price:,.2f} | Entry: {entry_price:,.2f} | Max since entry: {max_price:,.2f}[/dim]")
        table.add_column("Label", style="bold")
        table.add_column(f"ATR Wilder (SMA) @{multiplier}x", justify="right", style="yellow")
        table.add_column("Stop Price", justify="right", style="magenta" if stop_type == 'TRAILING' else "green")
        table.add_column("ATR/Base %", justify="right", style="dim")
        table.add_column("P/L at Stop", justify="right", style="bold")
        table.add_column("Buffer (%)", justify="right", style="cyan")
        table.add_column("% of NAV", justify="right", style="dim")

        # 6. Process each frequency
        current_price = df_daily['Close'].iloc[-1] if not df_daily.empty else entry_price
        
        for label, window, tf in intervals:
            if conid:
                df = price_service.get_prices(conid, timeframe=tf)
            else:
                # Map timeframe to yfinance periods/intervals
                yf_period = "3y" if tf == 'daily' else ("5y" if tf == 'weekly' else ("10y" if tf == 'monthly' else "max"))
                yf_interval = "1d" if tf == 'daily' else ("1wk" if tf == 'weekly' else ("1mo" if tf == 'monthly' else "3mo"))
                df = yf.Ticker(yf_ticker).history(period=yf_period, interval=yf_interval)

            if len(df) < window + 1: continue

            df['PrevClose'] = df['Close'].shift(1)
            df['TR'] = np.maximum(df['High'] - df['Low'], 
                        np.maximum(abs(df['High'] - df['PrevClose']), 
                                   abs(df['Low'] - df['PrevClose'])))

            # 1. Calculate Wilder (Primary) and SMA (Audit)
            atr_wilder = df['TR'].ewm(com=window - 1, min_periods=window, adjust=False).mean().iloc[-1]
            atr_sma = df['TR'].rolling(window=window).mean().iloc[-1]

            # 2. Store Wilder for assignment options
            raw_values[label] = atr_wilder * multiplier
            
            # 3. Calculations for Table (Using Wilder as base)
            final_val_wilder = atr_wilder * multiplier
            final_val_sma = atr_sma * multiplier
            
            stop_price = base_price - final_val_wilder
            atr_pct = (final_val_wilder / base_price * 100) if base_price > 0 else 0
            pl_at_stop = (stop_price - entry_price) * qty * inst_multiplier
            pl_color = "green" if pl_at_stop >= 0 else "red"
            pl_pct_nav = (pl_at_stop / total_nav * 100) if total_nav > 0 else 0
            buffer_pct = ((current_price - stop_price) / current_price * 100) if current_price > 0 else 0
            
            table.add_row(
                label, 
                f"{final_val_wilder:.2f} ({final_val_sma:.2f})", 
                f"{stop_price:,.2f}", 
                f"{atr_pct:.1f}%",
                f"[{pl_color}]{pl_at_stop:,.0f}[/{pl_color}]", 
                f"{buffer_pct:.1f}%", 
                f"{pl_pct_nav:.2f}%"
            )
            
        return table, raw_values

    except Exception as e:
        return f"[red]Error calculating ATR: {e}[/red]", {}
