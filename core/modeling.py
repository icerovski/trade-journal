"""Pre-trade position modeling — the what-if engine behind the risk panel.

Answers one question: *given a position, an optional draft, and a set of
overrides, what is the single reconciled directive and what does the book look
like after it?* Everything the risk workspace's audit panel prints is derived
from the `PositionModel` this returns; the UI adds markup and nothing else.

Pure: no I/O, no database, no Textual, no markup. The caller resolves the
position and its discovery rows; this decides.

Extracted from `ui.risk_workspace.refresh_risk_checklist` (2026-08-04) with no
behaviour change — `tests/test_risk_panel_characterization.py` pins the rendered
output byte-for-byte across 32 scenarios and must stay green.

The reconciled verdict is the heart of it. Three axes (exposure/sizing, risk,
exit ladder) are collapsed into ONE directive by strict precedence:

    breach → explicit user model (±N / BE) → exit stage → add → trim → hold

The fundamental that resolves add-vs-trim: exposure headroom sizes a new or early
position; it is never licence to add to a winner that has reached a profit-taking
stage. So at an exit stage the ladder governs and the headroom is reported but
muted.
"""

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from constants import TP_ATR_MULTIPLE
from core.stop_loss import audit_position_risk


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Verdict:
    """The single reconciled directive. `label`/`sub` are plain text — the UI
    owns colour markup; `color` is a semantic name, not a markup tag."""
    color: str
    label: str
    sub: str
    target_qty: int


@dataclass(frozen=True)
class SizingProjection:
    """Post-action projection of the book: BAL-BEG → ADD → BALANCE.

    Present only when a transaction is actually implied (`net_action != 0` on a
    held position with a NAV); `None` otherwise, which is what suppresses the
    sizing table in the panel.
    """
    net_action: int
    new_qty: float
    new_entry: float
    new_cost: float
    new_market: float
    new_hcm: float
    new_r_pct: float
    new_e_pct: float
    r_add_pct: float
    e_add_pct: float
    tx_hcm: float
    sl_pct_beg: float
    sl_pct_add: float
    sl_pct_bal: float
    pl_stop_beg: float
    pl_stop_add: float
    pl_stop_bal: float
    beg_is_market: bool
    bal_is_market: bool


@dataclass(frozen=True)
class PositionModel:
    """Everything the audit panel needs, already decided."""
    # resolved inputs
    price: float
    entry: float
    qty: float
    stop: float
    atr: float
    max_r_pct: float
    max_exp_pct: float
    is_modeling: bool
    exit_shape: str

    # audit
    audit: dict
    is_safe: bool
    buffer_pct: float

    # reward geometry
    r_unit: float
    tp_mult: float
    tp_target: float
    efficiency: float

    # decision
    verdict: Verdict
    exit_rec: Optional[dict]
    modeled_add: Optional[int]
    room: int

    # book impact
    cost_value: float
    market_value: float
    hcm_exposure: float
    sizing: Optional[SizingProjection] = None

    @property
    def has_sizing(self) -> bool:
        return self.sizing is not None


@dataclass(frozen=True)
class ModelInputs:
    """What-if overrides. Every field `None` = "use the position's own value",
    so an empty ModelInputs reproduces the position as it stands.

    `tp_mult` uses -1.0 rather than None as its "not supplied" sentinel because
    None is itself meaningful there (an explicitly cleared override → default 3R).
    """
    stop: Optional[float] = None
    atr: Optional[float] = None
    max_r_pct: Optional[float] = None
    max_exp_pct: Optional[float] = None
    qty: Optional[float] = None
    entry: Optional[float] = None
    add: Optional[float] = None
    goal_seek: Optional[str] = None
    tp_mult: float = -1.0
    exit_shape: Optional[str] = None


# --------------------------------------------------------------------------
# Helpers (pure)
# --------------------------------------------------------------------------
def solve_breakeven_add(qty: float, entry: float, stop: float, price: float) -> Optional[float]:
    """Shares to BUY at `price` so the aggregate average cost equals `stop` (P/L @ Stop = 0).
    Derivation: solve the WAC blend (entry·qty + price·add)/(qty + add) = stop  →
    add = qty·(entry − stop)/(stop − price). Returns None when no purchase achieves it —
    price == stop, no current quantity, or the math yields a non-positive add (trimming
    can't move a weighted-average cost, so break-even is only reachable by buying)."""
    denom = stop - price
    if denom == 0 or qty <= 0:
        return None
    add = qty * (entry - stop) / denom
    return round(add) if add > 0 else None


