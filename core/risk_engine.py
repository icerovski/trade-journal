import pandas as pd
import numpy as np
import yfinance as yf
from rich.console import Console
from models import Position, ATRDiscoveryRow
from db import update_high_water_mark
from services.price_service import PriceService
from logger import logger
from constants import (
    CONFLUENCE_ATR_THRESHOLD, CONFLUENCE_FORTRESS_THRESHOLD,
    RISK_RED_MULTIPLIER, EXPOSURE_RED_MULTIPLIER, TP_ATR_MULTIPLE,
)

console = Console()

class RiskEngine:
    """
    Core engine for calculating risk metrics, Stop Losses, and Take Profits.
    """

    @staticmethod
    def audit_position_risk(current_price: float, stop: float, entry_price: float, qty: float, multiplier: float, nav: float, max_r_pct: float = 1.0, max_exp_pct: float = 5.0, fx_rate: float = 1.0) -> dict:
        """
        Evaluate a position against two hard limits: Risk-at-Stop and Total Market Exposure.
        Returns the remaining capital budget for both constraints.
        Implements HCM (Higher of Cost or Market) for exposure limits.
        Normalizes all values to NAV currency using fx_rate.
        """
        if nav <= 0:
            return {
                "status_color": "RED",
                "risk_budget_remaining": 0.0,
                "exposure_budget_remaining": 0.0,
                "is_breached": False
            }

        # 1. Current State (Normalized to NAV Currency)
        risk_val = (entry_price - stop) * qty * multiplier * fx_rate
        # HCM logic: Use higher of Cost (entry * qty) or Market (current * qty)
        exposure_val = max(entry_price, current_price) * qty * multiplier * fx_rate

        risk_pct = (risk_val / nav) * 100
        exposure_pct = (exposure_val / nav) * 100
        
        # 2. Maximum Budget (Institutional Cap vs Custom Conviction Cap)
        max_risk_cap = nav * (max_r_pct / 100.0)
        max_exposure_cap = nav * (max_exp_pct / 100.0)

        # 3. Remaining Budget (In NAV Currency)
        risk_budget_rem = max_risk_cap - risk_val
        exposure_budget_rem = max_exposure_cap - exposure_val
        
        # 4. Share Adjustment (Quantity-First Auditing)
        # Mandate: Use Current Market Price for all "Shares to Add" calculations.
        if risk_budget_rem > 0:
            # ADDING: The risk distance for new shares is current_price to stop.
            risk_dist = abs(current_price - stop) * multiplier * fx_rate
        else:
            # TRIMMING: Removing shares reduces risk by the original inception distance (avg cost to stop).
            risk_dist = abs(entry_price - stop) * multiplier * fx_rate

        # If risk_dist is 0 (stop at entry/price), risk constraint is effectively infinite shares allowed.
        risk_adj = risk_budget_rem / risk_dist if risk_dist > 0 else float('inf')
        exp_adj = exposure_budget_rem / (current_price * multiplier * fx_rate) if current_price > 0 else 0

        # Use the most restrictive constraint.
        adjustment = min(risk_adj, exp_adj)

        is_breached = current_price <= stop

        # Audit thresholds scale with the custom limits
        if is_breached or risk_pct > (max_r_pct * RISK_RED_MULTIPLIER) or exposure_pct > (max_exp_pct * EXPOSURE_RED_MULTIPLIER):
            status_color = "RED"
        elif risk_pct > max_r_pct or exposure_pct > max_exp_pct:
            status_color = "YELLOW"
        else:
            status_color = "GREEN"

        # R-Breach Remediation: quantify the two paths to restore compliance
        stop_to_restore = None
        shares_to_trim = None
        if risk_budget_rem < 0 and qty > 0:
            per_share = multiplier * fx_rate
            # Path A: minimum stop price that restores R compliance at current qty
            stop_to_restore = entry_price - (nav * (max_r_pct / 100.0)) / (qty * per_share)
            # Path B: shares to trim to restore R compliance at current stop
            risk_dist_per_share = (entry_price - stop) * per_share
            if risk_dist_per_share > 0:
                qty_keep = (nav * (max_r_pct / 100.0)) / risk_dist_per_share
                shares_to_trim = max(0.0, qty - qty_keep)

        return {
            "status_color": status_color,
            "current_risk_pct": risk_pct,
            "current_exposure_pct": exposure_pct,
            "risk_budget_rem": risk_budget_rem,
            "exposure_budget_rem": exposure_budget_rem,
            "adjustment": adjustment,
            "is_breached": is_breached,
            "max_r_pct": max_r_pct,
            "max_exp_pct": max_exp_pct,
            "stop_to_restore": stop_to_restore,
            "shares_to_trim": shares_to_trim,
        }

    @staticmethod
    def calculate_pilot_entry(current_price: float, assigned_atr: float, nav: float, multiplier: float, 
                              entry_price: float, daily_atr: float, scale_step: float = 0.5, 
                              max_r_pct: float = 1.0, max_exp_pct: float = 5.0,
                              base_price: float = None, current_qty: float = 0.0, fx_rate: float = 1.0) -> dict:
        """
        Calculates the Pilot Entry roadmap based on custom Risk and Exposure limits.
        If base_price is provided (e.g. Inception Price), targets are anchored to it.
        Implements HCM (Higher of Cost or Market) for target quantity calculation.
        Normalizes values using fx_rate.
        """
        if nav <= 0 or current_price <= 0 or assigned_atr <= 0:
            return {"shares": 0, "stop": 0, "risk_pct": 0, "stage2_price": 0, "stage3_price": 0, "full_target_qty": 0}
            
        # 1. Dual-Constraint Target Calculation (Matches Audit Logic)
        risk_dist = assigned_atr * multiplier * fx_rate
        # Total Risk-at-Stop constraint
        qty_by_risk = (nav * (max_r_pct / 100.0)) / risk_dist if risk_dist > 0 else 0
        
        # Total Exposure constraint (HCM-aware)
        max_exposure_cap = nav * (max_exp_pct / 100.0)
        
        if current_price >= entry_price or current_qty == 0:
            # Winner or Fresh: Market value is the constraint
            target_total_qty = max_exposure_cap / (current_price * multiplier * fx_rate) if current_price > 0 else 0
        else:
            # Loser: Anchor existing shares to entry_price (HCM)
            existing_hcm_val = entry_price * current_qty * multiplier * fx_rate
            remaining_cap = max(0, max_exposure_cap - existing_hcm_val)
            additional_qty = remaining_cap / (current_price * multiplier * fx_rate) if current_price > 0 else 0
            target_total_qty = current_qty + additional_qty
        
        full_target_qty = int(min(qty_by_risk, target_total_qty))
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
            profile = risk_settings[str(position.conid)]
            
            atr = profile.atr_value
            s_type = profile.stop_type
            e_type = profile.entry_type
            scale_step = profile.scale_step
            max_r_pct = profile.max_r_pct
            max_exp_pct = profile.max_exp_pct
            highest_sl = profile.highest_sl
            inception_stop = profile.inception_stop
            inception_atr = profile.inception_atr
            
            # 1. Base Stop Loss Calculation
            if s_type == 'FIXED':
                # atr_value IS the stop price — absolute, set once, never auto-moved
                calculated_sl = atr
                stop_base = position.entry_price or max(position.current_price, position.mark_price)
            else:  # TRAILING
                hwm_proxy = max(position.entry_price, position.current_price, position.mark_price)
                stop_base = max(position.max_since_entry, hwm_proxy)
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
            position.inception_stop = inception_stop
            position.inception_atr = inception_atr
            
            # 2. Ratchet Rule (High-Water Mark)
            final_sl = max(calculated_sl, highest_sl)
            
            # Update high-water mark in DB if we reached a new high
            if final_sl > highest_sl:
                update_high_water_mark(position.conid, final_sl)
            
            position.sl_price = final_sl
            
            # 3. Take Profit
            if s_type == 'FIXED':
                # atr is the stop price, not a distance — use inception_atr for TP distance
                atr_for_tp = inception_atr if (inception_atr and inception_atr > 0) else 0.0
                position.tp_price = final_sl + (TP_ATR_MULTIPLE * atr_for_tp) if atr_for_tp > 0 else None
            else:
                position.tp_price = final_sl + (TP_ATR_MULTIPLE * atr)

            # 4. Percentage Metrics
            if position.current_price > 0:
                position.down_pct = ((position.current_price - position.sl_price) / position.current_price * 100)
                if position.tp_price:
                    position.up_pct = ((position.tp_price - position.current_price) / position.current_price * 100)
            
            # 5. Outcome at Stop/Target (Total P/L relative to Entry)
            position.risk_val = (position.sl_price - position.entry_price) * position.qty * position.multiplier
            position.reward_val = ((position.tp_price - position.entry_price) * position.qty * position.multiplier) if position.tp_price else 0.0

            # 6. Current Efficiency (Remaining Reward / Current Risk)
            dist_to_stop = (position.current_price - position.sl_price)
            dist_to_target = ((position.tp_price - position.current_price) if position.tp_price else 0.0)

            if dist_to_stop != 0:
                position.rr_ratio = dist_to_target / dist_to_stop
            else:
                position.rr_ratio = 0.0

            # 7. SL % (Distance from base as % of base)
            if s_type == 'FIXED':
                # Entry→stop distance as % of entry (the implicit ATR equivalent)
                dist = max(0.0, stop_base - final_sl)
                position.sl_pct_base = (dist / stop_base * 100) if stop_base > 0 else 0
            else:
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
            
            if atr_dist_price < CONFLUENCE_ATR_THRESHOLD:
                strength_score += 1
                confluence_zones.append({
                    "type": "ENTRY",
                    "dma": dma_name,
                    "dma_val": dma_val,
                    "atr_distance": atr_dist_price,
                    "pct_distance": (dist_to_price / price) * 100 if price > 0 else 0,
                    "is_fortress": atr_dist_price < CONFLUENCE_FORTRESS_THRESHOLD
                })
                
            # Check Stop Confluence
            dist_to_stop = abs(stop_price - dma_val)
            atr_dist_stop = dist_to_stop / atr
            
            if atr_dist_stop < CONFLUENCE_ATR_THRESHOLD:
                strength_score += 1
                confluence_zones.append({
                    "type": "STOP",
                    "dma": dma_name,
                    "dma_val": dma_val,
                    "atr_distance": atr_dist_stop,
                    "pct_distance": (dist_to_stop / stop_price) * 100 if stop_price > 0 else 0,
                    "is_fortress": atr_dist_stop < CONFLUENCE_FORTRESS_THRESHOLD
                })
                
        return {
            "strength": strength_score,
            "zones": confluence_zones
        }

