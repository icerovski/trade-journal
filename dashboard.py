import os
import time
import pandas as pd
import keyboard
from rich.console import Console
from rich.table import Table
from rich import box
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from datetime import datetime
from logger import log_system_milestone

# Log the recent improvement
log_system_milestone("Implemented Interactive Cockpit with arrow-key navigation and dynamic details panel")

console = Console()

class CockpitState:
    """Tracks interactive dashboard state."""
    def __init__(self):
        self.selected_index = 0
        self.max_index = 0
        self.df = pd.DataFrame()
        self.report_date = "Unknown"
        self.total_nav = 0.0
        self.last_update = datetime.now()

    def move_up(self, e=None):
        if self.selected_index > 0:
            self.selected_index -= 1

    def move_down(self, e=None):
        if self.selected_index < self.max_index:
            self.selected_index += 1

def calculate_dashboard_data(portfolio_manager, asset_class_filter=None, use_ledger=False):
    """Fetches data and returns (DataFrame, total_nav, report_date)."""
    nav_res = portfolio_manager.fetch_nav_data(force_download=False)
    real_nav, report_date = (nav_res[0], nav_res[2]) if nav_res else (None, "Unknown")
    df = portfolio_manager.get_dashboard_df(asset_class_filter=asset_class_filter, total_nav=real_nav, use_ledger=use_ledger)
    return df, real_nav, report_date

