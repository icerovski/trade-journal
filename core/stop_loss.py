import pandas as pd
import numpy as np
import yfinance as yf
from models import Position, ATRDiscoveryRow
from db import update_high_water_mark
from services.price_service import PriceService
from logger import logger
from constants import RISK_RED_MULTIPLIER, EXPOSURE_RED_MULTIPLIER, TP_ATR_MULTIPLE
from .profit_taking import compute_exit_milestones
from .sizing import compute_position_size


def audit_position_risk(
    current_price: float, stop: float, entry_price: float, qty: float,
    multiplier: float, nav: float, max_r_pct: float = 1.0,
    max_exp_pct: float = 5.0, fx_rate: float = 1.0,
) -> dict:
    """
    Evaluate a position against two hard limits: Risk-at-Stop and Total Market Exposure.
    Returns remaining capital budget for both constraints.
    HCM (Higher of Cost or Market) is used for exposure. All values normalized to NAV currency.
    """
    if nav <= 0:
        return {
            "status_color": "RED",
            "risk_budget_remaining": 0.0,
            "exposure_budget_remaining": 0.0,
            "is_breached": False,
        }

    risk_val = (entry_price - stop) * qty * multiplier * fx_rate
    exposure_val = max(entry_price, current_price) * qty * multiplier * fx_rate

    risk_pct = (risk_val / nav) * 100
    exposure_pct = (exposure_val / nav) * 100

    max_risk_cap = nav * (max_r_pct / 100.0)
    max_exposure_cap = nav * (max_exp_pct / 100.0)

    risk_budget_rem = max_risk_cap - risk_val
    exposure_budget_rem = max_exposure_cap - exposure_val

    # Mandate: use current_price for adding shares, entry_price for trimming.
    if risk_budget_rem > 0:
        risk_dist = abs(current_price - stop) * multiplier * fx_rate
    else:
        risk_dist = abs(entry_price - stop) * multiplier * fx_rate

    risk_adj = risk_budget_rem / risk_dist if risk_dist > 0 else float('inf')
    exp_adj = exposure_budget_rem / (current_price * multiplier * fx_rate) if current_price > 0 else 0
    adjustment = min(risk_adj, exp_adj)

    is_breached = current_price <= stop

    if is_breached or risk_pct > (max_r_pct * RISK_RED_MULTIPLIER) or exposure_pct > (max_exp_pct * EXPOSURE_RED_MULTIPLIER):
        status_color = "RED"
    elif risk_pct > max_r_pct or exposure_pct > max_exp_pct:
        status_color = "YELLOW"
    else:
        status_color = "GREEN"

    stop_to_restore = None
    shares_to_trim = None
    if risk_budget_rem < 0 and qty > 0:
        per_share = multiplier * fx_rate
        stop_to_restore = entry_price - (nav * (max_r_pct / 100.0)) / (qty * per_share)
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


