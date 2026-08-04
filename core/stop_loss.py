import pandas as pd
import numpy as np
import yfinance as yf
from models import Position, ATRDiscoveryRow
from db import update_high_water_mark
from services.price_service import PriceService
from logger import logger
from constants import RISK_RED_MULTIPLIER, EXPOSURE_RED_MULTIPLIER, TP_ATR_MULTIPLE, ATR_DISCOVERY_INTERVALS
from .profit_taking import compute_exit_milestones
from .sizing import compute_position_size
from .exit_shapes import normalize_shape, suppresses_price_target


def audit_position_risk(
    current_price: float, stop: float, entry_price: float, qty: float,
    multiplier: float, nav: float, max_r_pct: float = 1.0,
    max_exp_pct: float = 5.0, fx_rate: float = 1.0,
) -> dict:
    """
    Evaluate a position against two hard limits: Risk-at-Stop and Total Market Exposure.
    Returns remaining capital budget for both constraints.
    HCM (Higher of Cost or Market) is used for exposure. All values normalized to NAV currency.

    Every return carries the SAME keys, including the degraded `nav <= 0` path — a
    partial dict is how a caller ends up raising KeyError on a failed NAV download
    (`fetch_nav_data` returns 0.0 when the IBKR Flex fetch fails). Consumers must
    check `nav_known` before showing any percentage: with no NAV the R and exposure
    figures are 0.0 as a placeholder, and 0.0 read as a real reading means "no risk",
    which is the opposite of "unknown".

    `status_color` ∈ {GREEN, YELLOW, RED, GRAY}; GRAY means "not assessable".
    """
    if nav <= 0:
        # NAV unknown: percentages are undefined, but the stop breach is not — it is
        # a pure price comparison and remains the most important thing on the panel.
        breached = bool(current_price and current_price <= stop)
        return {
            "status_color": "RED" if breached else "GRAY",
            "current_risk_pct": 0.0,
            "current_exposure_pct": 0.0,
            "risk_budget_rem": 0.0,
            "exposure_budget_rem": 0.0,
            "adjustment": 0.0,        # no NAV, no sizing — never suggest a trade
            "is_breached": breached,
            "max_r_pct": max_r_pct,
            "max_exp_pct": max_exp_pct,
            "stop_to_restore": None,
            "shares_to_trim": None,
            "nav_known": False,
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
        "nav_known": True,
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
    tp_mult_override = getattr(profile, 'tp_atr_mult', None)

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
    # Carry the THESIS/TECHNICAL tag through (§0a). No exit logic branches on it yet.
    position.classification = getattr(profile, 'classification', '') or ''
    # Carry the exit shape (§5a). Unset → LADDER, which reproduces today's behaviour.
    position.exit_shape = normalize_shape(getattr(profile, 'exit_shape', None))

    # 2. Ratchet Rule (High-Water Mark)
    final_sl = max(calculated_sl, highest_sl)
    if final_sl > highest_sl:
        update_high_water_mark(position.conid, final_sl)
    position.sl_price = final_sl

    # 3. Take Profit
    # TP = entry + 3 × R, where R is the ORIGINAL risk unit (inception ATR) for BOTH
    # stop types, so the ladder is uniform (M1=+1R, M2=+2R, TP=+3R from entry) and
    # measures profit in R-multiples. For TRAILING this deliberately uses the inception
    # ATR, not the live trailing distance: anchoring to live ATR makes the milestones
    # drift away as volatility expands (e.g. AVGO live ATR 88 vs inception 57 pushed M1
    # to entry+88). The live ATR governs only where the trailing STOP sits, not the
    # reward ladder. In a confirmed trend the user manually extends TP via TP-stage guidance.
    if inception_atr and inception_atr > 0:
        atr_for_tp = inception_atr
    else:
        atr_for_tp = max(0.0, (position.entry_price or 0.0) - final_sl)
        if atr_for_tp > 0:
            logger.warning(
                f"[calculate_position_risk] {position.ticker}: inception_atr missing, "
                f"using entry-stop distance {atr_for_tp:.4f} for TP/milestones"
            )
    # Per-position TP override extends the target to any multiple of the SAME frozen inception
    # ATR (e.g. 4R, 5R). M1/M2 below always stay at +1R/+2R, so the override only lifts the top
    # rung. None/0 → default 3R. The override never touches the live stop ATR.
    tp_mult = float(tp_mult_override) if (tp_mult_override and tp_mult_override > 0) else TP_ATR_MULTIPLE
    position.tp_is_override = bool(tp_mult_override and tp_mult_override > 0)
    position.tp_atr_mult = tp_mult
    position.tp_price = (position.entry_price + tp_mult * atr_for_tp) if atr_for_tp > 0 else None
    # Exit shape (§5a): a THESIS trade carries no guessed-at-entry price target — it exits
    # on thesis/stop only. Drop the target so the target-driven ladder/exit-stage stays quiet
    # (up_pct, reward_val, rr and exit_stage all fall to their no-target branches below).
    # Any other shape (incl. the default) keeps today's target untouched.
    if suppresses_price_target(position.exit_shape):
        position.tp_price = None

    # 4. Percentage Metrics
    if position.current_price > 0:
        position.down_pct = (position.current_price - position.sl_price) / position.current_price * 100
        if position.tp_price:
            position.up_pct = (position.tp_price - position.current_price) / position.current_price * 100

    # 5. Outcome at Stop / Target
    position.risk_val = (position.sl_price - position.entry_price) * position.qty * position.multiplier
    # Live P/L at exit: while price holds at/above the stop this equals the planned stop-out
    # (risk_val); once price breaches the stop the realisable exit is the live price, so the
    # figure degrades with price and snaps back to risk_val on reclaim. For TRAILING, new highs
    # ratchet the stop up, lifting risk_val itself (handled in step 2 via the high-water mark).
    effective_exit = (
        min(position.sl_price, position.current_price)
        if position.current_price and position.current_price > 0
        else position.sl_price
    )
    position.risk_val_live = (effective_exit - position.entry_price) * position.qty * position.multiplier
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

    # 8. Exit milestones — same R unit as TP (inception ATR) for both stop types, so the
    # ladder reflects profit in units of original risk rather than drifting with live vol.
    atr_dist = atr_for_tp
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
                      price_service, df_prospect_daily=None, fx_rate=1.0):
    """Computes ATRDiscoveryRow objects for all timeframes and stop types."""
    intervals = ATR_DISCOVERY_INTERVALS
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
                    total_nav, effective_entry, stop_price, inst_multiplier, max_r_pct, max_exp_pct,
                    fx_rate=fx_rate,
                )

            # Local (asset-ccy) risk; converted by fx_rate only where it meets NAV.
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
                pl_pct_nav=(risk_amt * fx_rate / total_nav * 100) if total_nav > 0 else 0,
                qty=calc_qty,
                window_shrunk=actual_window < window,
            ))

    return results


