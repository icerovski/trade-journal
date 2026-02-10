import os
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

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

def print_rich_portfolio(df, total_nav_override=None):
    """
    Displays the portfolio dataframe with % NAV column.
    """
    if df.empty:
        console.print("[yellow]No active positions found.[/yellow]")
        return

    # Determine AUM for the Header
    if total_nav_override:
        total_aum = total_nav_override
        title_suffix = "(Real NAV)"
    else:
        total_aum = df['MarketValue'].sum()
        title_suffix = "(Sum of Pos)"

    # Sort by Market Value
    df = df.sort_values('MarketValue', ascending=False)
    
    # Create Table
    table = Table(box=box.SIMPLE_HEAD, title=f"PORTFOLIO [AUM: {df.iloc[0]['CCY']} {total_aum:,.0f}] {title_suffix}")
    
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
    table.add_column("% NAV", justify="right", style="blue") # <-- NEW COLUMN

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
            f"{nav_pct:.1f}%" # <-- NEW VALUE
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
        f"{total_nav_pct:.1f}%" # <-- TOTAL EXPOSURE
    )

    console.print(table)