def _fetch_price_data(yf_ticker, conid, entry_date_str, entry_price, price_service):
    """
    Fetches current price, max-since-entry, and daily OHLCV.
    Returns (effective_entry, max_price, current_price, df_daily).
    df_daily is the full daily history for prospects (used to resample in _compute_atr_rows),
    or None for conid-based positions (PriceService handles caching there).
    """
    if conid:
        df_daily = price_service.fetch_and_store(conid, yf_ticker)
    else:
        # Single max-history fetch; resampled in _compute_atr_rows to avoid 4 round-trips.
        df_daily = yf.Ticker(yf_ticker).history(period="max")

    if df_daily.empty:
        return None

    current_price = df_daily['Close'].iloc[-1]

    if conid:
        max_price = price_service.highest_high_since(conid, entry_date_str) or entry_price
        df_daily_out = None  # PriceService owns the cache; callers use get_prices()
    else:
        try:
            entry_dt = pd.to_datetime(entry_date_str)
            if df_daily.index.tz:
                entry_dt = entry_dt.tz_localize(df_daily.index.tz)
            df_since = df_daily[df_daily.index >= entry_dt]
            max_price = df_since['High'].max() if not df_since.empty else entry_price
        except Exception:
            max_price = entry_price
        df_daily_out = df_daily

    # Prospect: if entry unknown, assume buying at market
    effective_entry = entry_price if entry_price > 0 else current_price
    max_price = max(effective_entry, max_price)

    return effective_entry, max_price, current_price, df_daily_out


