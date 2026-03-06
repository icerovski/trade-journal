import pandas as pd
import numpy as np
import yfinance as yf
from rich.table import Table
from rich.console import Console
from rich import box
from models import Position, ATRDiscoveryRow
from db import update_high_water_mark
from services.price_service import PriceService
from logger import logger

console = Console()

class RiskEngine:
    """
    Core engine for calculating risk metrics, Stop Losses, and Take Profits.
    """

    @staticmethod
    def audit_position_risk(current_price: float, stop: float, entry_price: float, qty: float, multiplier: float, nav: float) -> dict:
        """
        Evaluate a position against two hard limits: 1.0% Risk-at-Stop and 5% Total Market Exposure.
        Returns the remaining capital budget for both constraints.
        """
        if nav <= 0:
            return {
                "status_color": "RED",
                "risk_budget_remaining": 0.0,
                "exposure_budget_remaining": 0.0,
                "is_breached": False
            }

        # 1. Current State
        risk_val = (entry_price - stop) * qty * multiplier
        exposure_val = current_price * qty * multiplier

        risk_pct = (risk_val / nav) * 100
        exposure_pct = (exposure_val / nav) * 100
        
        # 2. Maximum Budget
        max_risk_cap = nav * 0.01
        max_exposure_cap = nav * 0.05

        # 3. Remaining Budget (In Dollars/Euros)
        risk_budget_rem = max_risk_cap - risk_val
        exposure_budget_rem = max_exposure_cap - exposure_val
        
        # 4. Share Adjustment (Quantity-First Auditing)
        # Calculate how many shares we can ADD (+) or must TRIM (-) to hit the 1.0% / 5.0% limit.
        # Use the most restrictive constraint.
        risk_dist = abs(entry_price - stop) * multiplier
        risk_adj = risk_budget_rem / risk_dist if risk_dist > 0 else 0
        exp_adj = exposure_budget_rem / (current_price * multiplier) if current_price > 0 else 0
        
        # If budget is positive, we can add up to the MIN of both adjustments.
        # If budget is negative (over limit), we must trim by the MAX (most negative) adjustment.
        # Simplified: min() covers both cases correctly for institutional risk parity.
        adjustment = min(risk_adj, exp_adj)

        is_breached = current_price <= stop

        if is_breached or risk_pct > 1.5 or exposure_pct > 5.5:
            status_color = "RED"
        elif risk_pct > 1.0 or exposure_pct > 5.0:
            status_color = "YELLOW"
        else:
            status_color = "GREEN"

        return {
            "status_color": status_color,
            "current_risk_pct": risk_pct,
            "current_exposure_pct": exposure_pct,
            "risk_budget_rem": risk_budget_rem,
            "exposure_budget_rem": exposure_budget_rem,
            "adjustment": adjustment,
            "is_breached": is_breached
        }

    @staticmethod
    def calculate_pilot_entry(current_price: float, assigned_atr: float, nav: float, multiplier: float, 
                              entry_price: float, daily_atr: float, scale_step: float = 0.5) -> dict:
        """
        Calculates the Pilot Entry roadmap.
        - assigned_atr: The width of the STOP LOSS (e.g. 15% of price).
        - daily_atr: The 14d 'heartbeat' used for SCALING milestones.
        - scale_step: Multiplier applied to daily_atr for each stage add.
        """
        if nav <= 0 or current_price <= 0 or assigned_atr <= 0:
            return {"shares": 0, "stop": 0, "risk_pct": 0, "stage2_price": 0, "stage3_price": 0, "full_target_qty": 0}
            
        # 1. Dual-Constraint Target Calculation (Matches Audit Logic)
        risk_dist = assigned_atr * multiplier
        qty_by_risk = (nav * 0.01) / risk_dist if risk_dist > 0 else 0
        qty_by_exposure = (nav * 0.05) / (current_price * multiplier) if current_price > 0 else 0
        
        full_target_qty = int(min(qty_by_risk, qty_by_exposure))
        unit_shares = int(full_target_qty / 3.0)
        
        # 2. Financial Milestones (Based on the 14d Daily ATR Heartbeat)
        step_dist = daily_atr * scale_step
        s2_p = entry_price + step_dist
        s3_p = entry_price + (2 * step_dist)
        
        # Scale-In Total Outlay: Sum of 3 tranches at their respective prices
        tranche = full_target_qty / 3.0
        scale_in_outlay = (entry_price * tranche * multiplier) + (s2_p * tranche * multiplier) + (s3_p * tranche * multiplier)
        
        # Single Purchase Outlay: Full target at current market price
        single_outlay = current_price * full_target_qty * multiplier
        
        return {
            "shares": unit_shares,
            "stop": current_price - assigned_atr,
            "risk_pct": 0.33,
            "stage2_price": s2_p,
            "stage3_price": s3_p,
            "full_target_qty": full_target_qty,
            "scale_in_outlay": scale_in_outlay,
            "single_outlay": single_outlay
        }

    @staticmethod
    def calculate_position_risk(position: Position, risk_settings: dict):
        """
        Enriches a Position object with risk metrics based on provided settings.
        Implements the 'Ratchet' rule: Stop Loss only moves in the trader's favor.
        """
        if str(position.conid) in risk_settings:
            settings = risk_settings[str(position.conid)]
            
            # Handle tuple unpacking gracefully for backwards compatibility during session updates
            if len(settings) == 5:
                atr, s_type, highest_sl, e_type, scale_step = settings
            elif len(settings) == 4:
                atr, s_type, highest_sl, e_type = settings
                scale_step = 0.5
            else:
                atr, s_type, highest_sl = settings[:3]
                e_type = 'SINGLE'
                scale_step = 0.5
            
            # 1. Base Stop Loss Calculation
            # Stop Base is Entry Price (Fixed) or Max Price Since Entry (Trailing)
            stop_base = position.max_since_entry if s_type == 'TRAILING' else position.entry_price
            
            # Robust Fallback: If stop_base is 0 (missing entry), use mark_price or current_price as the floor
            if not stop_base or stop_base == 0:
                stop_base = position.mark_price or position.current_price
            
            calculated_sl = stop_base - atr
            
            # Populate raw fields for easier dashboard access
            position.atr = atr
            position.stop_type = s_type
            position.entry_type = e_type
            position.scale_step = scale_step
            
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
            
            # 7. SL % (Distance from Base)
            position.sl_pct_base = (atr / stop_base * 100) if stop_base > 0 else 0
        
        return position

