"""Entry/exit zone scanner — the orchestrator.

Ties together the composite volume profile, anchored VWAP, and moving averages
into a single confluence read per ticker, then converts a flagged zone into a
stop and position size under each risk preset. Targets and sizing stay on the
app's existing framework (dual R%/exposure constraints; reward anchored to
RR_SETUP_FLOOR), NOT the brief's 5:1.

I/O is injected: callers pass a `price_loader` (ticker spec -> OHLCV DataFrame),
NAV, and the preset table, so the orchestration logic stays pure and testable.
The volume profile is a daily-bar approximation — surface that in any output.
"""

import math

import pandas as pd

from constants import (
    ATR_FALLBACK_MULT,
    DMA_LONG_WINDOW,
    DMA_SHORT_WINDOW,
    GAP_MIN_ATR,
    HVN_MIN_PROMINENCE,
    MICRO_LOOKBACK_DAYS,
    MICRO_STOP_BUFFER_ATR,
    MOMENTUM_VAL_PREMIUM_PCT,
    RR_SETUP_FLOOR,
    SCANNER_ATR_WINDOW,
    TRADING_DAYS_PER_MONTH,
    VP_LOOKBACKS_MONTHS,
    ZONE_CONFLUENCE_PCT,
    ZONE_MIN_CONFLUENCE,
)
from core.anchored_vwap import anchored_vwap, compute_anchored_vwaps
from core.confluence import evaluate_confluence
from core.sizing import compute_position_size
from core.volume_profile import (
    compute_volume_profile,
    find_high_volume_nodes,
    find_naked_pocs,
)


