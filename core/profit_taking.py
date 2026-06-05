import traceback
from models import Position
from logger import logger
from constants import REGIME_REVERSAL_CONFIRM_DAYS

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
        "Target reached but the trend is not confirmed. Take meaningful profits. "
        "Keep a runner only if the RR ratio is still above 1.0 — if it has fallen below 1.0, "
        "the efficiency floor overrides this and you should exit entirely."
    )),
    ('TP', 'RANGING'): (1.00, (
        "Target reached with no structural support. The position has done its job. "
        "There is no trend to ride further — exit in full and redeploy capital elsewhere."
    )),
}


def classify_regime(direction: str, dma_days: int, price_above_dma: bool) -> str:
    """Pure 200-DMA regime decision. See TECHNICAL_DOCS §5.

    - TREND:   DMA rising ≥ 21d AND price above the 200-DMA.
    - NORMAL:  DMA rising 10–20d; a ≥21d rise while price is below the DMA (pullback);
               or an unconfirmed reversal (< REGIME_REVERSAL_CONFIRM_DAYS down) held by hysteresis.
    - RANGING: a confirmed decline, or a rise shorter than 10d.

    The day count resets to ~1 on any reversal, so the hysteresis branch is what keeps a
    single counter-trend day from crashing a long TREND straight to RANGING.
    """
    if direction == 'UP' and dma_days >= 21 and price_above_dma:
        return "TREND"
    if direction == 'UP' and dma_days >= 10:
        return "NORMAL"
    if direction == 'DOWN' and dma_days < REGIME_REVERSAL_CONFIRM_DAYS:
        return "NORMAL"  # unconfirmed reversal — hysteresis hold
    return "RANGING"


def compute_exit_milestones(position: Position, atr_dist: float) -> None:
    """Sets m1_price, m2_price, and exit_stage on position based on ATR distance from entry."""
    if atr_dist <= 0 or not position.entry_price:
        return
    position.m1_price = position.entry_price + atr_dist
    position.m2_price = position.entry_price + 2.0 * atr_dist
    cur = position.current_price if position.current_price > 0 else position.mark_price
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


def enrich_regime(positions: list[Position], mapper) -> None:
    """Sets trend_regime per position based on 200-DMA consecutive rising days.
    TREND >= 21d, NORMAL 10-20d, RANGING < 10d or declining.
    """
    from services.price_service import PriceService
    ps = PriceService()
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
            dma_trend = trend.get('dma200_trend', {})
            dma_signal = dma_trend.get('signal', 'NEUTRAL')
            dma_days = dma_trend.get('consecutive_days', 0)
            direction = dma_trend.get('direction', 'DOWN')
            dmas = trend.get('dmas', {})
            p.regime_dma200 = round(float(dmas.get('DMA200', 0.0) or 0.0), 4)
            p.regime_dma = f"{dma_signal} ({dma_days}d)"
            p.regime_dma_signal = dma_signal
            p.regime_dma_days = dma_days
            p.regime_dma_direction = direction
            # Gate TREND on price being above the 200-DMA: a rising DMA with price
            # already below it indicates a pullback — full trend trim is too aggressive.
            price_above_dma = (
                (p.current_price or p.mark_price) > p.regime_dma200
                if p.regime_dma200 > 0 else True
            )
            p.trend_regime = classify_regime(direction, dma_days, price_above_dma)
        except Exception as e:
            logger.warning(f"[enrich_regime] {p.ticker} (conid={p.conid}): {e}\n{traceback.format_exc()}")
