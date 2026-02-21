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
from core.portfolio_manager import PortfolioManager

# Log the recent improvement
log_system_milestone("Fixed Dashboard scrolling by disabling wrapping and increasing layout padding")

console = Console()

class CockpitState:
    """Tracks interactive dashboard state."""
    def __init__(self):
        self.selected_index = 0
        self.max_index = 0
        self.df = pd.DataFrame()
        self.df_view = pd.DataFrame() # Sorted/Filtered view
        self.report_date = "Unknown"
        self.total_nav = 0.0
        self.last_update = datetime.now()
        self.scroll_offset = 0
        self.visible_rows = 10 # Default
        self.last_key_time = 0

    def update_data(self, df, total_nav, report_date, sort_by="Ticker"):
        self.df = df
        self.total_nav = total_nav
        self.report_date = report_date
        
        if df.empty:
            self.df_view = df
            self.max_index = 0
            return

        if sort_by == "MarketValue":
            self.df_view = df.sort_values('MarketValue', ascending=False)
        elif sort_by == "Pct":
            self.df_view = df.sort_values('PL_Inc_Pct', ascending=False)
        else:
            self.df_view = df.sort_values(['AssetClass', 'Ticker'], ascending=True)

        self.max_index = len(self.df_view) - 1
        if self.selected_index > self.max_index:
            self.selected_index = max(0, self.max_index)

    def handle_input(self):
        """Polls for keyboard input with throttling."""
        now = time.time()
        if now - self.last_key_time < 0.1: # Throttle to ~10 commands/sec for stability
            return

        moved = False
        if keyboard.is_pressed('up'):
            if self.selected_index > 0:
                self.selected_index -= 1
                moved = True
        elif keyboard.is_pressed('down'):
            if self.selected_index < self.max_index:
                self.selected_index += 1
                moved = True
        
        if moved:
            self.last_key_time = now
            self._adjust_scroll()

    def _adjust_scroll(self):
        """Aggressive sticky scroll: Keep cursor centered where possible."""
        # Calculate scroll window boundaries
        # We want to keep the selected_index between [scroll_offset, scroll_offset + visible_rows]
        
        padding = 2 # Keep 2 rows visible at edges
        
        # Cursor moved above the top padding line
        if self.selected_index < self.scroll_offset + padding:
            self.scroll_offset = max(0, self.selected_index - padding)
            
        # Cursor moved below the bottom padding line
        elif self.selected_index >= self.scroll_offset + self.visible_rows - padding:
            self.scroll_offset = min(
                max(0, self.max_index - self.visible_rows + 1),
                self.selected_index - self.visible_rows + padding + 1
            )

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
        f"[bold cyan]PRIVATE EQUITY TRADING COCKPIT[/bold cyan] | [bold green]BATCH-MD[/bold green] | IBKR: {report_date} | [bold green]AUM: {ccy} {nav:,.0f}[/bold green] | [dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
        box=box.HORIZONTALS, border_style="cyan"
    )

def get_footer_panel():
    return Panel(
        "[dim]Use [bold]↑/↓ ARROWS[/bold] to navigate | [bold]ESC[/bold] to Exit[/dim]",
        title="[bold]Controls[/bold]", title_align="left", border_style="dim"
    )

