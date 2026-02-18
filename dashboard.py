import os
import time
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box
from rich.live import Live

console = Console()

def calculate_dashboard_data(portfolio_manager, asset_class_filter=None, use_ledger=False):
    """
    Substep 1: Make all calculations.
    Returns (DataFrame, total_nav, report_date)
    """
    # 1. Fetch NAV from LOCAL file only
    nav_res = portfolio_manager.fetch_nav_data(force_download=False)
    real_nav, report_date = (nav_res[0], nav_res[2]) if nav_res else (None, "Unknown")
    
    # 2. Get Data using the new enriched method
    df = portfolio_manager.get_dashboard_df(asset_class_filter=asset_class_filter, total_nav=real_nav, use_ledger=use_ledger)
    return df, real_nav, report_date

def generate_portfolio_table(df, total_nav_override=None, report_date="Unknown", sort_by="Ticker"):
    """
    Substep 2: Format the dashboard and return the Rich Table object.
    Groups by Asset Class and includes Risk Metrics (Age, ATR Placeholder).
    """
    if df.empty:
        return Table.grid().add_row("[yellow]No active positions found.[/yellow]")

    # 1. Prepare Table
    ccy = df.iloc[0]['CCY'] if not df.empty else "EUR"
    total_aum = total_nav_override if total_nav_override else df['MarketValue'].sum()
    title = f"[bold]PORTFOLIO RISK DASHBOARD [AUM: {ccy} {total_aum:,.0f}] (Report: {report_date})[/bold]"
    table = Table(box=box.HORIZONTALS, title=title, header_style="bold cyan", show_footer=True, padding=0)
    
    # Columns
    table.add_column("TICKER", style="bold")
    table.add_column("COMPANY", style="dim", max_width=15, overflow="ellipsis")
    table.add_column("DATE", justify="right")
    table.add_column("QTY", justify="right")
    table.add_column("ENTRY", justify="right")
    table.add_column("PRICE", justify="right")
    table.add_column("MKT VAL", justify="right", style="bold")
    table.add_column("P/L", justify="right")
    table.add_column("SL PRICE", justify="right", style="red")
    table.add_column("DOWN %", justify="right", style="red")
    table.add_column("TP PRICE", justify="right", style="green")
    table.add_column("UP %", justify="right", style="green")
    table.add_column("RISK", justify="right", style="magenta")
    table.add_column("R/R", justify="right", style="cyan")
    table.add_column("AAGR", justify="right", style="magenta")
    table.add_column("AGE", justify="right", style="yellow")
    table.add_column("ATR", justify="right", style="cyan")
    table.add_column("% NAV", justify="right", style="blue")

    # 2. Group by Asset Class
    asset_groups = df.groupby('AssetClass')
    
    today = pd.Timestamp.now()
    
    for asset_class, group in asset_groups:
        # Sort group
        if sort_by == "MarketValue":
            group = group.sort_values('MarketValue', ascending=False)
        elif sort_by == "Pct":
            group = group.sort_values('Pct', ascending=False)
        else:
            group = group.sort_values('Ticker', ascending=True)

        # Add Section Header
        table.add_row(f"[bold white underline]{asset_class}[/bold white underline]", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "")

        group_mv = group['MarketValue'].sum()
        group_pl = group['P/L'].sum()
        group_risk = group['Risk_Val'].sum()
        group_nav = group['NavPct'].sum()

        for _, row in group.iterrows():
            pl_color = "green" if row['P/L'] >= 0 else "red"
            
            # Date String
            date_str = row['Date'].strftime('%d/%m/%y') if pd.notnull(row['Date']) else "-"

            # Calculate Age String
            entry_date = pd.to_datetime(row['Date'])
            days = (today - entry_date).days
            if days > 365:
                age_str = f"{days/365.25:.1f}y"
            else:
                age_str = f"{days}d"

            # Risk Prices
            sl_str = f"{row['SL_Price']:,.2f}" if pd.notnull(row['SL_Price']) else "---"
            tp_str = f"{row['TP_Price']:,.2f}" if pd.notnull(row['TP_Price']) else "---"

            table.add_row(
                str(row['Ticker']),
                str(row['Name']),
                date_str,
                f"{row['Qty']:,.0f}",
                f"{row['Entry']:,.2f}",
                f"{row['Price']:,.2f}",
                f"{row['MarketValue']:,.0f}",
                f"[{pl_color}]{row['P/L']:,.0f}[/{pl_color}]",
                sl_str,
                f"{row['Down_Pct']:.1f}%",
                tp_str,
                f"{row['Up_Pct']:.1f}%",
                f"{row['Risk_Val']:,.0f}",
                f"{row['RR_Ratio']:.1f}",
                f"{row['AAGR']:.1f}%",
                age_str,
                str(row.get('ATR_Disp', '---')),
                f"{row['NavPct']:.1f}%"
            )
        
        # Subtotal for Asset Class
        table.add_row(
            f"[dim]{asset_class} TOTAL[/dim]", "", "", "", "", "",
            f"[dim]{group_mv:,.0f}[/dim]",
            f"[dim]{group_pl:,.0f}[/dim]", "", "", "", "", 
            f"[dim]{group_risk:,.0f}[/dim]", "", "", "", "",
            f"[dim]{group_nav:.1f}%[/dim]"
        )
        table.add_section()

    # 3. Final Footer
    total_mv = df['MarketValue'].sum()
    total_pl = df['P/L'].sum()
    total_risk = df['Risk_Val'].sum()
    total_nav_sum = df['NavPct'].sum()

    table.columns[0].footer = "GRAND TOTAL"
    table.columns[6].footer = f"{total_mv:,.0f}"
    table.columns[7].footer = f"{total_pl:,.0f}"
    table.columns[12].footer = f"{total_risk:,.0f}"
    table.columns[17].footer = f"{total_nav_sum:.1f}%"

    return table

def print_rich_portfolio(df, total_nav_override=None, report_date="Unknown", sort_by="Ticker"):
    """Simple wrapper for one-time print."""
    table = generate_portfolio_table(df, total_nav_override, report_date, sort_by=sort_by)
    console.print(table)

def run_live_dashboard(portfolio_manager, asset_class_filter=None, refresh_interval=30, sort_by="Ticker", use_ledger=False):
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
                df, real_nav, report_date = calculate_dashboard_data(pm, asset_class_filter, use_ledger=use_ledger)
                
                # 2. Update Display
                table = generate_portfolio_table(df, real_nav, report_date, sort_by=sort_by)
                live.update(table, refresh=True)
                
                time.sleep(refresh_interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Live dashboard stopped.[/yellow]")

def print_nav_table(portfolio_manager, force_download=False):
    """
    Uses the PortfolioManager to fetch and display NAV data.
    """
    data = portfolio_manager.fetch_nav_data(force_download=force_download)
    if not data:
        console.print("[red]No local NAV data available. Please Sync first.[/red]")
        return 0.0
    
    total, accounts, report_date = data
    table = Table(box=box.SIMPLE_HEAD, title=f"[bold]ACCOUNT BALANCES (IBKR as of {report_date})[/bold]")
    table.add_column("ALIAS", style="cyan")
    table.add_column("NAV", justify="right", style="green")
    
    for a in accounts:
        table.add_row(str(a['alias']), f"€{a['nav']:,.2f}")
    
    table.add_section()
    table.add_row("TOTAL", f"€{total:,.2f}")
    
    console.print(table)
    return total
