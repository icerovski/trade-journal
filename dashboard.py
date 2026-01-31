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
    # Fetch data (Force download ensures we get fresh data)
    data = portfolio_manager.fetch_nav_data(force_download=True)
    
    if not data:
        console.print("[red]No NAV data available. Check connection/config.[/red]")
        return 0.0
    
    total, accounts = data
    
    # Create Table
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
    Displays the portfolio dataframe.
    
    Args:
        df: The DataFrame from PortfolioManager
        total_nav_override: (float) The official Net Liquidation Value from IBKR.
                            If provided, this is used for the Header AUM.
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

    # Sort by Market Value (descending)
    df = df.sort_values('MarketValue', ascending=False)
    
    # Create Table
    table = Table(box=box.SIMPLE_HEAD, title=f"PORTFOLIO [AUM: {df.iloc[0]['CCY']} {total_aum:,.0f}] {title_suffix}")
    
    table.add_column("TICKER", style="bold cyan")
    table.add_column("COMPANY", style="dim", max_width=25, overflow="ellipsis")
    table.add_column("DATE", justify="right")
    table.add_column("QTY", justify="right")
    table.add_column("ENTRY", justify="right")
    table.add_column("PRICE", justify="right")
    table.add_column("MKT VAL", justify="right", style="bold")
    table.add_column("P/L", justify="right")
    table.add_column("P/L %", justify="right")
    table.add_column("AAGR", justify="right", style="magenta")

    for _, row in df.iterrows():
        # Color logic
        pl_color = "green" if row['P/L'] >= 0 else "red"
        
        # Date formatting
        date_str = row['Date'].strftime('%Y-%m-%d') if pd.notnull(row['Date']) else "-"

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
            f"{row['AAGR']:.1f}%"
        )

    console.print(table)