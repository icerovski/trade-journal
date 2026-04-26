from constants import CONFLUENCE_ATR_THRESHOLD, CONFLUENCE_FORTRESS_THRESHOLD


def evaluate_confluence(price: float, stop_price: float, dmas: dict, atr: float) -> dict:
    """
    Evaluates Volatility-Adjusted Confluence based on Daily ATR.
    Returns strength score and list of confluence zones for price and stop.
    """
    if atr <= 0 or not dmas:
        return {"strength": 0, "zones": []}

    confluence_zones = []
    strength_score = 0

    for dma_name, dma_val in dmas.items():
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