def resolve_effective_atr(position, inputs: ModelInputs, discovery: Optional[dict],
                          entry: float, stop: Optional[float]) -> float:
    """The ATR to measure volatility with.

    For a FIXED stop `position.atr` holds the stop PRICE, not a distance, so it
    cannot be used as an ATR. Prefer the daily 14d discovery ATR, then the frozen
    inception ATR, then the raw entry−stop distance.
    """
    if position.stop_type == 'FIXED' and inputs.atr is None:
        rows = (discovery or {}).get('rows') or []
        disc_atr = next((r.atr_wilder for r in rows if r.label == '14d'), None)
        if disc_atr:
            return disc_atr
        if position.inception_atr and position.inception_atr > 0:
            return position.inception_atr
        return max(0.0, (entry or 0) - (stop or entry or 0))
    return inputs.atr if inputs.atr is not None else position.atr


def resolve_tp_multiple(position, inputs: ModelInputs) -> float:
    """Effective TP multiple: a modeled override wins, then the saved override,
    then the default 3R. `inputs.tp_mult` of -1.0 means "not modeled this edit";
    a modeled None means "cleared → default"."""
    if inputs.tp_mult != -1.0:
        return inputs.tp_mult if (inputs.tp_mult and inputs.tp_mult > 0) else TP_ATR_MULTIPLE
    if getattr(position, 'tp_is_override', False) and position.tp_atr_mult:
        return position.tp_atr_mult
    return TP_ATR_MULTIPLE


# --------------------------------------------------------------------------
# The verdict chain
# --------------------------------------------------------------------------
def decide_verdict(*, audit: dict, qty: float, price: float, max_exp_pct: float,
                   modeled_add: Optional[int], goal_seek: Optional[str],
                   exit_rec: Optional[dict], room: int) -> Verdict:
    """Collapse the three axes into one directive. Order is the whole design —
    see the module docstring. Pure and side-effect free so each arm is testable
    in isolation."""
    if audit['is_breached']:
        return Verdict('red', 'EXIT NOW — stop breached',
                       f"Sell all {int(qty)} sh @ {price:,.2f}.", 0)

    if modeled_add is not None:
        target = int(qty + modeled_add)
        verb = "ADD" if modeled_add >= 0 else "TRIM"
        tag = " (P/L@Stop → 0)" if goal_seek == 'BE' else ""
        return Verdict('magenta', f"MODELING: {verb} {abs(int(modeled_add))} sh{tag}",
                       f"@ {price:,.2f} → {target} sh", target)

    if goal_seek == 'BE':
        return Verdict('magenta', "GOAL-SEEK: P/L@Stop = 0 not reachable by buying",
                       f"Would require trimming at {price:,.2f}, which can't move average cost.",
                       int(qty))

    if exit_rec:
        # Never add at a profit-taking stage; report the headroom, do not act on it.
        sub = exit_rec['reason']
        if room > 0:
            headroom = max_exp_pct - audit['current_exposure_pct']
            sub += f"  [dim]({headroom:.1f}% exposure room exists, but no adds at target.)[/]"
        return Verdict(exit_rec['color'], exit_rec['headline'], sub, int(qty))

    # Everything above this line is computable without NAV — a breach is a price
    # comparison, a user model is arithmetic on quantity, the ladder reads stage and
    # regime. Everything BELOW divides by NAV. With no NAV there is no room figure,
    # so saying "HOLD — within all limits" would assert a limit check that never ran.
    if not audit.get('nav_known', True):
        return Verdict('yellow', "NAV UNAVAILABLE — sizing suspended",
                       "Portfolio NAV could not be read, so R% and exposure cannot be "
                       "computed. Re-run SYNC ALL (menu 1) before sizing this trade.",
                       int(qty))

    if room > 0:
        target = int(qty + room)
        return Verdict('green', f"ADD +{room} sh",
                       f"@ {price:,.2f} → {target} sh — room to the {max_exp_pct:.1f}% exposure limit.",
                       target)

    if room < 0:
        target = int(qty + room)
        return Verdict('yellow', f"TRIM {abs(room)} sh",
                       f"Over the {max_exp_pct:.1f}% exposure limit @ {price:,.2f}.", target)

    return Verdict('white', "HOLD — at max size",
                   "Within all limits; no adjustment needed.", int(qty))


