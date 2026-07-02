import traceback
from models import Position
from logger import logger
from constants import (
    REGIME_REVERSAL_CONFIRM_DAYS,
    REGIME_TREND_MIN_DAYS,
    REGIME_NORMAL_MIN_DAYS,
    REGIME_LENS_BANDS,
    MILESTONE_M1_MULT,
    MILESTONE_M2_MULT,
)

# Trim guidance matrix: (exit_stage, trend_regime) → (trim_fraction, rationale).
# Rationale explains WHY; the UI renders the share count and % separately.
# Lives here (strategy layer) so the UI imports it rather than owning strategy decisions.
TRIM_MATRIX = {
    # Fraction 0.0 = hold, do not trim. In a confirmed trend the trailing stop is the
    # exit mechanism; trimming here would cut a compounder. Profits are banked at TP.
    ('M2', 'TREND'):   (0.0, (
        "The 200-DMA has been rising for 21+ consecutive days with price above it — "
        "the trend has genuine structural support. Do not trim here: let the trailing "
        "stop run the winner and bank profits at the full target. Re-evaluate at TP."
    )),
    ('M2', 'NORMAL'):  (0.33, (
        "The trend is developing but not yet confirmed (DMA rising < 21 days). "
        "Take a meaningful portion of profits while the position still has room to run. "
        "Keep two thirds open; re-evaluate at TP."
    )),
    ('M2', 'RANGING'): (0.50, (
        "The 200-DMA is flat or declining — there is no structural support for a continuation. "
        "Protect half your gains now. Hold the remainder only if the trailing stop remains intact; "
        "exit at the first sign of further deterioration."
    )),
    ('TP', 'TREND'):   (0.20, (
        "Target hit inside a confirmed trend. Take a modest additional trim and let the stop "
        "carry the rest of the move — the stop, not a fixed target, is the ultimate exit. "
        "Do not close the core position."
    )),
    ('TP', 'NORMAL'):  (0.33, (
        "Target reached but the trend is not confirmed. Take meaningful profits (about a third). "
        "Keep a runner only while the trailing stop and your thesis hold — the stop, not the RR "
        "ratio, is the exit. (RR is shown for context only.)"
    )),
    ('TP', 'RANGING'): (1.00, (
        "Target reached with no structural support. The position has done its job. "
        "There is no trend to ride further — exit in full and redeploy capital elsewhere."
    )),
}


def classify_regime(
    direction: str,
    dma_days: int,
    price_above_dma: bool,
    trend_min_days: int = REGIME_TREND_MIN_DAYS,
    normal_min_days: int = REGIME_NORMAL_MIN_DAYS,
) -> str:
    """Pure DMA regime decision. See TECHNICAL_DOCS §5.

    Defaults are the 200-DMA thresholds (21d/10d) — unchanged behaviour. The horizon
    lens passes shorter confirmation windows for faster DMAs (constants.REGIME_LENS_BANDS).

    - TREND:   DMA rising ≥ trend_min_days AND price above the lens DMA.
    - NORMAL:  DMA rising normal_min_days..trend_min_days−1; a confirmed rise while price
               is below the DMA (pullback); or an unconfirmed reversal
               (< REGIME_REVERSAL_CONFIRM_DAYS down) held by hysteresis.
    - RANGING: a confirmed decline, or a rise shorter than normal_min_days.

    The day count resets to ~1 on any reversal, so the hysteresis branch is what keeps a
    single counter-trend day from crashing a long TREND straight to RANGING.
    """
    if direction == 'UP' and dma_days >= trend_min_days and price_above_dma:
        return "TREND"
    if direction == 'UP' and dma_days >= normal_min_days:
        return "NORMAL"
    if direction == 'DOWN' and dma_days < REGIME_REVERSAL_CONFIRM_DAYS:
        return "NORMAL"  # unconfirmed reversal — hysteresis hold
    return "RANGING"


def select_regime_lens(risk_unit: float, atr_daily: float) -> tuple[int, int, int]:
    """Pick the regime DMA window + confirmation thresholds for a trade's horizon.

    Time is a function of risk: the stop *declares* the horizon. `risk_unit` is the
    frozen inception ATR (≈ entry − stop scale, already snapped to a discovery
    timeframe for FIXED stops), measured here in daily-ATR multiples. A tight
    daily-ATR stop (e.g. a leveraged-ETF trade) is judged on the fast lens its
    lifetime actually spans; a wide monthly-ATR conviction hold keeps the
    structural 200-DMA read. Missing/zero inputs → structural lens (today's path).

    Returns (dma_window, trend_min_days, normal_min_days).
    """
    if risk_unit and atr_daily and risk_unit > 0 and atr_daily > 0:
        ratio = risk_unit / atr_daily
        for max_ratio, window, trend_min, normal_min in REGIME_LENS_BANDS:
            if ratio <= max_ratio:
                return window, trend_min, normal_min
    return 200, REGIME_TREND_MIN_DAYS, REGIME_NORMAL_MIN_DAYS


