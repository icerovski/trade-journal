"""Volatility-adjusted confluence engine.

Scores how many independent structural levels cluster around the current price
and the stop, measured in ATR units (so the same thresholds apply across a $5
stock and a $5,000 one). `levels` is an open dict of label -> price: any mix of
DMAs/EMAs, composite volume-profile VAL/VAH/POC, and anchored VWAPs. One signal
is noise; a cluster is a wall.

The single source of truth for confluence — both the watch-list workspace and
the zone scanner call this; do not reintroduce a parallel inline loop.
"""

from constants import CONFLUENCE_ATR_THRESHOLD, CONFLUENCE_FORTRESS_THRESHOLD


def _metrics(target: float, value: float, atr: float) -> tuple[float, float]:
    """Return (distance in ATR units, distance in percent) from target to value."""
    dist = abs(target - value)
    return dist / atr, (dist / target * 100.0 if target > 0 else 0.0)


def evaluate_confluence(
    price: float,
    stop_price: float,
    levels: dict,
    atr: float,
    threshold: float = CONFLUENCE_ATR_THRESHOLD,
    fortress: float = CONFLUENCE_FORTRESS_THRESHOLD,
) -> dict:
    """Evaluate confluence of `levels` against both price and stop.

    Args:
        price: current price (the "entry" anchor).
        stop_price: stop level (the "stop" anchor).
        levels: ordered dict label -> price for any structural levels. None
            values are skipped, so callers can pass optional levels freely.
        atr: volatility yardstick (e.g. 14-day Wilder ATR).
        threshold / fortress: in-zone and fortress proximity in ATR units.

    Returns dict:
        strength: count of (level, anchor) pairs within `threshold` ATR;
                  price-side and stop-side are counted independently.
        levels:   per-level detail in input order — both price- and stop-side
                  distances (ATR and %), in-zone and fortress flags. The UI table
                  renders directly from this.
        zones:    flat list of in-zone hits, each naming the converging signal
                  (type ENTRY/STOP, name, value, atr_distance, pct_distance,
                  is_fortress) — the reasoning behind a flagged zone.
    """
    if atr <= 0 or not levels:
        return {"strength": 0, "levels": [], "zones": []}

    detail = []
    zones = []
    strength = 0

    for name, value in levels.items():
        if value is None:
            continue
        p_atr, p_pct = _metrics(price, value, atr)
        s_atr, s_pct = _metrics(stop_price, value, atr)
        p_in, s_in = p_atr < threshold, s_atr < threshold

        detail.append({
            "name": name,
            "value": float(value),
            "price_atr": p_atr, "price_pct": p_pct,
            "price_in_zone": p_in, "price_fortress": p_atr < fortress,
            "stop_atr": s_atr, "stop_pct": s_pct,
            "stop_in_zone": s_in, "stop_fortress": s_atr < fortress,
        })

        if p_in:
            strength += 1
            zones.append({
                "type": "ENTRY", "name": name, "value": float(value),
                "atr_distance": p_atr, "pct_distance": p_pct,
                "is_fortress": p_atr < fortress,
            })
        if s_in:
            strength += 1
            zones.append({
                "type": "STOP", "name": name, "value": float(value),
                "atr_distance": s_atr, "pct_distance": s_pct,
                "is_fortress": s_atr < fortress,
            })

    return {"strength": strength, "levels": detail, "zones": zones}
