"""Entry gates G1–G8 (Entry & Stop System §4) — a pure, advisory-first validator.

A gate is a hard stop sign, not a size penalty: a NEW entry must clear every gate
(§4). This module is *pure* — it takes a `ProposedTrade` and returns one
`GateResult` per gate (PASS / FAIL / NA + a human reason). It performs no I/O and
branches no trade logic; wiring decides what to do with the verdicts (see the
`gates_mode = off | advisory | blocking` flag in the pre-trade flow).

NA is a first-class outcome: when a gate's inputs are absent (no earnings date, no
ADV, no heat context), it returns NA and never blocks. Only an explicit FAIL blocks
in `blocking` mode — so partial context degrades gracefully.

Thresholds come from constants.py (Phase-1 config), so they can be tuned from the
log without touching this logic.
"""

from dataclasses import dataclass
from typing import Optional

from constants import (
    GATE_G1_MAX_STOP_ATR,
    GATE_G1_MAX_STOP_PCT,
    GATE_G2_MIN_CONFLUENCE,
    GATE_G2_THIN_SOURCES,
    GATE_G2_TIGHT_PREFIXES,
    GATE_G3_MOMO_VAL_STOP_PCT,
    GATE_G4_EVENT_DAYS,
    GATE_G5_MAX_EXTENSION_ATR,
    GATE_G6_ADV_FRACTION,
    GATE_G7_HEAT_MULT,
)

PASS = "PASS"
FAIL = "FAIL"
NA = "NA"


@dataclass
class GateResult:
    gate: str      # "G1" … "G8"
    name: str      # short label
    status: str    # PASS / FAIL / NA
    reason: str    # human-readable justification


@dataclass
class ProposedTrade:
    """Everything a gate might read. Every field is optional; a gate whose inputs
    are missing returns NA. Distances/prices are in the asset's own currency; the
    heat/currency gates convert to base currency via `fx_rate`."""

    ticker: str = ""
    entry: float = 0.0
    stop: float = 0.0
    atr: float = 0.0                       # ATR the multipliers are measured in (state the period upstream)
    qty: float = 0.0
    nav: float = 0.0
    multiplier: float = 1.0
    max_r_pct: float = 1.0                 # single-trade R% cap (for the heat cap)

    # scanner / structural context
    stop_source: str = ""
    flagged: Optional[bool] = None
    regime: str = ""                       # "MOMENTUM" / "NORMAL"
    confluence_count: Optional[int] = None

    # event (G4)
    days_to_event: Optional[int] = None

    # extension (G5)
    trail_anchor: Optional[float] = None   # the anchor you'd trail from (30-wk MA / DMA / …)

    # liquidity (G6)
    adv: Optional[float] = None            # average daily volume, in shares
    slippage_est: Optional[float] = None   # modeled slippage (same unit as budget)
    slippage_budget: Optional[float] = None

    # heat (G7)
    theme: str = ""
    theme_heat_pct: Optional[float] = None       # existing Σ R% already on this theme (base ccy)
    portfolio_heat_pct: Optional[float] = None    # existing Σ R% on correlated names (base ccy)

    # currency (G8)
    ccy: str = ""                          # asset currency
    base_ccy: str = ""                     # portfolio base currency
    fx_rate: float = 1.0                   # asset ccy -> base ccy
    fx_exposure_cap_pct: Optional[float] = None   # optional base-ccy exposure cap for foreign names


# --------------------------------------------------------------------------
# Derived quantities
# --------------------------------------------------------------------------
def r1(trade: ProposedTrade) -> float:
    """Initial risk per share = entry − stop."""
    return trade.entry - trade.stop


def r_pct(trade: ProposedTrade) -> Optional[float]:
    """Portfolio risk R% in base currency, or None if NAV is unknown."""
    if not trade.nav or trade.nav <= 0:
        return None
    return r1(trade) * trade.qty * trade.multiplier * trade.fx_rate / trade.nav * 100.0


def _stop_width_pct(trade: ProposedTrade) -> Optional[float]:
    if not trade.entry or trade.entry <= 0:
        return None
    return r1(trade) / trade.entry