def get_atr_discovery_data(ticker_symbol, entry_date_str, entry_price, multiplier=1.0, conid=None, qty=0.0, inst_multiplier=1.0, total_nav=0.0):
    """
    Returns raw ATR analysis data for both FIXED and TRAILING stop types.
    Calculates Risk % of NAV (R) for each scenario.
    """
    from .portfolio_manager import PortfolioManager
    try:
        manager = PortfolioManager()
        yf_ticker = manager.mapper.resolve_yf_ticker(ticker_symbol, conid=conid)
        price_service = PriceService()
        
        if conid:
            df_daily = price_service.fetch_and_store(conid, yf_ticker)
        else:
            df_daily = yf.Ticker(yf_ticker).history(period="3y")
        
        if df_daily.empty:
            return None

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
        current_price = df_daily['Close'].iloc[-1] if not df_daily.empty else entry_price

        intervals = [
            ("14d", 14, 'daily'),
            ("12w", 12, 'weekly'),
            ("12m", 12, 'monthly'),
            ("12q", 12, 'quarterly'),
            ("20q", 20, 'quarterly')
        ]
        
        results = []
        for label, window, tf in intervals:
            if conid:
                df = price_service.get_prices(conid, timeframe=tf)
            else:
                # Map timeframe to yfinance periods/intervals
                yf_period = "3y" if tf == 'daily' else ("5y" if tf == 'weekly' else ("10y" if tf == 'monthly' else "max"))
                yf_interval = "1d" if tf == 'daily' else ("1wk" if tf == 'weekly' else ("1mo" if tf == 'monthly' else "3mo"))
                
                # Quarterly needs max to ensure enough history for 20q
                if tf == 'quarterly': yf_period = "max"
                
                df = yf.Ticker(yf_ticker).history(period=yf_period, interval=yf_interval)

            if len(df) < window + 1: continue

            df['PrevClose'] = df['Close'].shift(1)
            df['TR'] = np.maximum(df['High'] - df['Low'], 
                        np.maximum(abs(df['High'] - df['PrevClose']), 
                                   abs(df['Low'] - df['PrevClose'])))

            atr_wilder = df['TR'].ewm(com=window - 1, min_periods=window, adjust=False).mean().iloc[-1]
            atr_sma = df['TR'].rolling(window=window).mean().iloc[-1]
            final_wilder = atr_wilder * multiplier

            # Calculate for both types
            for s_type in ['FIXED', 'TRAILING']:
                base_price = max_price if s_type == 'TRAILING' else entry_price
                stop_price = base_price - final_wilder
                atr_pct = (final_wilder / base_price * 100) if base_price > 0 else 0
                
                # P/L at Stop (Total profit/loss from entry)
                pl_at_stop = (stop_price - entry_price) * qty * inst_multiplier
                
                # R (Risk % of NAV) = Potential Loss relative to Entry / Total NAV
                # Formula: (Entry - Stop) * Qty / NAV
                risk_amt = (entry_price - stop_price) * qty * inst_multiplier
                pl_pct_nav = (risk_amt / total_nav * 100) if total_nav > 0 else 0
                
                buffer_pct = ((current_price - stop_price) / current_price * 100) if current_price > 0 else 0
                
                results.append(ATRDiscoveryRow(
                    label=label,
                    stop_type=s_type,
                    atr_wilder=final_wilder,
                    atr_sma=atr_sma * multiplier,
                    stop_price=stop_price,
                    atr_base_pct=atr_pct,
                    pl_at_stop=pl_at_stop,
                    buffer_pct=buffer_pct,
                    pl_pct_nav=pl_pct_nav
                ))
            
        return {
            'ticker': ticker_symbol,
            'entry_price': entry_price,
            'max_price': max_price,
            'current_price': current_price,
            'rows': results
        }
    except Exception as e:
        logger.error(f"ATR Discovery Data Error: {e}")
        return None