_RESAMPLE_RULES = {'weekly': 'W', 'monthly': 'ME', 'quarterly': 'QE'}
_RESAMPLE_AGG = {'Open': ('Open', 'first'), 'High': ('High', 'max'),
                 'Low': ('Low', 'min'), 'Close': ('Close', 'last'), 'Volume': ('Volume', 'sum')}


def _resample_ohlcv(df_daily: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df_daily.resample(rule).agg(**_RESAMPLE_AGG).dropna(subset=['Close'])


def _compute_atr_rows(yf_ticker, conid, effective_entry, max_price, current_price,
                      multiplier, inst_multiplier, qty, total_nav, max_r_pct, max_exp_pct,
                      price_service, df_prospect_daily=None):
    """Computes ATRDiscoveryRow objects for all timeframes and stop types."""
    intervals = [
        ("14d", 14, 'daily'),
        ("12w", 12, 'weekly'),
        ("12m", 12, 'monthly'),
        ("12q", 12, 'quarterly'),
    ]

    results = []
    for label, window, tf in intervals:
        if conid:
            df = price_service.get_prices(conid, timeframe=tf)
        else:
            # Resample the already-fetched daily history — no additional HTTP calls.
            if df_prospect_daily is None or df_prospect_daily.empty:
                continue
            if tf == 'daily':
                df = df_prospect_daily
            else:
                df = _resample_ohlcv(df_prospect_daily, _RESAMPLE_RULES[tf])

        if len(df) < 2:
            continue

        actual_window = min(window, len(df) - 1)
        df['PrevClose'] = df['Close'].shift(1)
        df['TR'] = np.maximum(
            df['High'] - df['Low'],
            np.maximum(abs(df['High'] - df['PrevClose']), abs(df['Low'] - df['PrevClose']))
        )
        atr_wilder = df['TR'].ewm(com=actual_window - 1, min_periods=actual_window, adjust=False).mean().iloc[-1]
        atr_sma = df['TR'].rolling(window=actual_window).mean().iloc[-1]
        final_wilder = atr_wilder * multiplier

        for s_type in ('FIXED', 'TRAILING'):
            base_price = max_price if s_type == 'TRAILING' else effective_entry
            stop_price = base_price - final_wilder
            atr_pct = (final_wilder / base_price * 100) if base_price > 0 else 0

            calc_qty = qty
            if calc_qty == 0 and total_nav > 0:
                risk_dist = abs(effective_entry - stop_price) * inst_multiplier
                risk_q = (total_nav * (max_r_pct / 100.0)) / risk_dist if risk_dist > 0 else float('inf')
                exp_q = (total_nav * (max_exp_pct / 100.0)) / (effective_entry * inst_multiplier) if effective_entry > 0 else 0
                calc_qty = int(min(risk_q, exp_q))

            risk_amt = (effective_entry - stop_price) * calc_qty * inst_multiplier
            results.append(ATRDiscoveryRow(
                label=label,
                stop_type=s_type,
                atr_wilder=final_wilder,
                atr_sma=atr_sma * multiplier,
                stop_price=stop_price,
                atr_base_pct=atr_pct,
                pl_at_stop=(stop_price - effective_entry) * calc_qty * inst_multiplier,
                buffer_pct=((current_price - stop_price) / current_price * 100) if current_price > 0 else 0,
                pl_pct_nav=(risk_amt / total_nav * 100) if total_nav > 0 else 0,
                qty=calc_qty,
            ))

    return results


def get_atr_discovery_data(ticker_symbol, entry_date_str, entry_price, multiplier=1.0, conid=None,
                           qty=0.0, inst_multiplier=1.0, total_nav=0.0, max_r_pct=1.0,
                           max_exp_pct=5.0, mapper=None):
    """
    Returns raw ATR analysis data for both FIXED and TRAILING stop types.
    Pass mapper= to avoid a redundant PortfolioManager instantiation when the caller already holds one.
    """
    try:
        if mapper is None:
            from .portfolio_manager import PortfolioManager
            mapper = PortfolioManager().mapper

        yf_ticker = mapper.resolve_yf_ticker(ticker_symbol, conid=conid)
        price_service = PriceService()

        price_data = _fetch_price_data(yf_ticker, conid, entry_date_str, entry_price, price_service)
        if price_data is None:
            return None
        effective_entry, max_price, current_price, df_prospect_daily = price_data

        rows = _compute_atr_rows(
            yf_ticker, conid, effective_entry, max_price, current_price,
            multiplier, inst_multiplier, qty, total_nav, max_r_pct, max_exp_pct,
            price_service, df_prospect_daily=df_prospect_daily,
        )

        trend_data = price_service.get_trend_analysis(
            conid if conid else f"PROSPECT:{ticker_symbol}", yf_ticker
        )

        return {
            'ticker': ticker_symbol,
            'entry_price': effective_entry,
            'max_price': max_price,
            'current_price': current_price,
            'rows': rows,
            'max_r_pct': max_r_pct,
            'max_exp_pct': max_exp_pct,
            'trend_data': trend_data,
        }
    except Exception as e:
        logger.error(f"ATR Discovery Data Error: {e}")
        return None
