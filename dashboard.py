import os
import time
import threading
import pandas as pd
import keyboard
from rich.console import Console
from rich.table import Table
from rich import box
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from datetime import datetime
from logger import logger, log_system_milestone, disable_console_logging, enable_console_logging
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
        self.is_refreshing = False
        self.lock = threading.Lock()

    def update_data(self, df, total_nav, report_date, sort_by="Ticker"):
        with self.lock:
            try:
                self.df = df
                self.total_nav = total_nav
                self.report_date = report_date
                
                if df.empty:
                    self.df_view = df
                    self.max_index = 0
                    return

                if sort_by == "MarketValue" and "MarketValue" in df.columns:
                    self.df_view = df.sort_values('MarketValue', ascending=False)
                elif sort_by == "Pct" and "PL_Inc_Pct" in df.columns:
                    self.df_view = df.sort_values('PL_Inc_Pct', ascending=False)
                elif sort_by == "PL" and "PL_Inc" in df.columns:
                    self.df_view = df.sort_values('PL_Inc', ascending=False)
                elif sort_by == "Date" and "Date" in df.columns:
                    self.df_view = df.sort_values('Date', ascending=True)
                else:
                    sort_cols = [c for c in ['AssetClass', 'Ticker'] if c in df.columns]
                    if sort_cols:
                        self.df_view = df.sort_values(sort_cols, ascending=True)
                    else:
                        self.df_view = df

                self.max_index = len(self.df_view) - 1
                if self.selected_index > self.max_index:
                    self.selected_index = max(0, self.max_index)
                
            except Exception as e:
                logger.error(f"update_data Critical Error: {e}")
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

def calculate_dashboard_data(portfolio_manager, asset_class_filter=None, use_ledger=False, silent=False):
    """Fetches data and returns (DataFrame, total_nav, report_date)."""
    if silent:
        disable_console_logging()
    
    try:
        nav_res = portfolio_manager.fetch_nav_data(force_download=False)
        
        if nav_res:
            real_nav, accounts, report_date = nav_res
        else:
            real_nav, report_date = 0.0, "Unknown"
        
        df = portfolio_manager.get_dashboard_df(
            asset_class_filter=asset_class_filter, 
            total_nav=real_nav, 
            use_ledger=use_ledger,
            silent=silent
        )
        
        return df, real_nav, report_date
    except Exception as e:
        logger.error(f"calculate_dashboard_data Error: {e}")
        return pd.DataFrame(), 0.0, "Error"
    finally:
        if silent:
            enable_console_logging()

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

def get_header_panel(state: CockpitState, ccy="EUR"):
    refresh_tag = " [bold yellow][REFRESHING...][/bold yellow]" if state.is_refreshing else ""
    nav_val = state.total_nav if state.total_nav is not None else 0.0
    return Panel(
        f"[bold cyan]PRIVATE EQUITY TRADING COCKPIT[/bold cyan] | [bold green]BATCH-MD[/bold green] | IBKR: {state.report_date} | [bold green]AUM: {ccy} {nav_val:,.0f}[/bold green] | [dim]{datetime.now().strftime('%H:%M:%S')}[/dim]{refresh_tag}",
        box=box.HORIZONTALS, border_style="cyan"
    )

def get_footer_panel():
    return Panel(
        "[dim]Use [bold]↑/↓ ARROWS[/bold] to navigate | [bold]ESC[/bold] to Exit[/dim]",
        title="[bold]Controls[/bold]", title_align="left", border_style="dim"
    )

def get_holdings_panel(state: CockpitState):
    if state.df_view.empty:
        if state.is_refreshing:
            return Panel("\n\n[bold yellow]   INITIALIZING MARKET DATA...[/bold yellow]\n\n", title="Holdings", border_style="blue")
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
    details.add_row("First Entry Date:", row['Date'].strftime('%d-%b-%y') if pd.notnull(row['Date']) else "---")
    details.add_row("Avg Cost:", f"{row['Entry']:,.2f}")
    details.add_row("High Since Entry:", f"{row['MaxSinceEntry']:,.2f}")
    details.add_row("AAGR:", f"{row['AAGR']:.1f}%")
    details.add_row("Days Since Entry:", f"{row['Age_Days']:.0f} days")

    return Panel(details, title=f"[bold]{row['Ticker']} Analysis[/bold]", border_style="magenta")

def run_live_dashboard(portfolio_manager, asset_class_filter=None, refresh_interval: int | None = 60, sort_by="Ticker", use_ledger=False):
    """
    Interactive Cockpit Loop with background refreshes.
    """
    logger.info(f"Dashboard: run_live_dashboard initiated (Filter: {asset_class_filter}).")
    state = CockpitState()
    layout = make_cockpit_layout()
    pm = PortfolioManager()

    # CRITICAL: Do the first load SYNCHRONOUSLY so we can see any errors in the console
    # before the 'Live' context takes over the screen.
    try:
        console.print("[cyan]Initializing dashboard data...[/cyan]")
        df, nav, r_date = calculate_dashboard_data(pm, asset_class_filter, use_ledger, silent=False)
        if df is not None:
            state.update_data(df, nav, r_date, sort_by)
            state.last_update = datetime.now()
        state.is_refreshing = False
        console.print(f"[green]Initialization complete. {len(df)} positions found.[/green]")
    except Exception as e:
        logger.error(f"Dashboard: Initial synchronous load failed: {e}", exc_info=True)
        console.print(f"[red]Error during initialization: {e}[/red]")
        time.sleep(2)

    def refresh_worker():
        """Background thread for periodic refreshes."""
        if not refresh_interval:
            return

        while True:
            try:
                time.sleep(refresh_interval)
                state.is_refreshing = True
                logger.info("Dashboard: Periodic background refresh starting...")
                df, nav, r_date = calculate_dashboard_data(pm, asset_class_filter, use_ledger, silent=True)
                state.update_data(df, nav, r_date, sort_by)
                state.last_update = datetime.now()
                state.is_refreshing = False
                logger.info("Dashboard: Periodic refresh complete.")
            except Exception as e:
                logger.error(f"Dashboard: Periodic refresh error: {e}")
                state.is_refreshing = False

    # Start background thread only if refresh is enabled
    if refresh_interval:
        t = threading.Thread(target=refresh_worker, daemon=True)
        t.start()
        logger.info("Dashboard: Background thread spawned successfully.")

    try:
        with Live(layout, refresh_per_second=10, screen=True) as live:
            logger.info("Dashboard: Live UI context started.")
            while True:
                state.visible_rows = max(5, console.size.height - 11)
                
                # Input handling
                try:
                    state.handle_input()
                    if keyboard.is_pressed('esc'):
                        break
                except Exception as e:
                    logger.debug(f"Input handling error: {e}")

                # Update components
                with state.lock:
                    ccy = "EUR"
                    if not state.df_view.empty:
                        try:
                            # Extract CCY from first row if available
                            ccy = state.df_view.iloc[0]['CCY'] if 'CCY' in state.df_view.columns else "EUR"
                        except: pass
                    
                    layout["header"].update(get_header_panel(state, ccy))
                    layout["body"].update(get_holdings_panel(state))
                    layout["sidebar"].update(get_details_panel(state))
                    layout["footer"].update(get_footer_panel())
                
                time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            keyboard.unhook_all()
        except: pass
        console.clear()
        logger.info("Dashboard: Cleaned up and returned to main menu.")

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
