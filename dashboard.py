import os
import time
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box
from rich.live import Live

console = Console()

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def calculate_dashboard_data(portfolio_manager, asset_class_filter=None):
    """
    Substep 1: Make all calculations.
    Returns (DataFrame, total_nav)
    """
    # 1. Fetch NAV
    nav_data = portfolio_manager.fetch_nav_data(force_download=False)
    real_nav = nav_data[0] if nav_data else None
    
    # 2. Get Data (Passing NAV for % calc)
    df = portfolio_manager.get_dashboard(asset_class_filter=asset_class_filter, total_nav=real_nav)
    return df, real_nav

def generate_portfolio_table(df, total_nav_override=None):
    """
    Substep 2: Format the dashboard and return the Rich Table object.
    """
    if df.empty:
        return Table.grid().add_row("[yellow]No active positions found.[/yellow]")

    # Determine AUM for the Header
    if total_nav_override:
        total_aum = total_nav_override
        title_suffix = "(Real NAV)"
    else:
        total_aum = df['MarketValue'].sum()
        title_suffix = "(Sum of Pos)"

    # Sort by Market Value
    df = df.sort_values('MarketValue', ascending=False)
    
    # Use currency from first row if available
    ccy = df.iloc[0]['CCY'] if not df.empty else "???"
    
    # Create Table
    table = Table(box=box.SIMPLE_HEAD, title=f"[bold]PORTFOLIO [AUM: {ccy} {total_aum:,.0f}] {title_suffix}[/bold]")
    
    table.add_column("TICKER", style="bold cyan")
    table.add_column("COMPANY", style="dim", max_width=20, overflow="ellipsis")
    table.add_column("DATE", justify="right")
    table.add_column("QTY", justify="right")
    table.add_column("ENTRY", justify="right")
    table.add_column("PRICE", justify="right")
    table.add_column("MKT VAL", justify="right", style="bold")
    table.add_column("P/L", justify="right")
    table.add_column("P/L %", justify="right")
    table.add_column("AAGR", justify="right", style="magenta")
    table.add_column("% NAV", justify="right", style="blue")

    # --- Print Rows ---
    for _, row in df.iterrows():
        pl_color = "green" if row['P/L'] >= 0 else "red"
        date_str = row['Date'].strftime('%Y-%m-%d') if pd.notnull(row['Date']) else "-"
        
        # Handle NavPct safely
        nav_pct = row.get('NavPct', 0.0)

        table.add_row(
            str(row['Ticker']),
            str(row['Name']),
            date_str,
            f"{row['Qty']:,.0f}",
            f"{row['Entry']:,.2f}",
            f"{row['Price']:,.2f}",
            f"{row['MarketValue']:,.0f}",
            f"[{pl_color}]{row['P/L']:,.0f}[/{pl_color}]",
            f"[{pl_color}]{row['Pct']:.1f}%[/{pl_color}]",
            f"{row['AAGR']:.1f}%",
            f"{nav_pct:.1f}%"
        )

    # --- Totals ---
    total_mv = df['MarketValue'].sum()
    total_pl = df['P/L'].sum()
    total_nav_pct = df['NavPct'].sum() # Sum of exposures
    
    total_cost = total_mv - total_pl
    total_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0.0
    total_color = "green" if total_pl >= 0 else "red"

    table.add_section()
    table.add_row(
        "TOTAL", "", "", "", "", "",
        f"{total_mv:,.0f}",
        f"[{total_color}]{total_pl:,.0f}[/{total_color}]",
        f"[{total_color}]{total_pct:.1f}%[/{total_color}]",
        "",
        f"{total_nav_pct:.1f}%"
    )

    return table

def print_rich_portfolio(df, total_nav_override=None):
    """Simple wrapper for one-time print."""
    table = generate_portfolio_table(df, total_nav_override)
    console.print(table)

def run_live_dashboard(portfolio_manager, asset_class_filter=None, refresh_interval=30):
    """
    Continuous refresh loop for the dashboard.
    """
    console.print(f"[cyan]Entering Live Dashboard (Refreshing every {refresh_interval}s)... Press Ctrl+C to exit.[/cyan]")
    time.sleep(1)
    
    try:
        with Live(auto_refresh=False) as live:
            while True:
                # 1. Recalculate
                from portfolio_manager import PortfolioManager
                pm = PortfolioManager() # Refresh data from DB each time
                df, real_nav = calculate_dashboard_data(pm, asset_class_filter)
                
                # 2. Update Display
                table = generate_portfolio_table(df, real_nav)
                live.update(table, refresh=True)
                
                time.sleep(refresh_interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Live dashboard stopped.[/yellow]")

def print_nav_table(portfolio_manager):
    """
    Uses the PortfolioManager to fetch and display NAV data.
    """
    data = portfolio_manager.fetch_nav_data(force_download=True)
    if not data:
        console.print("[red]No NAV data available. Check connection/config.[/red]")
        return 0.0
    
    total, accounts = data
    table = Table(box=box.SIMPLE_HEAD, title="[bold]ACCOUNT BALANCES (IBKR)[/bold]")
    table.add_column("ALIAS", style="cyan")
    table.add_column("NAV", justify="right", style="green")
    
    for a in accounts:
        table.add_row(str(a['alias']), f"€{a['nav']:,.2f}")
    
    table.add_section()
    table.add_row("TOTAL", f"€{total:,.2f}")
    
    console.print(table)
    return total