def compute_exit_milestones(position: Position, atr_dist: float) -> None:
    """Sets m1_price, m2_price, and exit_stage on position based on ATR distance from entry."""
    if atr_dist <= 0 or not position.entry_price:
        return
    position.m1_price = position.entry_price + MILESTONE_M1_MULT * atr_dist
    position.m2_price = position.entry_price + MILESTONE_M2_MULT * atr_dist
    cur = position.current_price if position.current_price > 0 else position.mark_price
    # Monotonicity guard: a TP override below the M2 milestone (< 2R) inverts the ladder.
    # The stage logic still resolves (reaching the target reads TP), but flag the unusual setup.
    if position.tp_price and position.tp_price <= position.m2_price and getattr(position, 'tp_is_override', False):
        logger.warning(
            f"[compute_exit_milestones] {position.ticker}: TP override {position.tp_price:.2f} "
            f"is at/below M2 {position.m2_price:.2f} (< 2R) — ladder is non-monotonic"
        )
    if not (cur > 0 and position.tp_price):
        logger.debug(
            f"[compute_exit_milestones] {position.ticker}: exit_stage not set "
            f"(current={cur}, tp_price={position.tp_price}) — profit-taking panel suppressed"
        )
        return
    if cur >= position.tp_price:
        position.exit_stage = "TP"
    elif cur >= position.m2_price:
        position.exit_stage = "M2"
    elif cur >= position.m1_price:
        position.exit_stage = "M1"
    else:
        position.exit_stage = "PRE-M1"


def enrich_regime(positions: list[Position], mapper, lens_mode: str = "default") -> None:
    """Sets trend_regime per position based on DMA consecutive rising days.

    lens_mode `default` (the `regime_lens` setting's default): the 200-DMA with
    TREND >= 21d, NORMAL 10-20d, RANGING < 10d or declining — today's behaviour.

    lens_mode `horizon`: the lens DMA and confirmation thresholds are picked per
    position from the stop's volatility horizon via select_regime_lens() — the
    inception ATR in daily-ATR14 multiples (tight daily-ATR stop → 50-DMA, weekly
    → 100-DMA, wider or missing data → the structural 200-DMA, unchanged).
    """
    from services.price_service import PriceService
    ps = PriceService()
    horizon = (lens_mode or "default").strip().lower() == "horizon"
    for p in positions:
        if not p.conid or p.qty <= 0:
            continue
        try:
            yf_ticker = mapper.resolve_yf_ticker(p.ticker, conid=p.conid)
            logger.info(f"[enrich_regime] {p.ticker} (conid={p.conid}) -> yf_ticker={yf_ticker!r}")
            trend = ps.get_trend_analysis(str(p.conid), yf_ticker)
            if trend.get('status') != 'OK':
                logger.warning(f"[enrich_regime] {p.ticker} (conid={p.conid}): status={trend.get('status')}")
                continue
            window, trend_min, normal_min = 200, REGIME_TREND_MIN_DAYS, REGIME_NORMAL_MIN_DAYS
            dma_trend = trend.get('dma200_trend', {})
            if horizon:
                risk_unit = float(p.inception_atr or 0.0)
                window, trend_min, normal_min = select_regime_lens(
                    risk_unit, float(trend.get('atr14_daily') or 0.0)
                )
                # Missing per-window trend (e.g. stale cache) → structural read.
                dma_trend = (trend.get('dma_trends') or {}).get(window) or dma_trend
            dma_signal = dma_trend.get('signal', 'NEUTRAL')
            dma_days = dma_trend.get('consecutive_days', 0)
            direction = dma_trend.get('direction', 'DOWN')
            dmas = trend.get('dmas', {})
            p.regime_dma200 = round(float(dmas.get('DMA200', 0.0) or 0.0), 4)
            # Name the lens in the display string only when it isn't the default 200.
            p.regime_dma = (
                f"{dma_signal} ({dma_days}d, DMA{window})" if window != 200
                else f"{dma_signal} ({dma_days}d)"
            )
            p.regime_dma_signal = dma_signal
            p.regime_dma_days = dma_days
            p.regime_dma_direction = direction
            p.regime_lens = window
            # Gate TREND on price being above the lens DMA: a rising DMA with price
            # already below it indicates a pullback — full trend trim is too aggressive.
            lens_dma_level = float(dmas.get(f'DMA{window}', 0.0) or 0.0) if window != 200 else p.regime_dma200
            price_above_dma = (
                (p.current_price or p.mark_price) > lens_dma_level
                if lens_dma_level > 0 else True
            )
            p.trend_regime = classify_regime(
                direction, dma_days, price_above_dma,
                trend_min_days=trend_min, normal_min_days=normal_min,
            )
        except Exception as e:
            logger.warning(f"[enrich_regime] {p.ticker} (conid={p.conid}): {e}\n{traceback.format_exc()}")