def _wilder_atr(ohlcv: pd.DataFrame, window: int = SCANNER_ATR_WINDOW) -> float:
    """Wilder ATR via the same EWM method as core/stop_loss.py (com=window-1,
    adjust=False) so the scanner's volatility yardstick matches the rest of the app.
    """
    high, low, close = ohlcv["high"], ohlcv["low"], ohlcv["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(com=window - 1, min_periods=window, adjust=False).mean()
    val = atr.iloc[-1]
    return float(val) if pd.notna(val) else 0.0


def _slice_months(df: pd.DataFrame, months: int) -> pd.DataFrame:
    """Trailing `months` of bars. Uses the date column when present, else falls
    back to ~21 trading days per month.
    """
    if "date" in df.columns:
        last = pd.to_datetime(df["date"].iloc[-1])
        start = last - pd.DateOffset(months=months)
        return df[pd.to_datetime(df["date"]) >= start]
    return df.tail(int(months * TRADING_DAYS_PER_MONTH))


def _build_levels(df: pd.DataFrame, lookbacks) -> tuple[dict, list]:
    """Assemble the structural level map (DMAs + VP VAL/VAH/POC per lookback +
    AVWAPs) and collect naked POCs across the lookbacks for targeting.
    """
    levels: dict = {}
    naked_all: list = []

    close = df["close"]
    if len(close) >= DMA_LONG_WINDOW:
        levels[f"DMA{DMA_LONG_WINDOW}"] = float(close.tail(DMA_LONG_WINDOW).mean())
    if len(close) >= DMA_SHORT_WINDOW:
        levels[f"DMA{DMA_SHORT_WINDOW}"] = float(close.tail(DMA_SHORT_WINDOW).mean())

    for months in lookbacks:
        sub = _slice_months(df, months)
        prof = compute_volume_profile(sub)
        if prof:
            tag = f"{months}mo"
            levels[f"VAL_{tag}"] = prof["val"]
            levels[f"VAH_{tag}"] = prof["vah"]
            levels[f"POC_{tag}"] = prof["poc"]
            naked_all.extend(find_naked_pocs(sub, prof))

    avwaps = compute_anchored_vwaps(df)
    if avwaps["low_anchor"]:
        levels["AVWAP_low"] = avwaps["low_anchor"]["vwap"]
    if avwaps["high_anchor"]:
        levels["AVWAP_high"] = avwaps["high_anchor"]["vwap"]

    return levels, naked_all


def _nearest_support(levels: dict, price: float) -> tuple[float | None, str | None]:
    """Tightest invalidating level below price for a long: the closest VAL or
    anchored-VWAP support under the current price. Returns (price, source_name).
    """
    candidates = {
        name: val for name, val in levels.items()
        if (name.startswith("VAL") or name == "AVWAP_low") and val < price
    }
    if not candidates:
        return None, None
    name = max(candidates, key=candidates.get)  # nearest below = largest value < price
    return candidates[name], name


def _breakout_gap_floor(
    micro: pd.DataFrame, price: float, atr: float, gap_min_atr: float
) -> float | None:
    """Floor of the most recent significant up-gap in the window, if it sits below
    price. An up-gap (a bar whose low is above the prior bar's high) leaves an
    unfilled shelf; the pre-gap high is the floor where a clean fill of the gap
    breaks the momentum. Only gaps of at least `gap_min_atr` daily-ATRs count, and
    the floor (not the gap top) is returned so a partial fill doesn't shake out.

    Returns the floor price, or None if there is no qualifying gap below price.
    """
    if micro is None or len(micro) < 2 or atr <= 0:
        return None

    highs = micro["high"].to_numpy(dtype=float)
    lows = micro["low"].to_numpy(dtype=float)
    min_gap = gap_min_atr * atr

    # Walk from the most recent bar backward — the latest qualifying gap wins.
    for i in range(len(micro) - 1, 0, -1):
        floor = highs[i - 1]
        if lows[i] - floor >= min_gap and floor < price:
            return float(floor)
    return None


def _micro_support(
    ohlcv: pd.DataFrame, price: float, atr: float, micro_days: int, buffer_atr: float,
    *, gap_min_atr: float = GAP_MIN_ATR, hvn_min_prominence: float = HVN_MIN_PROMINENCE,
) -> tuple[float | None, str | None]:
    """Short-term support for a momentum-flag entry, from the last `micro_days`
    bars. Four anchor types are considered below price:
      - VAL:   the micro volume-profile value-area low,
      - HVN:   the nearest high-volume node (heavier shelf than the VAL edge),
      - AVWAP: anchored to the most recent swing low (the lowest low in the window),
      - GAP:   the floor of the most recent significant breakout gap.
    The nearest of those below price wins (tightest), and the stop sits `buffer_atr`
    daily-ATRs beneath it — a clean break of that level means the parabolic move
    is broken.

    Returns (stop_price, source_label) or (None, None) if no micro support exists
    below price (e.g. price is sitting on the micro low).
    """
    micro = ohlcv.tail(micro_days)
    if micro.empty:
        return None, None

    candidates: dict[str, float] = {}

    prof = compute_volume_profile(micro)
    if prof:
        if prof["val"] < price:
            candidates[f"VAL_{micro_days}d"] = prof["val"]
        # Nearest high-volume node below price — a heavier shelf than the VAL edge.
        hvns_below = [n["price"] for n in find_high_volume_nodes(prof, hvn_min_prominence) if n["price"] < price]
        if hvns_below:
            candidates[f"HVN_{micro_days}d"] = max(hvns_below)

    anchor_pos = int(micro["low"].to_numpy().argmin())  # most recent swing low in window
    av = anchored_vwap(micro.reset_index(drop=True), anchor_pos)
    if math.isfinite(av) and av < price:
        candidates[f"AVWAP_{micro_days}d"] = av

    gap_floor = _breakout_gap_floor(micro, price, atr, gap_min_atr)
    if gap_floor is not None:
        candidates[f"GAP_{micro_days}d"] = gap_floor

    if not candidates:
        return None, None

    name = max(candidates, key=candidates.get)  # nearest below price = tightest
    stop = candidates[name] - buffer_atr * atr
    return stop, name


def scan_ticker(
    ohlcv: pd.DataFrame,
    nav: float,
    presets: dict,
    *,
    ticker: str = "",
    multiplier: float = 1.0,
    current_price: float | None = None,
    lookbacks=VP_LOOKBACKS_MONTHS,
    atr_window: int = SCANNER_ATR_WINDOW,
    min_confluence: int = ZONE_MIN_CONFLUENCE,
    confluence_pct: float = ZONE_CONFLUENCE_PCT,
    reward_mult: float = RR_SETUP_FLOOR,
    momentum_premium: float = MOMENTUM_VAL_PREMIUM_PCT,
    micro_days: int = MICRO_LOOKBACK_DAYS,
    micro_buffer_atr: float = MICRO_STOP_BUFFER_ATR,
    calibration=None,
) -> dict | None:
    """Scan one ticker for an entry zone. Returns a result dict (always, when
    there is enough data), with `flagged` indicating whether a zone fired and
    stop/target/sizes populated only when it did. Returns None if data is too thin.

    `calibration` (core.calibration.CalibrationProfile) is the horizon lens. When
    given, it OVERRIDES the horizon knobs (atr_window, lookbacks, momentum_premium,
    micro window/buffer, confluence band) and the MOMENTUM behaviour. The default
    (None, or the DEFAULT_CALIBRATION profile) reproduces today's short-swing scan
    exactly. The 3–6mo profile disables the tight micro-stop, so a MOMENTUM flag falls
    back to the weekly value anchors instead of the 14-bar micro structure.
    """
    use_micro_momentum_stop = True
    if calibration is not None:
        atr_window = calibration.atr_window
        lookbacks = calibration.lookbacks
        momentum_premium = calibration.momentum_premium
        micro_days = calibration.micro_days
        micro_buffer_atr = calibration.micro_buffer_atr
        confluence_pct = calibration.confluence_pct
        use_micro_momentum_stop = calibration.use_micro_momentum_stop

    if ohlcv is None or len(ohlcv) < atr_window + 1:
        return None

    price = current_price if current_price is not None else float(ohlcv["close"].iloc[-1])
    atr = _wilder_atr(ohlcv, atr_window)
    # NaN fails every comparison silently, so check finiteness explicitly.
    if not math.isfinite(price) or not math.isfinite(atr) or atr <= 0 or price <= 0:
        return None

    levels, naked_all = _build_levels(ohlcv, lookbacks)
    if not levels:
        return None

    # Regime: when price has run far above the 6mo VAL, that support is too distant
    # for a momentum-flag entry. Switch to a micro-structure stop from recent bars.
    val_6mo = levels.get("VAL_6mo")
    regime = (
        "MOMENTUM"
        if val_6mo is not None and price > val_6mo * (1 + momentum_premium)
        else "NORMAL"
    )

    stop_price, stop_source = None, None
    # MOMENTUM override (3–6mo lens): when the profile disables the micro-stop, a
    # momentum flag means "extended — wait for a weekly pullback", so we skip the tight
    # micro structure and fall through to the weekly value anchors (_nearest_support).
    if regime == "MOMENTUM" and use_micro_momentum_stop:
        stop_price, stop_source = _micro_support(
            ohlcv, price, atr, micro_days, micro_buffer_atr
        )
    if stop_price is None:
        stop_price, stop_source = _nearest_support(levels, price)
    if stop_price is None:
        # No structural support below price: fall back to a 1-ATR stop so the
        # zone can still be sized, and flag the weaker basis.
        stop_price, stop_source = price - ATR_FALLBACK_MULT * atr, "ATR(1)"

    # Express the percent confluence band in ATR units for the engine.
    threshold = (confluence_pct * price) / atr
    conf = evaluate_confluence(price, stop_price, levels, atr, threshold=threshold)

    entry_signals = [z for z in conf["zones"] if z["type"] == "ENTRY"]
    flagged = len(entry_signals) >= min_confluence
    nearest = min(conf["levels"], key=lambda l: l["price_pct"]) if conf["levels"] else None

    result = {
        "ticker": ticker,
        "price": price,
        "atr": atr,
        "flagged": flagged,
        "regime": regime,
        "tag": ("ZONE-MOMO" if regime == "MOMENTUM" else "ZONE") if flagged else None,
        "levels": levels,
        "entry_signals": entry_signals,
        "dist_to_zone_pct": nearest["price_pct"] if nearest else None,
    }

    if not flagged:
        return result

    risk_per_share = price - stop_price
    naked_above = sorted(n["price"] for n in naked_all if n["price"] > price)
    target = naked_above[0] if naked_above else price + reward_mult * risk_per_share

    sizes = {}
    for key, p in presets.items():
        qty = compute_position_size(
            nav, price, stop_price, multiplier, p["max_r_pct"], p["max_exp_pct"]
        )
        sizes[key] = {
            "label": p.get("label", key),
            "qty": qty,
            "max_r_pct": p["max_r_pct"],
            "max_exp_pct": p["max_exp_pct"],
        }

    result.update({
        "stop": stop_price,
        "stop_source": stop_source,
        "stop_pct": (risk_per_share / price * 100.0) if price > 0 else 0.0,
        "target": target,
        "target_from_naked_poc": bool(naked_above),
        "risk_per_share": risk_per_share,
        "sizes": sizes,
    })
    return result


def build_zone_report(universe, price_loader, nav: float, presets: dict, **kwargs) -> list[dict]:
    """Scan a universe of tickers. `universe` is an iterable of dicts with at
    least 'ticker' (optionally 'conid', 'multiplier', 'price'); `price_loader` is
    a callable receiving each item and returning its OHLCV DataFrame.

    Results are sorted flagged-first, then by proximity to the nearest level.
    """
    results = []
    for item in universe:
        ohlcv = price_loader(item)
        r = scan_ticker(
            ohlcv, nav, presets,
            ticker=item.get("ticker", ""),
            multiplier=item.get("multiplier", 1.0),
            current_price=item.get("price"),
            **kwargs,
        )
        if r is not None:
            results.append(r)

    results.sort(key=lambda r: (not r["flagged"], r["dist_to_zone_pct"] if r["dist_to_zone_pct"] is not None else 1e9))
    return results