# --------------------------------------------------------------------------
# Individual gates
# --------------------------------------------------------------------------
def g1_stop_width(trade: ProposedTrade) -> GateResult:
    name = "Stop-width"
    if trade.atr <= 0 or trade.entry <= 0 or r1(trade) <= 0:
        return GateResult("G1", name, NA, "Need entry, stop and ATR (with entry > stop).")
    width_atr = r1(trade) / trade.atr
    width_pct = r1(trade) / trade.entry
    ok_atr = width_atr <= GATE_G1_MAX_STOP_ATR
    ok_pct = width_pct <= GATE_G1_MAX_STOP_PCT
    if ok_atr and ok_pct:
        return GateResult("G1", name, PASS,
                          f"R₁ {width_atr:.2f}×ATR ({width_pct*100:.1f}% of price) within "
                          f"{GATE_G1_MAX_STOP_ATR}×ATR / {GATE_G1_MAX_STOP_PCT*100:.0f}%.")
    parts = []
    if not ok_atr:
        parts.append(f"{width_atr:.2f}×ATR > {GATE_G1_MAX_STOP_ATR}×")
    if not ok_pct:
        parts.append(f"{width_pct*100:.1f}% > {GATE_G1_MAX_STOP_PCT*100:.0f}%")
    return GateResult("G1", name, FAIL,
                      "Stop too wide (" + "; ".join(parts) + ") — wrong location or mid-air, not licence to risk more.")


def g2_basis_quality(trade: ProposedTrade) -> GateResult:
    name = "Basis quality"
    if not trade.stop_source or trade.confluence_count is None:
        return GateResult("G2", name, NA, "Need stop_source and a confluence count.")
    thin = trade.stop_source in GATE_G2_THIN_SOURCES
    tight = trade.stop_source.startswith(GATE_G2_TIGHT_PREFIXES)
    enough = trade.confluence_count >= GATE_G2_MIN_CONFLUENCE
    if thin or not tight:
        return GateResult("G2", name, FAIL,
                          f"stop_source '{trade.stop_source}' is a thin/loose basis (Scenario D).")
    if not enough:
        return GateResult("G2", name, FAIL,
                          f"Only {trade.confluence_count} confluent level(s); need ≥ {GATE_G2_MIN_CONFLUENCE} independent.")
    return GateResult("G2", name, PASS,
                      f"'{trade.stop_source}' with {trade.confluence_count} independent confluent levels.")


def g3_fallback_artifact(trade: ProposedTrade) -> GateResult:
    name = "Not a fallback artifact"
    if trade.flagged is None or not trade.regime:
        return GateResult("G3", name, NA, "Need the regime and the flagged status.")
    width_pct = _stop_width_pct(trade)
    is_momo = trade.regime.upper() == "MOMENTUM"
    is_val = trade.stop_source.startswith("VAL")
    double_digit = width_pct is not None and width_pct >= GATE_G3_MOMO_VAL_STOP_PCT
    if is_momo and trade.flagged is False and is_val and double_digit:
        return GateResult("G3", name, FAIL,
                          f"Unflagged MOMENTUM with a {width_pct*100:.0f}% VAL_* stop — Scenario C fallback, no trade.")
    return GateResult("G3", name, PASS, "Not a Scenario-C fallback (flagged, or not a deep MOMO VAL stop).")


def g4_event(trade: ProposedTrade) -> GateResult:
    name = "Event"
    if trade.days_to_event is None:
        return GateResult("G4", name, NA, "No earnings/catalyst date supplied.")
    if 0 <= trade.days_to_event <= GATE_G4_EVENT_DAYS:
        return GateResult("G4", name, FAIL,
                          f"Entry is {trade.days_to_event}d from a catalyst (≤ {GATE_G4_EVENT_DAYS}d) — "
                          f"structural stops don't survive gaps. Wait, or size off the gap (§6).")
    return GateResult("G4", name, PASS, f"{trade.days_to_event}d to next catalyst (> {GATE_G4_EVENT_DAYS}d).")


def g5_extension(trade: ProposedTrade) -> GateResult:
    name = "Extension"
    if trade.trail_anchor is None or trade.atr <= 0:
        return GateResult("G5", name, NA, "Need a trail anchor and an ATR.")
    ext_atr = (trade.entry - trade.trail_anchor) / trade.atr
    if ext_atr > GATE_G5_MAX_EXTENSION_ATR:
        return GateResult("G5", name, FAIL,
                          f"Price is {ext_atr:.2f}×ATR above the trail anchor (> {GATE_G5_MAX_EXTENSION_ATR}×) — chasing.")
    return GateResult("G5", name, PASS, f"{ext_atr:.2f}×ATR above the trail anchor (≤ {GATE_G5_MAX_EXTENSION_ATR}×).")