def snap_inception_atr(rows, risk_dist):
    """Nearest trustworthy discovery ATR to the risk distance (entry − stop), deduped
    by timeframe label. Rows whose ATR window was shrunken by thin history are
    excluded — a '12q' value from 3 quarterly bars is not a quarterly ATR and must
    never be frozen as a position's inception R unit.

    Single source of the FIXED-stop snap rule: the live commit path
    (ui/risk_workspace.py) and the retroactive migration tool
    (tools/migrate_fixed_inception_atr.py) both call this so they cannot diverge.
    Returns (atr, label), or (None, None) when nothing trustworthy remains.
    """
    choices = {r.label: r.atr_wilder for r in (rows or []) if not r.window_shrunk}
    if not choices or risk_dist <= 0:
        return None, None
    label = min(choices, key=lambda k: abs(choices[k] - risk_dist))
    return choices[label], label


def get_atr_discovery_data(
    ticker_symbol, entry_date_str, entry_price, multiplier=1.0, conid=None,
    qty=0.0, inst_multiplier=1.0, total_nav=0.0, max_r_pct=1.0,
    max_exp_pct=5.0, mapper=None, max_since_entry: float = 0.0,
    fx_rate: float = 1.0,
):
    """
    Returns ATR analysis data for both FIXED and TRAILING stop types across all timeframes.
    Pass mapper= to avoid a redundant PortfolioManager instantiation when the caller already holds one.
    Pass max_since_entry= (from position enrichment) to ensure the TRAILING base matches the
    portfolio risk status, which uses max(prices.db high, live intraday price).
    Pass fx_rate= (asset ccy -> NAV ccy) so prospect sizing and pl_pct_nav are risked
    against the real base-currency budget; 1.0 = same currency.
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
        if max_since_entry > max_price:
            max_price = max_since_entry

        rows = _compute_atr_rows(
            yf_ticker, conid, effective_entry, max_price, current_price,
            multiplier, inst_multiplier, qty, total_nav, max_r_pct, max_exp_pct,
            price_service, df_prospect_daily=df_prospect_daily, fx_rate=fx_rate,
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
