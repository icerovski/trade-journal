import pandas as pd


def compute_position_size(
    total_nav: float, entry_price: float, stop_price: float,
    inst_multiplier: float, max_r_pct: float, max_exp_pct: float,
) -> int:
    """
    Returns maximum share quantity satisfying both the R% and exposure% constraints.
    The tighter of the two limits wins.
    """
    risk_dist = abs(entry_price - stop_price) * inst_multiplier
    risk_q = (total_nav * (max_r_pct / 100.0)) / risk_dist if risk_dist > 0 else float('inf')
    exp_q = (total_nav * (max_exp_pct / 100.0)) / (entry_price * inst_multiplier) if entry_price > 0 else 0
    return int(min(risk_q, exp_q))


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

    # P/L at stop in NAV currency
    with_stop['stop_out_nav'] = with_stop['Risk_Val'] * with_stop['FXRate'].fillna(1.0)
    total_stop_out = with_stop['stop_out_nav'].sum()

    total_r_pct = with_stop['risk_pct_nav'].sum()
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
        'total_r_pct': float(total_r_pct),
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
