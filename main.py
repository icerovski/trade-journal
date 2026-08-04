import sys
import warnings
from pathlib import Path
from db import init_db, wipe_trades_only, get_watch_list_profiles
from services.ibkr import (
    process_local_csvs, 
    process_all_local_history, 
    fetch_trade_history, 
    fetch_open_positions,
    fetch_trade_confirmations,
    process_confirmations
)
from ui.dashboard import print_nav_table, run_live_dashboard
from core.portfolio_manager import PortfolioManager
from logger import logger
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

    for p in prospects:
        table.add_row(
            str(p['ticker']),
            f"{p['atr_value']:.2f}",
            str(p['stop_type'])[:1],
        )
    
    console.print(table)

def print_open_items():
    """Surface unchecked items from docs/OPEN_ITEMS.md on startup. Tracked in git,
    so the reminder travels across machines (the .claude memory store does not)."""
    path = Path(__file__).parent / "docs" / "OPEN_ITEMS.md"
    if not path.exists():
        return
    items = [
        line.strip()[6:].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- [ ]")
    ]
    if not items:
        return

    body = Text()
    for item in items:
        body.append("  • ", style="bold yellow")
        body.append(f"{item}\n", style="white")
    body.append("\n  See docs/OPEN_ITEMS.md to tick off or edit.", style="dim")
    console.print(Panel(body, title=f"[bold yellow]OPEN ITEMS ({len(items)})[/bold yellow]",
                        border_style="yellow"))

def show_menu():
    from db import get_watch_list_profiles
    watch_count = len(get_watch_list_profiles())
    watch_label = f"WATCH LIST ({watch_count})" if watch_count > 0 else "WATCH LIST"

    menu_text = Text()
    menu_text.append("\n[1] ", style="bold green")
    menu_text.append("SYNC ALL         ", style="bold white")
    menu_text.append("(IBKR Fetch + Ledger Update + Price Sync)\n", style="dim")

    menu_text.append("[2] ", style="bold yellow")
    menu_text.append("RISK WORKSPACE   ", style="bold white")
    menu_text.append("(ATR Discovery, Risk Audit, Strategy Lab)\n", style="dim")

    menu_text.append("[3] ", style="bold cyan")
    menu_text.append("VIEW DASHBOARD   ", style="bold white")
    menu_text.append("(Performance & Risk Monitoring)\n", style="dim")
    
    menu_text.append("[4] ", style="bold yellow")
    menu_text.append("KIDS FUND        ", style="bold white")
    menu_text.append("(Private Wealth & Glide Path Audit)\n", style="dim")
    
    menu_text.append("[5] ", style="bold magenta")
    menu_text.append("MAINTENANCE      ", style="bold white")
    menu_text.append("(Surgical Rebuilds & System Tools)\n", style="dim")
    
    menu_text.append("[6] ", style="bold yellow")
    menu_text.append(f"{watch_label:<17}", style="bold white")
    menu_text.append("(Monitor & Manage Prospective Ideas)\n", style="dim")

    menu_text.append("[7] ", style="bold red")
    menu_text.append("PORTFOLIO RISK   ", style="bold white")
    menu_text.append("(Aggregate R%, Stop-Out Loss, Concentration, FX)\n", style="dim")

    menu_text.append("[8] ", style="bold cyan")
    menu_text.append("ZONE SCANNER     ", style="bold white")
    menu_text.append("(Entry/Exit Zones: Volume Profile + AVWAP + MA Confluence)\n", style="dim")

    menu_text.append("[9] ", style="bold green")
    menu_text.append("EXPECTANCY       ", style="bold white")
    menu_text.append("(Per-Archetype E[R], Source vs Benchmark, Base-CCY Return)\n", style="dim")

    menu_text.append("\n[0] EXIT", style="bold red")

    console.print(Panel(menu_text, title="[bold]TRADE JOURNAL & RISK MANAGEMENT[/bold]", subtitle="Institutional Portfolio System", border_style="blue"))

def _refresh_broker_snapshot(manager):
    """Downloads fresh broker data and ingests confirmations into the ledger."""
    fetch_open_positions()
    print_nav_table(manager, force_download=True)
    fetch_trade_confirmations()
    process_confirmations()


def handle_sync_all(manager):
    """Unified command for full system refresh."""
    console.print("\n[bold green]>>> Step 1: Syncing with Interactive Brokers...[/bold green]")
    fetch_trade_history()
    _refresh_broker_snapshot(manager)

    console.print("\n[bold green]>>> Step 2: Ingesting Full Trade History...[/bold green]")
    process_all_local_history()

    console.print("\n[bold green]>>> Step 3: Syncing Historical Prices (prices.db)...[/bold green]")
    handle_sync_prices(manager, silent=True)

    console.print("\n[bold green]SUCCESS: Full system sync complete.[/bold green]")

