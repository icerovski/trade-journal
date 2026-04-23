import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich import box

from core.portfolio_manager import PortfolioManager
from core.portfolio_analytics import compute_portfolio_risk, hhi_label

console = Console()


def _r_color(r_pct: float, budget: float) -> str:
    if budget <= 0:
        return "white"
    ratio = r_pct / budget
    if ratio >= 0.90:
        return "red"
    elif ratio >= 0.70:
        return "yellow"
    return "green"


def run_portfolio_risk():
    pm = PortfolioManager()

    nav_res = pm.fetch_nav_data()
    if not nav_res:
        console.print("[red]Could not fetch NAV data.[/red]")
        input("\nPress Enter to return to menu...")
        return
    total_nav, nav_ccy, _, _ = nav_res

    console.print("\n[bold cyan]Loading portfolio data...[/bold cyan]")
    df, _ = pm.get_dashboard_df(total_nav=total_nav, silent=True)

    if df.empty:
        console.print("[yellow]No open positions found.[/yellow]")
        input("\nPress Enter to return to menu...")
        return

    m = compute_portfolio_risk(df, total_nav, nav_ccy)
    if not m:
        console.print("[yellow]Insufficient data for risk metrics.[/yellow]")
        input("\nPress Enter to return to menu...")
        return

    # ── Header ────────────────────────────────────────────────────────────────
    flags = []
    if m['n_breached']:
        flags.append(f"[bold red]⚠ {m['n_breached']} BREACHED[/]")
    if m['n_without_stop']:
        flags.append(f"[yellow]{m['n_without_stop']} unmanaged[/]")
    flag_str = "  │  " + "  ".join(flags) if flags else ""

    header = (
        f"NAV: [bold]{total_nav:,.0f} {nav_ccy}[/]  │  "
        f"{m['n_active']} positions  │  "
        f"{m['n_with_stop']} with stops"
        f"{flag_str}"
    )
    console.print(Panel(header, title="[bold]PORTFOLIO RISK REPORT[/bold]", border_style="blue"))

    # ── Aggregate Risk ─────────────────────────────────────────────────────────
    stop_out = m['total_stop_out']
    stop_out_color = "green" if stop_out >= 0 else "red"
    stop_out_str = f"[{stop_out_color}]{stop_out:+,.0f} {nav_ccy}[/]"

    rc = _r_color(m['total_r_pct'], m['total_budget'])
    hc = "green" if m['headroom'] >= 0 else "red"

    agg = Table(box=box.SIMPLE_HEAD, show_header=False, padding=(0, 2))
    agg.add_column("", style="dim")
    agg.add_column("", justify="right")
    agg.add_row("Portfolio R%  (total risk at stop)",  f"[{rc}]{m['total_r_pct']:.2f}%[/]")
    agg.add_row("Portfolio E%  (total HCM exposure)",  f"{m['total_e_pct']:.1f}%")
    agg.add_row("P/L if all stops hit",                stop_out_str)
    agg.add_row(
        "Risk budget used",
        f"{m['total_r_pct']:.2f}% of {m['total_budget']:.2f}%  "
        f"([{rc}]{m['pct_budget_used']:.0f}%[/])",
    )
    agg.add_row("Budget headroom", f"[{hc}]{m['headroom']:.2f}%[/]")
    if m['n_breached']:
        agg.add_row(
            "[bold red]Breached[/]",
            f"[bold red]{', '.join(m['breached_tickers'])}[/]",
        )

    console.print("\n[bold]AGGREGATE RISK[/bold]")
    console.print(agg)

    # ── Concentration ─────────────────────────────────────────────────────────
    exp_t = Table(title="Top 5 by Exposure", box=box.SIMPLE_HEAD)
    exp_t.add_column("Ticker", style="cyan", min_width=8)
    exp_t.add_column("E%", justify="right")
    exp_t.add_column("R%", justify="right")
    for _, row in m['top_exposure'].iterrows():
        exp_t.add_row(
            str(row['Ticker']),
            f"{row['NavPct']:.2f}%",
            f"{row['risk_pct_nav']:.2f}%" if row['risk_pct_nav'] > 0 else "---",
        )

    risk_t = Table(title="Top 5 by Risk", box=box.SIMPLE_HEAD)
    risk_t.add_column("Ticker", style="cyan", min_width=8)
    risk_t.add_column("R%", justify="right")
    risk_t.add_column("E%", justify="right")
    for _, row in m['top_risk'].iterrows():
        risk_t.add_row(
            str(row['Ticker']),
            f"{row['risk_pct_nav']:.2f}%",
            f"{row['NavPct']:.2f}%",
        )

    console.print("\n[bold]CONCENTRATION[/bold]")
    console.print(Columns([exp_t, risk_t]))
    hhi_col, hhi_desc = hhi_label(m['hhi'])
    console.print(f"  HHI: [{hhi_col}]{m['hhi']:.3f}[/]  ({hhi_desc})")

    # ── Currency Breakdown ────────────────────────────────────────────────────
    ccy_t = Table(box=box.SIMPLE_HEAD)
    ccy_t.add_column("CCY", style="cyan")
    ccy_t.add_column("% of Exposure", justify="right")
    ccy_t.add_column(f"NAV Value ({nav_ccy})", justify="right")
    for ccy, (nav_pct_sum, pct_of_exp) in m['ccy_breakdown'].items():
        nav_val = nav_pct_sum * total_nav / 100
        ccy_t.add_row(ccy, f"{pct_of_exp:.1f}%", f"{nav_val:,.0f}")

    console.print("\n[bold]CURRENCY EXPOSURE[/bold]")
    console.print(ccy_t)

    # ── Unmanaged positions ───────────────────────────────────────────────────
    if m['unmanaged']:
        console.print(
            f"\n[bold yellow]⚠ NO STOP ASSIGNED:[/] {', '.join(m['unmanaged'])}"
        )

    input("\nPress Enter to return to menu...")
