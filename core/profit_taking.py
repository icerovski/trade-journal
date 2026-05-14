import traceback
from models import Position
from logger import logger

# Trim guidance matrix: (exit_stage, trend_regime) → (trim_fraction, display_description).
# Lives here (strategy layer) so the UI imports it rather than owning strategy decisions.
TRIM_MATRIX = {
    ('M2', 'TREND'):   (0.15, "Token trim 15% — preserve trend runway"),
    ('M2', 'NORMAL'):  (0.33, "Trim 33%"),
    ('M2', 'RANGING'): (0.50, "Trim 50% — protect gains"),
    ('TP', 'TREND'):   (0.20, "Trim 20% — raise TP to weekly ATR level"),
    ('TP', 'NORMAL'):  (0.33, "Trim 33% or close; keep runner if RR > 1.0"),
    ('TP', 'RANGING'): (1.00, "Close position — no trend support"),
}


def compute_exit_milestones(position: Position, atr_dist: float) -> None:
    """Sets m1_price, m2_price, and exit_stage on position based on ATR distance from entry."""
    if atr_dist <= 0 or not position.entry_price:
        return
    position.m1_price = position.entry_price + atr_dist
    position.m2_price = position.entry_price + 2.0 * atr_dist
    cur = position.current_price if position.current_price > 0 else position.mark_price
    if cur > 0 and position.tp_price:
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
            # Gate TREND on price being above the 200-DMA: a rising DMA with price
            # already below it indicates a pullback — full trend trim is too aggressive.
            price_above_dma = (
                (p.current_price or p.mark_price) > p.regime_dma200
                if p.regime_dma200 > 0 else True
            )
            if direction == 'UP' and dma_days >= 21 and price_above_dma:
                p.trend_regime = "TREND"
            elif direction == 'UP' and dma_days >= 10:
                p.trend_regime = "NORMAL"
            else:
                p.trend_regime = "RANGING"
        except Exception as e:
            logger.warning(f"[enrich_regime] {p.ticker} (conid={p.conid}): {e}\n{traceback.format_exc()}")