def get_holdings_panel(state: CockpitState):
    if state.df_view.empty:
        return Panel("[yellow]No active positions found.[/yellow]", title="Holdings")

    # CRITICAL: Disable wrapping to ensure 1 row = 1 terminal line
    table = Table(expand=True, box=box.SIMPLE, header_style="bold cyan", pad_edge=False)
    table.add_column("TICKER", style="bold", no_wrap=True)
    table.add_column("PRICE", justify="right", no_wrap=True)
    table.add_column("QTY", justify="right", no_wrap=True)
    table.add_column("P/L", justify="right", no_wrap=True)
    table.add_column("P/L %", justify="right", no_wrap=True)
    table.add_column("UNRLZD P&L", justify="right", no_wrap=True)
    table.add_column("UNRLZD P&L %", justify="right", no_wrap=True)
    table.add_column("COST BASIS", justify="right", no_wrap=True)
    table.add_column("MKT VAL", justify="right", no_wrap=True)
    table.add_column("% NAV", justify="right", no_wrap=True)

    # Calculate visible slice
    start_idx = int(state.scroll_offset)
    end_idx = min(start_idx + int(state.visible_rows), len(state.df_view))
    
    df_slice = state.df_view.iloc[start_idx:end_idx]
    
    for idx_relative, (_, row) in enumerate(df_slice.iterrows()):
        idx_absolute = start_idx + idx_relative
        is_selected = (idx_absolute == state.selected_index)
        daily_color = "green" if row['PL_Daily'] >= 0 else "red"
        inc_color = "green" if row['PL_Inc'] >= 0 else "red"
        style = "reverse" if is_selected else ""
        
        # Signal Stop/Target breaches
        ticker_display = str(row['Ticker'])
        if pd.notnull(row['SL_Price']) and row['Price'] <= row['SL_Price']:
            ticker_display = f"[bold red]{ticker_display}[/bold red]"
        elif pd.notnull(row['TP_Price']) and row['Price'] >= row['TP_Price']:
            ticker_display = f"[bold green]{ticker_display}[/bold green]"
        
        table.add_row(
            ticker_display,
            f"{row['Price']:,.2f}",
            f"{row['Qty']:,.0f}",
            f"[{daily_color}]{row['PL_Daily']:,.0f}[/{daily_color}]",
            f"[{daily_color}]{row['PL_Daily_Pct']:.1f}%[/{daily_color}]",
            f"[{inc_color}]{row['PL_Inc']:,.0f}[/{inc_color}]",
            f"[{inc_color}]{row['PL_Inc_Pct']:.1f}%[/{inc_color}]",
            f"{row['CostBasis']:,.0f}",
            f"{row['MarketValue']:,.0f}",
            f"{row['NavPct']:.1f}%",
            style=style
        )

    title = f"[bold]Portfolio Holdings ({state.selected_index+1}/{len(state.df_view)})[/bold]"
    return Panel(table, title=title, border_style="blue")