def g6_liquidity(trade: ProposedTrade) -> GateResult:
    name = "Liquidity"
    checks = []
    failed = []
    if trade.adv is not None and trade.adv > 0:
        cap = GATE_G6_ADV_FRACTION * trade.adv
        checks.append("ADV")
        if trade.qty > cap:
            failed.append(f"size {trade.qty:.0f} > {GATE_G6_ADV_FRACTION*100:.0f}% of ADV ({cap:.0f})")
    if trade.slippage_est is not None and trade.slippage_budget is not None:
        checks.append("slippage")
        if trade.slippage_est > trade.slippage_budget:
            failed.append(f"slippage {trade.slippage_est:g} > budget {trade.slippage_budget:g}")
    if not checks:
        return GateResult("G6", name, NA, "No ADV or slippage inputs supplied.")
    if failed:
        return GateResult("G6", name, FAIL, "; ".join(failed) + " — a stop you can't exit at is not a stop.")
    return GateResult("G6", name, PASS, "Within ADV and slippage budget.")


def g7_theme_heat(trade: ProposedTrade) -> GateResult:
    name = "Theme/portfolio heat"
    if trade.theme_heat_pct is None and trade.portfolio_heat_pct is None:
        return GateResult("G7", name, NA, "No theme/portfolio heat context supplied.")
    add = r_pct(trade)
    if add is None:
        return GateResult("G7", name, NA, "Need NAV to compute this trade's R%.")
    cap = GATE_G7_HEAT_MULT * trade.max_r_pct
    failed = []
    if trade.theme_heat_pct is not None and (trade.theme_heat_pct + add) > cap:
        failed.append(f"theme '{trade.theme or '?'}' → {trade.theme_heat_pct + add:.2f}% > {cap:.2f}%")
    if trade.portfolio_heat_pct is not None and (trade.portfolio_heat_pct + add) > cap:
        failed.append(f"correlated heat → {trade.portfolio_heat_pct + add:.2f}% > {cap:.2f}%")
    if failed:
        return GateResult("G7", name, FAIL,
                          "; ".join(failed) + " — clustered one-view risk; count the theme, not the trade.")
    return GateResult("G7", name, PASS, f"Adding {add:.2f}% keeps theme/correlated heat ≤ {cap:.2f}%.")


def g8_currency(trade: ProposedTrade) -> GateResult:
    name = "Currency"
    if not trade.ccy or not trade.base_ccy:
        return GateResult("G8", name, NA, "No asset/base currency supplied.")
    if trade.ccy.upper() == trade.base_ccy.upper():
        return GateResult("G8", name, PASS, f"Asset and book are both {trade.base_ccy.upper()} — no FX risk.")
    # Foreign currency: informational unless an explicit base-ccy exposure cap is breached.
    if trade.fx_exposure_cap_pct is not None and trade.nav and trade.nav > 0:
        exp_pct = max(trade.entry, 0.0) * trade.qty * trade.multiplier * trade.fx_rate / trade.nav * 100.0
        if exp_pct > trade.fx_exposure_cap_pct:
            return GateResult("G8", name, FAIL,
                              f"{trade.ccy.upper()} exposure {exp_pct:.1f}% > cap {trade.fx_exposure_cap_pct:.1f}% "
                              f"in {trade.base_ccy.upper()} terms.")
    return GateResult("G8", name, PASS,
                      f"{trade.ccy.upper()} vs {trade.base_ccy.upper()} book — FX risk carried (decide: ignore/cap/hedge).")


_GATES = (
    g1_stop_width, g2_basis_quality, g3_fallback_artifact, g4_event,
    g5_extension, g6_liquidity, g7_theme_heat, g8_currency,
)


def evaluate_gates(trade: ProposedTrade) -> list[GateResult]:
    """Run every gate in order (G1…G8) and return their results."""
    return [gate(trade) for gate in _GATES]


def gates_summary(results: list[GateResult]) -> dict:
    """Aggregate a gate run. `blocking` is True iff any gate explicitly FAILed
    (NA never blocks)."""
    failed = [r for r in results if r.status == FAIL]
    return {
        "n_pass": sum(1 for r in results if r.status == PASS),
        "n_fail": len(failed),
        "n_na": sum(1 for r in results if r.status == NA),
        "failed": failed,
        "blocking": bool(failed),
    }
