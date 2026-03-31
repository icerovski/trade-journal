import sys
import warnings
from db import init_db, wipe_trades_only, get_watch_list_profiles
from services.ibkr import (
    process_local_csvs, 
    process_all_local_history, 
    fetch_trade_history, 
    fetch_open_positions,
    fetch_trade_confirmations,
    process_confirmations
)
from dashboard import print_nav_table, run_live_dashboard
from core.portfolio_manager import PortfolioManager
import sync_config
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Suppress specific deprecation warnings from third-party libraries (e.g. yfinance/pandas)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="yfinance")

console = Console()

def print_watch_list_summary():
    """Displays a concise summary of prospects on the Watch List."""
    prospects = get_watch_list_profiles()
    if not prospects:
        return

    from rich.table import Table
    from rich import box
    
    table = Table(box=box.SIMPLE_HEAD, title="[bold yellow]WATCH LIST PROSPECTS[/bold yellow]", title_justify="left")
    table.add_column("TICKER", style="cyan")
    table.add_column("ATR", justify="right")
    table.add_column("TYPE", justify="center")
    table.add_column("STRATEGY", justify="center")
    table.add_column("STEP", justify="right")

    for p in prospects:
        table.add_row(
            str(p['ticker']),
            f"{p['atr_value']:.2f}",
            str(p['stop_type'])[:1],
            "Pilot" if p['entry_type'] == 'SCALE_IN' else "Single",
            f"{p['scale_step']}x"
        )
    
    console.print(table)

def show_menu(nav_info=None):
    menu_text = Text()
    menu_text.append("\n[1] ", style="bold green")
    menu_text.append("SYNC ALL         ", style="bold white")
    menu_text.append("(IBKR Fetch + Ledger Update + Price Sync)\n", style="dim")
    
    nav_display = ""
    if nav_info:
        nav_val, nav_ccy, _, _ = nav_info
        nav_display = f" [bold cyan](AUM: {nav_val:,.0f} {nav_ccy})[/]"

    menu_text.append("[2] ", style="bold yellow")
    menu_text.append("RISK WORKSPACE   ", style="bold white")
    menu_text.append(f"(ATR Discovery, Risk Audit, Strategy Lab){nav_display}\n", style="dim")
    
    menu_text.append("[3] ", style="bold cyan")
    menu_text.append("VIEW DASHBOARD   ", style="bold white")
    menu_text.append(f"(Performance & Risk Monitoring){nav_display}\n", style="dim")
    
    menu_text.append("[4] ", style="bold yellow")
    menu_text.append("KIDS FUND        ", style="bold white")
    menu_text.append("(Private Wealth & Glide Path Audit)\n", style="dim")
    
    menu_text.append("[5] ", style="bold magenta")
    menu_text.append("MAINTENANCE      ", style="bold white")
    menu_text.append("(Surgical Rebuilds & System Tools)\n", style="dim")
    
    menu_text.append("[6] ", style="bold yellow")
    menu_text.append("WATCH LIST       ", style="bold white")
    menu_text.append("(Monitor & Manage Prospective Ideas)\n", style="dim")
    
    menu_text.append("\n[0] EXIT", style="bold red")

    console.print(Panel(menu_text, title="[bold]TRADE JOURNAL & RISK MANAGEMENT[/bold]", subtitle="CEO Dashboard v2.0", border_style="blue"))

def handle_sync_all():
    """Unified command for full system refresh."""
    console.print("\n[bold green]>>> Step 1: Syncing with Interactive Brokers...[/bold green]")
    fetch_trade_history()
    fetch_open_positions()
    fetch_trade_confirmations()
    
    manager = PortfolioManager()
    print_nav_table(manager, force_download=True)
    
    console.print("\n[bold green]>>> Step 2: Ingesting Trades into trade_journal.db...[/bold green]")
    process_all_local_history()
    process_confirmations()
    
    console.print("\n[bold green]>>> Step 3: Syncing Historical Prices (prices.db)...[/bold green]")
    handle_sync_prices(silent=True)
    
    console.print("\n[bold green]SUCCESS: Full system sync complete.[/bold green]")

