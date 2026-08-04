import math

import pandas as pd


def compute_position_size(
    total_nav: float, entry_price: float, stop_price: float,
    inst_multiplier: float, max_r_pct: float, max_exp_pct: float,
    fx_rate: float = 1.0, exposure_price: float | None = None,
) -> int:
    """
    Returns maximum share quantity satisfying both the R% and exposure% constraints.
    The tighter of the two limits wins.

    `fx_rate` converts asset-currency amounts to the NAV currency (e.g. USD -> EUR),
    the same convention as audit_position_risk; 1.0 = same currency. Prices stay in
    the asset currency — only the NAV-relative caps need the conversion. A degenerate
    rate (None / 0 / negative / NaN — bad snapshot data) degrades to 1.0 rather than
    dividing by zero: the caps then read the asset currency at par, matching the
    pre-FX behaviour instead of crashing the caller.
    `exposure_price` pins the exposure leg to a different reference than the risk
    leg (e.g. current price while modeling off a trailing base); default entry_price.
    """
    if not fx_rate or not math.isfinite(fx_rate) or fx_rate <= 0:
        fx_rate = 1.0
    exp_ref = exposure_price if exposure_price is not None else entry_price
    risk_dist = abs(entry_price - stop_price) * inst_multiplier * fx_rate
    risk_q = (total_nav * (max_r_pct / 100.0)) / risk_dist if risk_dist > 0 else float('inf')
    exp_q = (total_nav * (max_exp_pct / 100.0)) / (exp_ref * inst_multiplier * fx_rate) if exp_ref > 0 else 0
    return int(min(risk_q, exp_q))


def gap_effective_stop(stop_price: float, gap_price):
    """The stop the gap-aware sizer risks against: the LOWER of the structural stop
    and the plausible post-event gap price (§6). Picking the lower price is exactly
    'use the larger of R₁ and R_gap'. `gap_price` None (or not below the stop) → the
    structural stop, so sizing is unchanged."""
    if gap_price is None:
        return stop_price
    return min(stop_price, gap_price)


def compute_position_size_gap(
    total_nav: float, entry_price: float, stop_price: float, gap_price,
    inst_multiplier: float, max_r_pct: float, max_exp_pct: float,
    fx_rate: float = 1.0, exposure_price: float | None = None,
) -> int:
    """
    Gap-aware sizing (Entry & Stop System §6). For a name held through an event, the
    stop can slip to the gap, not the level — so size off `R_gap = entry − gap_price`
    using the larger of R₁ and R_gap. Opt-in: with `gap_price=None` this is identical
    to compute_position_size (the default fixed-fractional path). The exposure clamp is
    unchanged; only the risk distance widens, which can only shrink the size.
    `fx_rate` / `exposure_price` pass through to compute_position_size.
    """
    effective_stop = gap_effective_stop(stop_price, gap_price)
    return compute_position_size(
        total_nav, entry_price, effective_stop, inst_multiplier, max_r_pct, max_exp_pct,
        fx_rate=fx_rate, exposure_price=exposure_price,
    )


def compute_portfolio_risk(df: pd.DataFrame, total_nav: float, nav_ccy: str) -> dict:
    """
    Computes portfolio-level Phase 1 risk metrics from the enriched positions DataFrame.
    Only rows with Qty > 0 are included; risk metrics are further split by whether
    a stop has been assigned (SL_Price > 0).
    """
    if df.empty or total_nav <= 0:
        return {}

    active = df[df['Qty'] > 0].copy()
    if active.empty:
        return {}

    has_stop = active['SL_Price'].notna() & (active['SL_Price'] > 0)
    with_stop = active[has_stop].copy()
    without_stop = active[~has_stop].copy()

    # P/L at stop in NAV currency. This one is legitimately NET: a position whose
    # stop sits above entry really does bank a gain, and the question here is
    # "what does a full stop-out cost me in cash?".
    with_stop['stop_out_nav'] = with_stop['Risk_Val'] * with_stop['FXRate'].fillna(1.0)
    total_stop_out = with_stop['stop_out_nav'].sum()

    # Portfolio heat answers a different question — "how much NAV is still exposed
    # to being lost?" — and must NOT net. A ratcheted winner carries a negative
    # risk_pct_nav (a locked-in gain at its stop); summing raw lets it cancel live
    # downside on other names, so a book of three 1%-risk positions plus one −3%
    # winner would report ~0% heat and hand back false budget headroom. Heat is the
    # sum of POSITIVE risk only; the net figure is kept alongside for context.
    open_risk = with_stop['risk_pct_nav'].clip(lower=0.0)
    total_r_pct = float(open_risk.sum())
    total_r_pct_net = float(with_stop['risk_pct_nav'].sum())
    n_locked_in = int((with_stop['risk_pct_nav'] < 0).sum())
    total_e_pct = active['NavPct'].sum()

    total_budget = with_stop['MaxRPct'].sum()
    headroom = total_budget - total_r_pct
    pct_budget_used = (total_r_pct / total_budget * 100) if total_budget > 0 else 0.0

    breached = with_stop[with_stop['Price'] <= with_stop['SL_Price']]

    top_exposure = active.nlargest(5, 'NavPct')[['Ticker', 'NavPct', 'risk_pct_nav']].copy()
    top_risk = with_stop.nlargest(5, 'risk_pct_nav')[['Ticker', 'risk_pct_nav', 'NavPct']].copy()

    total_e = active['NavPct'].sum()
    hhi = float(((active['NavPct'] / total_e) ** 2).sum()) if total_e > 0 else 0.0

    ccy_groups = active.groupby('CCY')['NavPct'].sum().sort_values(ascending=False)
    ccy_breakdown = {
        ccy: (float(nav_pct), float(nav_pct / total_e * 100) if total_e > 0 else 0.0)
        for ccy, nav_pct in ccy_groups.items()
    }

    return {
        'n_active': len(active),
        'n_with_stop': len(with_stop),
        'n_without_stop': len(without_stop),
        'total_stop_out': float(total_stop_out),
        'total_r_pct': float(total_r_pct),          # heat: positive risk only
        'total_r_pct_net': total_r_pct_net,         # net of stops ratcheted above entry
        'n_locked_in': n_locked_in,                 # positions whose stop is above entry
        'total_e_pct': float(total_e_pct),
        'total_budget': float(total_budget),
        'headroom': float(headroom),
        'pct_budget_used': float(pct_budget_used),
        'n_breached': len(breached),
        'breached_tickers': list(breached['Ticker']),
        'top_exposure': top_exposure,
        'top_risk': top_risk,
        'hhi': hhi,
        'ccy_breakdown': ccy_breakdown,
        'unmanaged': list(without_stop['Ticker']) if not without_stop.empty else [],
    }


def hhi_label(hhi: float) -> tuple[str, str]:
    """Returns (colour, description) for an HHI score."""
    if hhi < 0.10:
        return "green", "Low — well diversified"
    elif hhi < 0.20:
        return "yellow", "Moderate"
    else:
        return "red", "High — concentrated"
