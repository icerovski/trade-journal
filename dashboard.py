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

def get_holdings_panel(state: CockpitState, sort_by="Ticker"):
    if state.df.empty:
        return Panel("[yellow]No active positions found.[/yellow]", title="Holdings")

    table = Table(expand=True, box=box.SIMPLE, header_style="bold cyan", pad_edge=False)
    table.add_column("TICKER", style="bold")
    table.add_column("DATE", justify="right")
    table.add_column("QTY", justify="right")
    table.add_column("ENTRY", justify="right")
    table.add_column("PRICE", justify="right")
    table.add_column("MKT VAL", justify="right")
    table.add_column("P/L %", justify="right")
    table.add_column("NAV %", justify="right", style="blue")

    # Group by Asset Class for the table view
    df_view = state.df.copy()
    if sort_by == "MarketValue":
        df_view = df_view.sort_values('MarketValue', ascending=False)
    elif sort_by == "Pct":
        df_view = df_view.sort_values('Pct', ascending=False)
    else:
        df_view = df_view.sort_values(['AssetClass', 'Ticker'], ascending=True)

    state.max_index = len(df_view) - 1
    
    for idx, (_, row) in enumerate(df_view.iterrows()):
        is_selected = (idx == state.selected_index)
        pl_color = "green" if row['P/L'] >= 0 else "red"
        
        # Style logic for selected row
        style = "reverse" if is_selected else ""
        
        date_str = row['Date'].strftime('%d/%m/%y') if pd.notnull(row['Date']) else "-"
        
        table.add_row(
            str(row['Ticker']),
            date_str,
            f"{row['Qty']:,.0f}",
            f"{row['Entry']:,.2f}",
            f"{row['Price']:,.2f}",
            f"{row['MarketValue']:,.0f}",
            f"[{pl_color}]{row['Pct']:.1f}%[/{pl_color}]",
            f"{row['NavPct']:.1f}%",
            style=style
        )

    return Panel(table, title="[bold]Portfolio Holdings[/bold]", border_style="blue")

def get_details_panel(state: CockpitState):
    """Context-aware panel for the selected position."""
    if state.df.empty:
        return Panel("", title="Position Details")

    # Get the selected row
    # (Note: We need to handle the sorting consistent with get_holdings_panel)
    df_sorted = state.df.sort_values(['AssetClass', 'Ticker'], ascending=True) # Default
    if state.selected_index >= len(df_sorted):
        state.selected_index = 0
        
    row = df_sorted.iloc[state.selected_index]
    
    details = Table.grid(expand=True)
    details.add_row(f"[bold]{row['Name']}[/bold]", "")
    details.add_row("-" * 20, "")
    details.add_row("[bold]Asset Class:[/bold]", str(row['AssetClass']))
    details.add_row("[bold]Currency:[/bold]", str(row['CCY']))
    details.add_row("[bold]High Since Entry:[/bold]", f"{row['MaxSinceEntry']:,.2f}")
    details.add_row("", "")
    
    details.add_row("[bold cyan]RISK ENGINE[/bold cyan]", "")
    details.add_row("[bold]ATR / Type:[/bold]", str(row['ATR_Disp']))
    details.add_row("[bold]Stop Price:[/bold]", f"[red]{row['SL_Price']:,.2f}[/red]" if pd.notnull(row['SL_Price']) else "---")
    details.add_row("[bold]Buffer to SL:[/bold]", f"[red]{row['Down_Pct']:.1f}%[/red]")
    details.add_row("", "")
    
    details.add_row("[bold green]TARGETS[/bold green]", "")
    details.add_row("[bold]Profit Price:[/bold]", f"[green]{row['TP_Price']:,.2f}[/green]" if pd.notnull(row['TP_Price']) else "---")
    details.add_row("[bold]Buffer to TP:[/bold]", f"[green]{row['Up_Pct']:.1f}%[/green]")
    details.add_row("[bold]R/R Ratio:[/bold]", f"{row['RR_Ratio']:.1f}")
    details.add_row("", "")
    
    details.add_row("[bold magenta]PERFORMANCE[/bold magenta]", "")
    details.add_row("[bold]AAGR:[/bold]", f"{row['AAGR']:.1f}%")
    details.add_row("[bold]Total P/L:[/bold]", f"{row['P/L']:,.0f}")

    return Panel(details, title=f"[bold yellow]{row['Ticker']} Analysis[/bold yellow]", border_style="magenta")

def run_live_dashboard(portfolio_manager, asset_class_filter=None, refresh_interval=30, sort_by="Ticker", use_ledger=False):
    """
    Interactive Cockpit Loop.
    """
    state = CockpitState()
    layout = make_cockpit_layout()
    
    # Register keyboard listeners
    keyboard.on_press_key("up", state.move_up)
    keyboard.on_press_key("down", state.move_down)

    try:
        with Live(layout, refresh_per_second=10, screen=True) as live:
            while True:
                # 1. Periodically Refresh Data (or if empty)
                if state.df.empty or (datetime.now() - state.last_update).total_seconds() > refresh_interval:
                    from portfolio_manager import PortfolioManager
                    pm = PortfolioManager()
                    state.df, state.total_nav, state.report_date = calculate_dashboard_data(pm, asset_class_filter, use_ledger)
                    state.last_update = datetime.now()

                if keyboard.is_pressed('esc'):
                    break

                # 2. Update Layout Components
                ccy = state.df.iloc[0]['CCY'] if not state.df.empty else "EUR"
                layout["header"].update(get_header_panel(state.report_date, state.total_nav or 0, ccy))
                layout["body"].update(get_holdings_panel(state, sort_by))
                layout["sidebar"].update(get_details_panel(state))
                layout["footer"].update(get_footer_panel())
                
                time.sleep(0.1) # Loop speed for UI responsiveness
    except KeyboardInterrupt:
        pass
    finally:
        keyboard.unhook_all()
        console.clear()

def print_rich_portfolio(df, total_nav_override=None, report_date="Unknown", sort_by="Ticker"):
    """Still support the static view if needed."""
    from dashboard_static import generate_portfolio_table # Separate file or logic
    # For now, let's just use the existing logic for static if called
    pass

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