def get_details_panel(state: CockpitState):
    """Context-aware panel for the selected position."""
    if state.df_view.empty:
        return Panel("", title="Position Details")

    if state.selected_index >= len(state.df_view):
        state.selected_index = 0
        
    row = state.df_view.iloc[state.selected_index]
    
    details = Table.grid(expand=True)
    details.add_row(f"[bold yellow]{row['Name']}[/bold yellow]", "")
    details.add_row("-" * 25, "")
    
    # Block 1: Structural Context
    details.add_row("[bold cyan]STRUCTURE[/bold cyan]", "")
    details.add_row("Exchange:", str(row.get('ListingExchange', '---')))
    details.add_row("Underlying:", str(row.get('UnderlyingSymbol', '---')))
    details.add_row("Asset Class:", str(row.get('AssetClass', '---')))
    details.add_row("Currency:", str(row.get('CCY', '---')))
    details.add_row("", "")
    
    # Block 3: Risk Parameters
    s_type = str(row.get('StopType', '---'))
    atr_val = row.get('ATR', 0.0)
    stop_base = row['MaxSinceEntry'] if s_type == 'TRAILING' else row['Entry']
    sl_pct = (atr_val / stop_base * 100) if stop_base > 0 else 0
    stop_pl_color = "green" if row['Risk_Val'] >= 0 else "red"

    details.add_row("[bold cyan]RISK PARAMETERS[/bold cyan]", "")
    details.add_row("ATR:", f"{atr_val:.2f}")
    details.add_row("Stop Loss %:", f"{sl_pct:.1f}%")
    details.add_row("Stop Type:", s_type)
    details.add_row("Stop Price:", f"[bold red]{row['SL_Price']:,.2f}[/bold red]" if pd.notnull(row['SL_Price']) else "---")
    details.add_row("P/L at Stop:", f"[{stop_pl_color}]{row['Risk_Val']:,.0f}[/{stop_pl_color}]")
    details.add_row("Buffer to SL:", f"[red]{row['Down_Pct']:.1f}%[/red]")
    details.add_row("", "")
    
    # Block 4: Risk Engine - TARGET PROFIT
    details.add_row("[bold green]TARGET PROFIT[/bold green]", "")
    details.add_row("Target Type:", s_type)
    details.add_row("Target Price:", f"[bold green]{row['TP_Price']:,.2f}[/bold green]" if pd.notnull(row['TP_Price']) else "---")
    details.add_row("P/L at Target:", f"[green]{row['Reward_Val']:,.0f}[/green]")
    details.add_row("Buffer to Target:", f"[green]{row['Up_Pct']:.1f}%[/green]")
    details.add_row("", "")
    
    # Block 5: Performance
    details.add_row("[bold magenta]PERFORMANCE[/bold magenta]", "")
    details.add_row("Inception:", row['Date'].strftime('%d-%b-%y') if pd.notnull(row['Date']) else "---")
    details.add_row("Avg Cost:", f"{row['Entry']:,.2f}")
    details.add_row("High Since Entry:", f"{row['MaxSinceEntry']:,.2f}")
    details.add_row("AAGR:", f"{row['AAGR']:.1f}%")
    details.add_row("Days Since Entry:", f"{row['Age_Days']:.0f} days")

    return Panel(details, title=f"[bold]{row['Ticker']} Analysis[/bold]", border_style="magenta")

def run_live_dashboard(portfolio_manager, asset_class_filter=None, refresh_interval=30, sort_by="Ticker", use_ledger=False):
    """
    Interactive Cockpit Loop.
    """
    state = CockpitState()
    layout = make_cockpit_layout()
    
    # Initial Data Load
    pm = PortfolioManager()
    df, nav, r_date = calculate_dashboard_data(pm, asset_class_filter, use_ledger)
    state.update_data(df, nav, r_date, sort_by)
    state.last_update = datetime.now()

    try:
        with Live(layout, refresh_per_second=15, screen=True) as live:
            while True:
                # Dynamically calculate visible rows
                # Overhead calculation:
                # Header (3) + Footer (3) + Panel Borders (2) + Table Header (2) + Margin (1) = 11 lines
                # We use 11 lines overhead to maximize screen usage
                state.visible_rows = max(5, console.size.height - 11)

                # 1. Handle keyboard input via polling
                state.handle_input()

                if keyboard.is_pressed('esc'):
                    break

                # 2. Periodically Refresh Data
                if refresh_interval and (datetime.now() - state.last_update).total_seconds() > refresh_interval:
                    df, nav, r_date = calculate_dashboard_data(pm, asset_class_filter, use_ledger)
                    state.update_data(df, nav, r_date, sort_by)
                    state.last_update = datetime.now()

                # 3. Update Layout Components
                if not state.df_view.empty:
                    ccy = state.df_view.iloc[0]['CCY'] if 'CCY' in state.df_view.columns else "EUR"
                    layout["header"].update(get_header_panel(state.report_date, state.total_nav or 0, ccy))
                    layout["body"].update(get_holdings_panel(state))
                    layout["sidebar"].update(get_details_panel(state))
                    layout["footer"].update(get_footer_panel())
                else:
                    layout["body"].update(Panel("[yellow]No data to display.[/yellow]"))
                
                time.sleep(0.02) # Higher polling frequency for input
    except KeyboardInterrupt:
        pass
    finally:
        keyboard.unhook_all()
        console.clear()

def print_rich_portfolio(df, total_nav_override=None, report_date="Unknown", sort_by="Ticker"):
    """Legacy entry point."""
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