def calculate_position_risk(position: Position, risk_settings: dict) -> Position:
    """
    Enriches a Position with stop loss, take profit, and efficiency metrics.
    Implements the Ratchet Rule: stop loss only moves in the trader's favour.
    """
    if str(position.conid) not in risk_settings:
        return position

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

    # 1. Base Stop Loss
    if s_type == 'FIXED':
        calculated_sl = atr
        stop_base = position.entry_price or max(position.current_price, position.mark_price)
    else:  # TRAILING
        hwm_proxy = max(position.entry_price, position.current_price, position.mark_price)
        stop_base = max(position.max_since_entry, hwm_proxy)
        if not stop_base or stop_base == 0:
            stop_base = hwm_proxy
        calculated_sl = stop_base - atr

    position.atr = atr
    position.stop_type = s_type
    position.entry_type = e_type
    position.scale_step = scale_step
    position.max_r_pct = max_r_pct
    position.max_exp_pct = max_exp_pct
    position.inception_stop = inception_stop
    position.inception_atr = inception_atr
    position.profile = getattr(profile, 'profile', None)

    # 2. Ratchet Rule (High-Water Mark)
    final_sl = max(calculated_sl, highest_sl)
    if final_sl > highest_sl:
        update_high_water_mark(position.conid, final_sl)
    position.sl_price = final_sl

    # 3. Take Profit
    # FIXED: anchor to entry so the ladder is M1=+1, M2=+2, TP=+3 ATRs from entry.
    # TRAILING: anchor to the current (ratcheted) stop so TP rises with the position.
    if s_type == 'FIXED':
        if inception_atr and inception_atr > 0:
            atr_for_tp = inception_atr
        else:
            atr_for_tp = max(0.0, (position.entry_price or 0.0) - final_sl)
            if atr_for_tp > 0:
                logger.warning(
                    f"[calculate_position_risk] {position.ticker}: inception_atr missing, "
                    f"using entry-stop distance {atr_for_tp:.4f} for TP"
                )
        position.tp_price = (position.entry_price + TP_ATR_MULTIPLE * atr_for_tp) if atr_for_tp > 0 else None
    else:
        position.tp_price = final_sl + (TP_ATR_MULTIPLE * atr)

    # 4. Percentage Metrics
    if position.current_price > 0:
        position.down_pct = (position.current_price - position.sl_price) / position.current_price * 100
        if position.tp_price:
            position.up_pct = (position.tp_price - position.current_price) / position.current_price * 100

    # 5. Outcome at Stop / Target
    position.risk_val = (position.sl_price - position.entry_price) * position.qty * position.multiplier
    position.reward_val = (
        (position.tp_price - position.entry_price) * position.qty * position.multiplier
        if position.tp_price else 0.0
    )

    # 6. RR Efficiency
    dist_to_stop = position.current_price - position.sl_price
    dist_to_target = (position.tp_price - position.current_price) if position.tp_price else 0.0
    position.rr_ratio = dist_to_target / dist_to_stop if dist_to_stop != 0 else 0.0

    # 7. SL % from base
    if s_type == 'FIXED':
        dist = max(0.0, stop_base - final_sl)
        position.sl_pct_base = (dist / stop_base * 100) if stop_base > 0 else 0
    else:
        position.sl_pct_base = (atr / stop_base * 100) if stop_base > 0 else 0

    # 8. Exit milestones
    if s_type == 'FIXED':
        atr_dist = inception_atr if (inception_atr and inception_atr > 0) \
                   else max(0.0, (position.entry_price or 0.0) - final_sl)
    else:
        atr_dist = atr
    compute_exit_milestones(position, atr_dist)

    return position


# ---------------------------------------------------------------------------
# ATR Discovery
# ---------------------------------------------------------------------------

def _fetch_price_data(yf_ticker, conid, entry_date_str, entry_price, price_service):
    """
    Fetches current price, max-since-entry, and daily OHLCV.
    Returns (effective_entry, max_price, current_price, df_daily) or None.
    df_daily is None for conid-based positions (PriceService owns the cache).
    """
    if conid:
        df_daily = price_service.fetch_and_store(conid, yf_ticker)
    else:
        # Single max-history fetch; resampled in _compute_atr_rows to avoid extra HTTP calls.
        df_daily = yf.Ticker(yf_ticker).history(period="max")

    if df_daily.empty:
        return None

    current_price = df_daily['Close'].iloc[-1]

    if conid:
        max_price = price_service.highest_high_since(conid, entry_date_str) or entry_price
        df_daily_out = None
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

    effective_entry = entry_price if entry_price > 0 else current_price
    max_price = max(effective_entry, max_price)
    return effective_entry, max_price, current_price, df_daily_out


_RESAMPLE_RULES = {'weekly': 'W', 'monthly': 'ME', 'quarterly': 'QE'}
_RESAMPLE_AGG = {
    'Open': ('Open', 'first'), 'High': ('High', 'max'),
    'Low': ('Low', 'min'), 'Close': ('Close', 'last'), 'Volume': ('Volume', 'sum'),
}


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
            if df_prospect_daily is None or df_prospect_daily.empty:
                continue
            df = df_prospect_daily if tf == 'daily' else _resample_ohlcv(df_prospect_daily, _RESAMPLE_RULES[tf])

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
                calc_qty = compute_position_size(
                    total_nav, effective_entry, stop_price, inst_multiplier, max_r_pct, max_exp_pct
                )

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


def get_atr_discovery_data(
    ticker_symbol, entry_date_str, entry_price, multiplier=1.0, conid=None,
    qty=0.0, inst_multiplier=1.0, total_nav=0.0, max_r_pct=1.0,
    max_exp_pct=5.0, mapper=None,
):
    """
    Returns ATR analysis data for both FIXED and TRAILING stop types across all timeframes.
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