def handle_maintenance(manager):
    while True:
        console.print("\n[bold magenta]--- SYSTEM MAINTENANCE ---[/bold magenta]")
        print("1. Rebuild Trades (Surgical wipe, preserve risk profiles)")
        print("2. Sync Trade History (Fetch latest IBKR CSV)")
        print("3. Re-ingest ALL local CSVs (Full History Replay)")
        print("4. Sync Historical Prices (Manual)")
        print("5. Rebuild Price History (Re-download on one adjustment basis)")
        print("0. Back")

        choice = input("\nChoice: ").strip()
        if choice == '1':
            handle_rebuild_db()
        elif choice == '2':
            fetch_trade_history()
        elif choice == '3':
            process_local_csvs()
        elif choice == '4':
            handle_sync_prices(manager)
        elif choice == '5':
            handle_rebuild_prices(manager)
        elif choice == '0':
            break

def handle_sync_prices(manager, silent=False):
    if not silent:
        console.print("\n[bold cyan]--- SYNC HISTORICAL PRICES ---[/bold cyan]")

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

def handle_rebuild_prices(manager):
    """Re-download every cached price series from scratch.

    Ongoing syncs now detect a Yahoo re-basing (split/dividend) and heal that
    series automatically. This is the one-off cure for a seam already welded into
    the cache from before that guard existed — the symptom is an impossible
    one-day jump on a chart, or a trailing stop anchored to a high-water mark the
    position never traded at.
    """
    console.print("\n[bold cyan]--- REBUILD PRICE HISTORY ---[/bold cyan]")
    console.print("Re-downloads all cached price history so every bar sits on the CURRENT")
    console.print("split/dividend adjustment basis. Existing history is replaced, not merged.")
    console.print("[dim]Trades and risk profiles are untouched. Expect one request per position.[/dim]")
    if input("\nProceed? (y/N): ").strip().lower() != 'y':
        console.print("Aborted.")
        return

    open_positions = manager.get_open_positions_hybrid()
    if not open_positions:
        console.print("[yellow]No open positions found to rebuild.[/yellow]")
        return

    from services.price_service import PriceService
    from rich.progress import Progress

    ps = PriceService()
    rebuilt, failed = 0, []
    with Progress() as progress:
        task = progress.add_task("[cyan]Rebuilding...", total=len(open_positions))
        for pos in open_positions:
            try:
                yf_ticker = manager.mapper.resolve_yf_ticker(pos.ticker, conid=pos.conid)
                if ps.rebuild_series(pos.conid, yf_ticker) > 0:
                    rebuilt += 1
                else:
                    failed.append(pos.ticker)
            except Exception as e:
                logger.error(f"Price rebuild failed for {pos.ticker}: {e}")
                failed.append(pos.ticker)
            progress.update(task, advance=1, description=f"[cyan]Rebuilt {pos.ticker}")

    console.print(f"\n[bold green]Rebuilt {rebuilt} series.[/bold green]")
    if failed:
        # A failed rebuild leaves that series' existing history in place — say so,
        # rather than letting a silent skip read as success.
        console.print(f"[yellow]No data returned for {', '.join(failed)} — those caches were left as they were.[/yellow]")


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
    from ui.risk_workspace import run_risk_workspace
    run_risk_workspace()

def handle_view_dashboard(manager):
    """Direct-launch institutional dashboard."""
    console.print("\n[bold cyan]--- VIEW DASHBOARD ---[/bold cyan]")

    refresh_broker = input("Sync with IBKR (Fresh Snapshots + Intraday)? [y/N]: ").strip().lower()
    if refresh_broker in ['y', 'yes']:
        console.print("[bold green]>>> Syncing broker data...[/bold green]")
        _refresh_broker_snapshot(manager)

    console.print("[cyan]Launching Trading Cockpit...[/cyan]")
    run_live_dashboard(manager)

def handle_kids_fund():
    """Launch the Kids Fund Dashboard."""
    from ui.kids_fund_dashboard import run_kids_fund_dashboard
    run_kids_fund_dashboard()

def handle_watch_list():
    """Interactive management of the Watch List via Textual Workspace."""
    from ui.watch_list_workspace import run_watch_list_workspace
    run_watch_list_workspace()

def handle_portfolio_risk():
    """Portfolio-level risk aggregation report."""
    from ui.portfolio_risk import run_portfolio_risk
    run_portfolio_risk()

def handle_zone_scanner():
    """Launch the Entry/Exit Zone Scanner workspace."""
    from ui.zone_scan_workspace import run_zone_scan_workspace
    run_zone_scan_workspace()

def handle_expectancy():
    """Read-only expectancy report over the trade log."""
    from ui.expectancy_report import run_expectancy_report
    run_expectancy_report()

def main():
    sync_config.smart_sync()
    init_db()
    manager = PortfolioManager()

    print_open_items()

    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        if choice == '1':
            handle_sync_all(manager)
        elif choice == '2':
            handle_atr_calculator()
        elif choice == '3':
            handle_view_dashboard(manager)
        elif choice == '4':
            handle_kids_fund()
        elif choice == '5':
            handle_maintenance(manager)
        elif choice == '6':
            handle_watch_list()
        elif choice == '7':
            handle_portfolio_risk()
        elif choice == '8':
            handle_zone_scanner()
        elif choice == '9':
            handle_expectancy()
        elif choice == '0':
            sys.exit()
        else:
            console.print("[red]Invalid option.[/red]")

if __name__ == "__main__":
    main()