def project_sizing(*, qty: float, entry: float, price: float, stop: float, atr: float,
                   net_action: int, multiplier: float, fx_rate: float, total_nav: float,
                   stop_type: str, max_since_entry: float, audit: dict,
                   cost_value: float, market_value: float) -> Optional[SizingProjection]:
    """Post-action projection. Returns None when no transaction is implied, which
    is what suppresses the sizing table."""
    if not (qty > 0 and total_nav > 0 and net_action != 0):
        return None

    if net_action > 0:
        new_qty = qty + net_action
        new_entry = (entry * qty + price * net_action) / new_qty
    else:
        new_qty = max(0.0, qty + net_action)
        new_entry = entry if new_qty > 0 else 0.0

    new_cost = new_qty * new_entry * multiplier
    new_market = new_qty * price * multiplier
    new_hcm = max(new_cost, new_market)
    new_r = ((new_entry - stop) * new_qty * multiplier * fx_rate / total_nav * 100) if new_qty > 0 else 0.0
    new_e = new_hcm * fx_rate / total_nav * 100

    # ADD-column values are per-transaction contributions: they sum exactly to BALANCE.
    r_add = (price - stop) * net_action * multiplier * fx_rate / total_nav * 100
    e_add = price * net_action * multiplier * fx_rate / total_nav * 100

    if stop_type == 'TRAILING':
        # The ATR width is unchanged by the transaction, so all three columns match.
        hwm = max_since_entry if max_since_entry > 0 else entry
        sl_beg = sl_add = sl_bal = (atr / hwm * 100) if hwm > 0 else 0.0
    else:  # FIXED — the stop is a price, so each column measures from its own basis.
        sl_beg = max(0.0, entry - stop) / entry * 100 if entry > 0 else 0.0
        sl_add = max(0.0, price - stop) / price * 100 if price > 0 else 0.0
        sl_bal = max(0.0, new_entry - stop) / new_entry * 100 if new_entry > 0 else 0.0

    return SizingProjection(
        net_action=net_action,
        new_qty=new_qty, new_entry=new_entry,
        new_cost=new_cost, new_market=new_market, new_hcm=new_hcm,
        new_r_pct=new_r, new_e_pct=new_e, r_add_pct=r_add, e_add_pct=e_add,
        tx_hcm=net_action * price * multiplier,
        sl_pct_beg=sl_beg, sl_pct_add=sl_add, sl_pct_bal=sl_bal,
        pl_stop_beg=(stop - entry) * qty * multiplier,
        pl_stop_add=(stop - price) * net_action * multiplier,
        pl_stop_bal=(stop - new_entry) * new_qty * multiplier,
        beg_is_market=market_value >= cost_value,
        bal_is_market=new_market >= new_cost,
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def build_position_model(position, *, total_nav: float, inputs: ModelInputs = None,
                         discovery: Optional[dict] = None, is_modeling: bool = False,
                         exit_recommender=None) -> Optional[PositionModel]:
    """Model `position` under `inputs`. Returns None when there is nothing to
    audit (no stop and no entry to fall back on, or a zero price).

    `exit_recommender(stage, regime, qty, entry, stop, tp, price, rr, stop_type,
    exit_shape=…)` is injected so the exit ladder stays where it is today
    (`ui.risk_workspace._exit_recommendation`) rather than being moved in the same
    commit as this extraction.
    """
    inputs = inputs or ModelInputs()

    # Audit price: a HELD position is always priced at the live market price —
    # never at entry, which would fabricate a breach for a winner whose stop sits
    # above cost. A PROSPECT (qty 0) has no market position, so it prices the
    # hypothetical entry. Quantity modeling transacts at the live price, since an
    # add reflects what you would actually pay now.
    if position.qty > 0:
        price = position.current_price or position.mark_price
    else:
        price = inputs.entry if inputs.entry is not None else (position.current_price or position.mark_price)
    if price == 0 and discovery:
        price = discovery.get('current_price', 0.0)
    if inputs.add is not None or inputs.goal_seek:
        market_p = position.current_price or position.mark_price
        if market_p and market_p > 0:
            price = market_p

    max_r_pct = inputs.max_r_pct if inputs.max_r_pct is not None else position.max_r_pct
    max_exp_pct = inputs.max_exp_pct if inputs.max_exp_pct is not None else position.max_exp_pct
    qty = inputs.qty if inputs.qty is not None else position.qty
    entry = inputs.entry if inputs.entry is not None else (
        position.entry_price if position.entry_price > 0 else price)
    stop = inputs.stop if inputs.stop is not None else position.sl_price

    # No stop anywhere → fall back to entry, which makes risk zero rather than undefined.
    effective_stop = stop if pd.notnull(stop) else entry
    if not pd.notnull(effective_stop) or price <= 0:
        return None

    audit = audit_position_risk(price, effective_stop, entry, qty, position.multiplier,
                                total_nav, max_r_pct=max_r_pct, max_exp_pct=max_exp_pct,
                                fx_rate=position.fx_rate)

    atr = resolve_effective_atr(position, inputs, discovery, entry, stop)

    # The reward ladder is anchored to entry + n × R where R is the ORIGINAL risk
    # unit (inception ATR) — the same unit as pos.tp_price and M1/M2/TP — so the
    # panel's RR can never diverge from the ladder. The live trailing ATR governs
    # the stop, not the target.
    r_unit = position.inception_atr if (position.inception_atr and position.inception_atr > 0) \
        else max(0.0, (entry or 0) - (effective_stop or entry or 0))
    tp_mult = resolve_tp_multiple(position, inputs)
    tp_target = entry + (tp_mult * r_unit)
    efficiency = ((tp_target - price) / (price - effective_stop)) if price > effective_stop else 0

    modeled_add = None
    if inputs.goal_seek == 'BE':
        modeled_add = solve_breakeven_add(qty, entry, effective_stop, price)
    elif inputs.add is not None:
        modeled_add = int(inputs.add)

    exit_shape = inputs.exit_shape if inputs.exit_shape is not None else getattr(position, 'exit_shape', '')
    exit_stage = getattr(position, 'exit_stage', '')
    regime = getattr(position, 'trend_regime', 'NORMAL')
    exit_rec = exit_recommender(
        exit_stage, regime, qty, entry, effective_stop, position.tp_price,
        price, efficiency, position.stop_type, exit_shape=exit_shape,
    ) if exit_recommender else None

    room = int(audit['adjustment'])
    verdict = decide_verdict(audit=audit, qty=qty, price=price, max_exp_pct=max_exp_pct,
                             modeled_add=modeled_add, goal_seek=inputs.goal_seek,
                             exit_rec=exit_rec, room=room)

    # HCM exposure uses the LIVE quantity (position.qty), not the modeled one:
    # it reports the book as it stands, which the projection then acts on.
    cost_value = position.qty * entry * position.multiplier
    market_value = position.qty * price * position.multiplier

    sizing = project_sizing(
        qty=qty, entry=entry, price=price, stop=effective_stop, atr=atr,
        net_action=int(verdict.target_qty) - int(qty), multiplier=position.multiplier,
        fx_rate=position.fx_rate, total_nav=total_nav, stop_type=position.stop_type,
        max_since_entry=position.max_since_entry, audit=audit,
        cost_value=cost_value, market_value=market_value,
    )

    return PositionModel(
        price=price, entry=entry, qty=qty, stop=effective_stop, atr=atr,
        max_r_pct=max_r_pct, max_exp_pct=max_exp_pct,
        is_modeling=is_modeling, exit_shape=exit_shape,
        audit=audit, is_safe=price > effective_stop,
        buffer_pct=((price - effective_stop) / price * 100) if price > 0 else 0,
        r_unit=r_unit, tp_mult=tp_mult, tp_target=tp_target, efficiency=efficiency,
        verdict=verdict, exit_rec=exit_rec, modeled_add=modeled_add, room=room,
        cost_value=cost_value, market_value=market_value,
        hcm_exposure=max(cost_value, market_value),
        sizing=sizing,
    )