def handle_maintenance():
    while True:
        console.print("\n[bold magenta]--- SYSTEM MAINTENANCE ---[/bold magenta]")
        print("1. Rebuild Trades (Surgical wipe, preserve risk profiles)")
        print("2. Sync Trade History (Fetch latest IBKR CSV)")
        print("3. Re-ingest ALL local CSVs (Full History Replay)")
        print("4. Sync Historical Prices (Manual)")
        print("0. Back")
        
        choice = input("\nChoice: ").strip()
        if choice == '1':
            handle_rebuild_db()
        elif choice == '2':
            fetch_trade_history()
        elif choice == '3':
            process_local_csvs()
        elif choice == '4':
            handle_sync_prices()
        elif choice == '0':
            break

def handle_sync_prices(silent=False):
    if not silent:
        console.print("\n[bold cyan]--- SYNC HISTORICAL PRICES ---[/bold cyan]")
    
    manager = PortfolioManager()
    open_positions = manager.get_open_positions_hybrid()
    
    if not open_positions:
        if not silent:
            console.print("[yellow]No open positions found to sync.[/yellow]")
        return

    from services.price_service import PriceService
    from rich.progress import Progress
    
    ps = PriceService()
    
    with Progress(disable=silent) as progress:
        task = progress.add_task("[cyan]Syncing prices...", total=len(open_positions))
        for pos in open_positions:
            try:
                yf_ticker = manager.mapper.resolve_yf_ticker(pos.ticker, conid=pos.conid)
                ps.fetch_and_store(pos.conid, yf_ticker)
                progress.update(task, advance=1, description=f"[cyan]Synced {pos.ticker}")
            except Exception:
                progress.update(task, advance=1)

    if not silent:
        console.print("\n[bold green]Price sync complete.[/bold green]")

def handle_rebuild_db():
    console.print("\n[bold red]WARNING: Surgical Rebuild initiated.[/bold red]")
    console.print("This will wipe only the trades history and re-import all CSVs.")
    console.print("YOUR RISK PROFILES AND ATR SETTINGS WILL BE PRESERVED.")
    confirm = input("Proceed? (y/N): ").strip().lower()
    if confirm == 'y':
        wipe_trades_only()
        console.print("Trades table wiped. Re-importing history...")
        process_local_csvs()
        console.print("[bold green]Full rebuild complete.[/bold green]")
    else:
        console.print("Aborted.")

def handle_atr_calculator():
    """Launch the interactive Risk Assignment Workspace."""
    from risk_workspace import run_risk_workspace
    run_risk_workspace()

def handle_view_dashboard():
    """Direct-launch institutional dashboard."""
    console.print("\n[bold cyan]--- VIEW DASHBOARD ---[/bold cyan]")
    
    # 1. Real-Time Refresh Prompt (Broker Sync)
    refresh_broker = input("Sync with IBKR (Fresh Snapshots + Intraday)? [y/N]: ").strip().lower()
    if refresh_broker in ['y', 'yes']:
        console.print("[bold green]>>> Syncing broker data...[/bold green]")
        fetch_open_positions()
        manager = PortfolioManager()
        print_nav_table(manager, force_download=True)
        fetch_trade_confirmations()
        process_confirmations()
        
    # 2. Direct Launch (No more prompts for Layout/Method/View)
    console.print("[cyan]Launching Trading Cockpit...[/cyan]")
    run_live_dashboard(PortfolioManager())

def handle_kids_fund():
    """Launch the Kids Fund Dashboard."""
    from kids_fund_dashboard import run_kids_fund_dashboard
    run_kids_fund_dashboard()

def handle_watch_list():
    """Interactive management of the Watch List via Textual Workspace."""
    from watch_list_workspace import run_watch_list_workspace
    run_watch_list_workspace()

def main():
    sync_config.smart_sync()
    init_db()
    manager = PortfolioManager()
    nav_info = manager.fetch_nav_data()
    
    while True:
        show_menu(nav_info)
        choice = input("\nSelect option: ").strip()
        if choice == '1':
            handle_sync_all()
            nav_info = manager.fetch_nav_data() # Refresh after sync
        elif choice == '2':
            handle_atr_calculator()
        elif choice == '3':
            handle_view_dashboard()
        elif choice == '4':
            handle_kids_fund()
        elif choice == '5':
            handle_maintenance()
        elif choice == '6':
            handle_watch_list()
        elif choice == '0':
            sys.exit()
        else:
            console.print("[red]Invalid option.[/red]")

if __name__ == "__main__":
    main()
