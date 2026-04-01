import pandas as pd
import numpy as np
import yfinance as yf
from rich.console import Console
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
    def audit_position_risk(current_price: float, stop: float, entry_price: float, qty: float, multiplier: float, nav: float, max_r_pct: float = 1.0, max_exp_pct: float = 5.0) -> dict:
        """
        Evaluate a position against two hard limits: Risk-at-Stop and Total Market Exposure.
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
        
        # 2. Maximum Budget (Institutional Cap vs Custom Conviction Cap)
        max_risk_cap = nav * (max_r_pct / 100.0)
        max_exposure_cap = nav * (max_exp_pct / 100.0)

        # 3. Remaining Budget (In Dollars/Euros)
        risk_budget_rem = max_risk_cap - risk_val
        exposure_budget_rem = max_exposure_cap - exposure_val
        
        # 4. Share Adjustment (Quantity-First Auditing)
        # Calculate how many shares we can ADD (+) or must TRIM (-) to hit the risk / exposure limits.
        
        # Mandate: Use Current Market Price for all "Shares to Add" calculations.
        if risk_budget_rem > 0:
            # ADDING: The risk distance for new shares is current_price to stop.
            risk_dist = abs(current_price - stop) * multiplier
        else:
            # TRIMMING: Removing shares reduces risk by the original inception distance (avg cost to stop).
            risk_dist = abs(entry_price - stop) * multiplier

        # If risk_dist is 0 (stop at entry/price), risk constraint is effectively infinite shares allowed.
        risk_adj = risk_budget_rem / risk_dist if risk_dist > 0 else float('inf')
        exp_adj = exposure_budget_rem / (current_price * multiplier) if current_price > 0 else 0
        
        # Use the most restrictive constraint.
        adjustment = min(risk_adj, exp_adj)

        is_breached = current_price <= stop

        # Audit thresholds scale with the custom limits
        if is_breached or risk_pct > (max_r_pct * 1.5) or exposure_pct > (max_exp_pct * 1.1):
            status_color = "RED"
        elif risk_pct > max_r_pct or exposure_pct > max_exp_pct:
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
            "is_breached": is_breached,
            "max_r_pct": max_r_pct,
            "max_exp_pct": max_exp_pct
        }

    @staticmethod
    def calculate_pilot_entry(current_price: float, assigned_atr: float, nav: float, multiplier: float, 
                              entry_price: float, daily_atr: float, scale_step: float = 0.5, 
                              max_r_pct: float = 1.0, max_exp_pct: float = 5.0,
                              base_price: float = None) -> dict:
        """
        Calculates the Pilot Entry roadmap based on custom Risk and Exposure limits.
        If base_price is provided (e.g. Inception Price), targets are anchored to it.
        """
        if nav <= 0 or current_price <= 0 or assigned_atr <= 0:
            return {"shares": 0, "stop": 0, "risk_pct": 0, "stage2_price": 0, "stage3_price": 0, "full_target_qty": 0}
            
        # 1. Dual-Constraint Target Calculation (Matches Audit Logic)
        risk_dist = assigned_atr * multiplier
        qty_by_risk = (nav * (max_r_pct / 100.0)) / risk_dist if risk_dist > 0 else 0
        qty_by_exposure = (nav * (max_exp_pct / 100.0)) / (current_price * multiplier) if current_price > 0 else 0
        
        full_target_qty = int(min(qty_by_risk, qty_by_exposure))
        unit_shares = int(full_target_qty / 3.0)
        
        # 2. Financial Milestones (Based on the 14d Daily ATR Heartbeat)
        anchor = base_price if base_price is not None else entry_price
        step_dist = daily_atr * scale_step
        s2_p = anchor + step_dist
        s3_p = anchor + (2 * step_dist)
        
        # Scale-In Total Outlay: Sum of 3 tranches at their respective prices
        tranche = full_target_qty / 3.0
        scale_in_outlay = (anchor * tranche * multiplier) + (s2_p * tranche * multiplier) + (s3_p * tranche * multiplier)
        
        # Single Purchase Outlay: Full target at current market price
        single_outlay = current_price * full_target_qty * multiplier
        
        return {
            "shares": unit_shares,
            "stop": current_price - assigned_atr,
            "risk_pct": (max_r_pct / 3.0),
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
            
            # Handle tuple unpacking for different versions of the DB schema
            max_r_pct = 1.0
            max_exp_pct = 5.0
            if len(settings) >= 7:
                # settings: (atr, type, highest_sl, entry_type, scale_step, max_r, max_exp, [start_date])
                atr, s_type, highest_sl, e_type, scale_step, max_r_pct, max_exp_pct = settings[:7]
            elif len(settings) == 6:
                atr, s_type, highest_sl, e_type, scale_step, max_r_pct = settings
            elif len(settings) == 5:
                atr, s_type, highest_sl, e_type, scale_step = settings
            elif len(settings) == 4:
                atr, s_type, highest_sl, e_type = settings
                scale_step = 0.5
            else:
                atr, s_type, highest_sl = settings[:3]
                e_type = 'SINGLE'
                scale_step = 0.5
            
            # 1. Base Stop Loss Calculation
            # Robust Base: Use highest of Entry, Current, or Mark price
            hwm_proxy = max(position.entry_price, position.current_price, position.mark_price)
            # For Trailing, anchor to the Max High Since Entry (which should now be healed by date)
            stop_base = max(position.max_since_entry, hwm_proxy) if s_type == 'TRAILING' else position.entry_price
            
            # Robust Fallback: If stop_base is 0 (missing entry), use hwm_proxy
            if not stop_base or stop_base == 0:
                stop_base = hwm_proxy
            
            calculated_sl = stop_base - atr
            
            # Populate raw fields for easier dashboard access
            position.atr = atr
            position.stop_type = s_type
            position.entry_type = e_type
            position.scale_step = scale_step
            position.max_r_pct = max_r_pct
            position.max_exp_pct = max_exp_pct
            
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

    @staticmethod
    def evaluate_confluence(price: float, stop_price: float, dmas: dict, atr: float) -> dict:
        """
        Evaluates Volatility-Adjusted Confluence based on Daily ATR.
        """
        if atr <= 0 or not dmas:
            return {"strength": 0, "zones": []}
            
        confluence_zones = []
        strength_score = 0
        
        for dma_name, dma_val in dmas.items():
            # Check Entry Confluence
            dist_to_price = abs(price - dma_val)
            atr_dist_price = dist_to_price / atr
            
            if atr_dist_price < 0.25:
                strength_score += 1
                confluence_zones.append({
                    "type": "ENTRY",
                    "dma": dma_name,
                    "dma_val": dma_val,
                    "atr_distance": atr_dist_price,
                    "pct_distance": (dist_to_price / price) * 100 if price > 0 else 0,
                    "is_fortress": atr_dist_price < 0.10
                })
                
            # Check Stop Confluence
            dist_to_stop = abs(stop_price - dma_val)
            atr_dist_stop = dist_to_stop / atr
            
            if atr_dist_stop < 0.25:
                strength_score += 1
                confluence_zones.append({
                    "type": "STOP",
                    "dma": dma_name,
                    "dma_val": dma_val,
                    "atr_distance": atr_dist_stop,
                    "pct_distance": (dist_to_stop / stop_price) * 100 if stop_price > 0 else 0,
                    "is_fortress": atr_dist_stop < 0.10
                })
                
        return {
            "strength": strength_score,
            "zones": confluence_zones
        }

def get_atr_discovery_data(ticker_symbol, entry_date_str, entry_price, multiplier=1.0, conid=None, qty=0.0, inst_multiplier=1.0, total_nav=0.0, max_r_pct=1.0, max_exp_pct=5.0):
    """
    Returns raw ATR analysis data for both FIXED and TRAILING stop types.
    Calculates Risk % of NAV (R) for each scenario based on customizable Risk and Exposure limits.
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
            except Exception:
                max_price = entry_price
        
        current_price = df_daily['Close'].iloc[-1] if not df_daily.empty else entry_price

        # Prospect logic: If entry_price is unknown (0.0), assume we buy at current market price
        effective_entry = entry_price if entry_price > 0 else current_price
        
        # Ensure max_price is never 0 for simulation; default to effective entry
        max_price = max(effective_entry, max_price)

        intervals = [
            ("14d", 14, 'daily'),
            ("12w", 12, 'weekly'),
            ("12m", 12, 'monthly'),
            ("12q", 12, 'quarterly')
        ]

        results = []
        for label, window, tf in intervals:
            if conid:
                df = price_service.get_prices(conid, timeframe=tf)
            else:
                yf_period = "3y" if tf == 'daily' else ("5y" if tf == 'weekly' else ("10y" if tf == 'monthly' else "max"))
                yf_interval = "1d" if tf == 'daily' else ("1wk" if tf == 'weekly' else ("1mo" if tf == 'monthly' else "3mo"))
                if tf == 'quarterly':
                    yf_period = "max"
                df = yf.Ticker(yf_ticker).history(period=yf_period, interval=yf_interval)

            # Adaptive Window: Use the requested window, or the max available history (min 2 periods)
            # This prevents 12q from disappearing for tickers with 3-5 years of history
            if len(df) < 2:
                continue
            
            # If we have less than window+1, we use a smaller window for the calculation
            # but we keep the label so the user knows which timeframe we are looking at.
            actual_window = min(window, len(df) - 1)

            df['PrevClose'] = df['Close'].shift(1)
            df['TR'] = np.maximum(df['High'] - df['Low'], 
                        np.maximum(abs(df['High'] - df['PrevClose']), 
                                   abs(df['Low'] - df['PrevClose'])))

            # Wilder ATR (EMA equivalent) using the adaptive window
            atr_wilder = df['TR'].ewm(com=actual_window - 1, min_periods=actual_window, adjust=False).mean().iloc[-1]
            # Simple Moving Average ATR
            atr_sma = df['TR'].rolling(window=actual_window).mean().iloc[-1]
            
            final_wilder = atr_wilder * multiplier

            # Calculate for both types
            for s_type in ['FIXED', 'TRAILING']:
                base_price = max_price if s_type == 'TRAILING' else effective_entry
                stop_price = base_price - final_wilder
                atr_pct = (final_wilder / base_price * 100) if base_price > 0 else 0
                
                # --- SIZING FOR PROSPECTS ---
                calc_qty = qty
                if calc_qty == 0 and total_nav > 0:
                    risk_dist = abs(effective_entry - stop_price) * inst_multiplier
                    # Dual-Constraint Sizing
                    risk_q = (total_nav * (max_r_pct / 100.0)) / risk_dist if risk_dist > 0 else float('inf')
                    exp_q = (total_nav * (max_exp_pct / 100.0)) / (effective_entry * inst_multiplier) if effective_entry > 0 else 0
                    calc_qty = int(min(risk_q, exp_q))

                # P/L at Stop (Total profit/loss from entry)
                pl_at_stop = (stop_price - effective_entry) * calc_qty * inst_multiplier
                
                # R (Risk % of NAV) = Potential Loss relative to Entry / Total NAV
                risk_amt = (effective_entry - stop_price) * calc_qty * inst_multiplier
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
                    pl_pct_nav=pl_pct_nav,
                    qty=calc_qty
                ))
            
        trend_data = price_service.get_trend_analysis(conid if conid else f"PROSPECT:{ticker_symbol}", yf_ticker)

        return {
            'ticker': ticker_symbol,
            'entry_price': effective_entry,
            'max_price': max_price,
            'current_price': current_price,
            'rows': results,
            'max_r_pct': max_r_pct,
            'max_exp_pct': max_exp_pct,
            'trend_data': trend_data
        }
    except Exception as e:
        logger.error(f"ATR Discovery Data Error: {e}")
        return None