def make_cockpit_layout() -> Layout:
    """Defines the structure of the dashboard cockpit."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["main"].split_row(
        Layout(name="body", ratio=3),
        Layout(name="sidebar", ratio=1),
    )
    return layout

def get_header_panel(report_date, nav, ccy):
    return Panel(
        f"[bold cyan]PRIVATE EQUITY TRADING COCKPIT[/bold cyan] | IBKR: {report_date} | [bold green]AUM: {ccy} {nav:,.0f}[/bold green] | [dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
        box=box.HORIZONTALS, border_style="cyan"
    )

def get_footer_panel():
    return Panel(
        "[dim]Use [bold]↑/↓ ARROWS[/bold] to navigate positions | [bold]ESC[/bold] or [bold]Ctrl+C[/bold] to Exit[/dim]",
        title="[bold]Controls[/bold]", title_align="left", border_style="dim"
    )

def _generate_static_table(df, sort_by="Ticker"):
    """Helper to generate a rich Table for both static and cockpit views."""
    table = Table(expand=True, box=box.SIMPLE, header_style="bold cyan", pad_edge=False)
    table.add_column("TICKER", style="bold")
    table.add_column("DATE", justify="right")
    table.add_column("QTY", justify="right")
    table.add_column("ENTRY", justify="right")
    table.add_column("PRICE", justify="right")
    table.add_column("MKT VAL", justify="right")
    table.add_column("D-P/L", justify="right")
    table.add_column("D-%", justify="right")
    table.add_column("P/L-INC", justify="right")
    table.add_column("INC-%", justify="right")

    df_view = df.copy()
    if sort_by == "MarketValue":
        df_view = df_view.sort_values('MarketValue', ascending=False)
    elif sort_by == "Pct":
        df_view = df_view.sort_values('PL_Inc_Pct', ascending=False)
    else:
        df_view = df_view.sort_values(['AssetClass', 'Ticker'], ascending=True)

    for _, row in df_view.iterrows():
        daily_color = "green" if row['PL_Daily'] >= 0 else "red"
        inc_color = "green" if row['PL_Inc'] >= 0 else "red"
        date_str = row['Date'].strftime('%d/%m/%y') if pd.notnull(row['Date']) else "-"
        
        table.add_row(
            str(row['Ticker']),
            date_str,
            f"{row['Qty']:,.0f}",
            f"{row['Entry']:,.2f}",
            f"{row['Price']:,.2f}",
            f"{row['MarketValue']:,.0f}",
            f"[{daily_color}]{row['PL_Daily']:,.0f}[/{daily_color}]",
            f"[{daily_color}]{row['PL_Daily_Pct']:.1f}%[/{daily_color}]",
            f"[{inc_color}]{row['PL_Inc']:,.0f}[/{inc_color}]",
            f"[{inc_color}]{row['PL_Inc_Pct']:.1f}%[/{inc_color}]"
        )
    return table

def get_holdings_panel(state: CockpitState, sort_by="Ticker"):
    if state.df.empty:
        return Panel("[yellow]No active positions found.[/yellow]", title="Holdings")

    # Reuse the static table logic but with selection highlighting
    table = Table(expand=True, box=box.SIMPLE, header_style="bold cyan", pad_edge=False)
    table.add_column("TICKER", style="bold")
    table.add_column("DATE", justify="right")
    table.add_column("QTY", justify="right")
    table.add_column("ENTRY", justify="right")
    table.add_column("PRICE", justify="right")
    table.add_column("MKT VAL", justify="right")
    table.add_column("D-P/L", justify="right")
    table.add_column("D-%", justify="right")
    table.add_column("P/L-INC", justify="right")
    table.add_column("INC-%", justify="right")

    df_view = state.df.copy()
    if sort_by == "MarketValue":
        df_view = df_view.sort_values('MarketValue', ascending=False)
    elif sort_by == "Pct":
        df_view = df_view.sort_values('PL_Inc_Pct', ascending=False)
    else:
        df_view = df_view.sort_values(['AssetClass', 'Ticker'], ascending=True)

    state.max_index = len(df_view) - 1
    
    for idx, (_, row) in enumerate(df_view.iterrows()):
        is_selected = (idx == state.selected_index)
        daily_color = "green" if row['PL_Daily'] >= 0 else "red"
        inc_color = "green" if row['PL_Inc'] >= 0 else "red"
        style = "reverse" if is_selected else ""
        date_str = row['Date'].strftime('%d/%m/%y') if pd.notnull(row['Date']) else "-"
        
        table.add_row(
            str(row['Ticker']),
            date_str,
            f"{row['Qty']:,.0f}",
            f"{row['Entry']:,.2f}",
            f"{row['Price']:,.2f}",
            f"{row['MarketValue']:,.0f}",
            f"[{daily_color}]{row['PL_Daily']:,.0f}[/{daily_color}]",
            f"[{daily_color}]{row['PL_Daily_Pct']:.1f}%[/{daily_color}]",
            f"[{inc_color}]{row['PL_Inc']:,.0f}[/{inc_color}]",
            f"[{inc_color}]{row['PL_Inc_Pct']:.1f}%[/{inc_color}]",
            style=style
        )

    return Panel(table, title="[bold]Portfolio Holdings[/bold]", border_style="blue")

def get_details_panel(state: CockpitState):
    """Context-aware panel for the selected position."""
    if state.df.empty:
        return Panel("", title="Position Details")

    # Handle sorting consistent with get_holdings_panel (default is AssetClass/Ticker)
    df_sorted = state.df.sort_values(['AssetClass', 'Ticker'], ascending=True)
    if state.selected_index >= len(df_sorted):
        state.selected_index = 0
        
    row = df_sorted.iloc[state.selected_index]
    
    details = Table.grid(expand=True)
    details.add_row(f"[bold yellow]{row['Name']}[/bold yellow]", "")
    details.add_row("-" * 25, "")
    
    # Block 1: Structural Context
    details.add_row("[bold cyan]STRUCTURE[/bold cyan]", "")
    details.add_row("ISIN:", str(row.get('ISIN', '---')))
    details.add_row("Exchange:", str(row.get('ListingExchange', '---')))
    details.add_row("Underlying:", str(row.get('UnderlyingSymbol', '---')))
    details.add_row("Asset Class:", str(row.get('AssetClass', '---')))
    details.add_row("Currency:", str(row.get('CCY', '---')))
    details.add_row("", "")
    
    # Block 2: Portfolio Impact (The "R" Constraint)
    details.add_row("[bold yellow]PORTFOLIO IMPACT[/bold yellow]", "")
    details.add_row("NAV Weight:", f"[bold yellow]{row['NavPct']:.1f}%[/bold yellow]")
    
    # Calculate R-Ratio (Risk Value / NAV Value)
    # We assume total_nav is known in state
    r_ratio = (row['Risk_Val'] / state.total_nav) if state.total_nav and state.total_nav > 0 else 0
    r_color = "green" if r_ratio <= 1.0 else "red"
    details.add_row("R (Risk Ratio):", f"[{r_color}]{r_ratio:.2f}[/{r_color}]")
    details.add_row("Cash at Risk:", f"{row['CCY']} {row['Risk_Val']:,.0f}")
    details.add_row("", "")
    
    # Block 3: Risk Engine
    details.add_row("[bold cyan]RISK ENGINE[/bold cyan]", "")
    details.add_row("ATR / Type:", str(row['ATR_Disp']))
    details.add_row("Stop Price:", f"[red]{row['SL_Price']:,.2f}[/red]" if pd.notnull(row['SL_Price']) else "---")
    details.add_row("Buffer to SL:", f"[red]{row['Down_Pct']:.1f}%[/red]")
    details.add_row("Target Price:", f"[green]{row['TP_Price']:,.2f}[/green]" if pd.notnull(row['TP_Price']) else "---")
    details.add_row("R/R Ratio:", f"{row['RR_Ratio']:.1f}")
    details.add_row("", "")
    
    # Block 4: Performance
    details.add_row("[bold magenta]PERFORMANCE[/bold magenta]", "")
    details.add_row("High Since Entry:", f"{row['MaxSinceEntry']:,.2f}")
    details.add_row("AAGR:", f"{row['AAGR']:.1f}%")
    details.add_row("Days Since Entry:", f"{row['Age_Days']:.0f} days")

    return Panel(details, title=f"[bold]{row['Ticker']} Analysis[/bold]", border_style="magenta")

def run_live_dashboard(portfolio_manager, asset_class_filter=None, refresh_interval=30, sort_by="Ticker", use_ledger=False):
    """
    Interactive Cockpit Loop. If refresh_interval is None, it acts as a static interactive view.
    """
    state = CockpitState()
    layout = make_cockpit_layout()
    
    # Register keyboard listeners
    keyboard.on_press_key("up", state.move_up)
    keyboard.on_press_key("down", state.move_down)

    # Initial Data Load
    from portfolio_manager import PortfolioManager
    pm = PortfolioManager()
    state.df, state.total_nav, state.report_date = calculate_dashboard_data(pm, asset_class_filter, use_ledger)
    state.last_update = datetime.now()

    try:
        with Live(layout, refresh_per_second=10, screen=True) as live:
            while True:
                # 1. Periodically Refresh Data (only if refresh_interval is set)
                if refresh_interval and (datetime.now() - state.last_update).total_seconds() > refresh_interval:
                    state.df, state.total_nav, state.report_date = calculate_dashboard_data(pm, asset_class_filter, use_ledger)
                    state.last_update = datetime.now()

                if keyboard.is_pressed('esc'):
                    break

                # 2. Update Layout Components
                if not state.df.empty:
                    ccy = state.df.iloc[0]['CCY'] if 'CCY' in state.df.columns else "EUR"
                    layout["header"].update(get_header_panel(state.report_date, state.total_nav or 0, ccy))
                    layout["body"].update(get_holdings_panel(state, sort_by))
                    layout["sidebar"].update(get_details_panel(state))
                    layout["footer"].update(get_footer_panel())
                else:
                    layout["body"].update(Panel("[yellow]No data to display.[/yellow]"))
                
                time.sleep(0.1) # Loop speed for UI responsiveness
    except KeyboardInterrupt:
        pass
    finally:
        keyboard.unhook_all()
        console.clear()

def print_rich_portfolio(df, total_nav_override=None, report_date="Unknown", sort_by="Ticker"):
    """
    Legacy static view. Now redirects to the interactive non-refreshing cockpit
    for full feature parity (navigation, details, etc).
    """
    # Note: We need the portfolio manager to handle the data if redirected.
    # For a pure 'print', we could just show the table, but user requested parity.
    from portfolio_manager import PortfolioManager
    run_live_dashboard(PortfolioManager(), sort_by=sort_by, refresh_interval=None)

def print_nav_table(portfolio_manager, force_download=False):
    """Displays NAV account balances."""
    data = portfolio_manager.fetch_nav_data(force_download=force_download)
    if not data:
        console.print("[red]No local NAV data available.[/red]")
        return 0.0
    
    total, accounts, report_date = data
    table = Table(box=box.SIMPLE_HEAD, title=f"[bold]ACCOUNT BALANCES (IBKR {report_date})[/bold]")
    table.add_column("ALIAS", style="cyan")
    table.add_column("NAV", justify="right", style="green")
    
    for a in accounts:
        table.add_row(str(a['alias']), f"€{a['nav']:,.2f}")
    
    table.add_section()
    table.add_row("TOTAL", f"€{total:,.2f}")
    console.print(table)
    return total
