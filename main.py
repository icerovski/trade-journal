import sys
import warnings
# Suppress specific deprecation warnings from third-party libraries (e.g. yfinance/pandas)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="yfinance")

from db import init_db, get_manual_trades, delete_trade, add_trade, set_position_risk, wipe_trades_only
from services.ibkr import (
    process_local_csvs, 
    process_ytd_only, 
    fetch_trade_history, 
    fetch_open_positions,
    fetch_trade_confirmations,
    process_confirmations
)
from dashboard import print_nav_table, run_live_dashboard
from core.portfolio_manager import PortfolioManager
from core.risk_engine import calculate_atr_metrics
import sync_config
import pandas as pd
import os
from datetime import datetime
from dateutil.parser import parse
from config import DB_PATH
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

def show_menu():
    menu_text = Text()
    menu_text.append("\n[1] ", style="bold green")
    menu_text.append("SYNC ALL         ", style="bold white")
    menu_text.append("(IBKR Fetch + Ledger Update + Price Sync)\n", style="dim")
    
    menu_text.append("[2] ", style="bold yellow")
    menu_text.append("MANUAL ENTRIES   ", style="bold white")
    menu_text.append("(Risk Discovery, Risk Strategy, Manual Trades)\n", style="dim")
    
    menu_text.append("[3] ", style="bold cyan")
    menu_text.append("VIEW DASHBOARD   ", style="bold white")
    menu_text.append("(Performance & Risk Monitoring)\n", style="dim")
    
    menu_text.append("[4] ", style="bold magenta")
    menu_text.append("MAINTENANCE      ", style="bold white")
    menu_text.append("(Surgical Rebuilds & System Tools)\n", style="dim")
    
    menu_text.append("\n[0] EXIT", style="bold red")

    console.print(Panel(menu_text, title="[bold]TRADE JOURNAL & RISK MANAGEMENT[/bold]", subtitle="CEO Dashboard v2.0", border_style="blue"))

def handle_sync_all():
    """Unified command for full system refresh."""
    console.print("\n[bold green]>>> Step 1: Syncing with Interactive Brokers...[/bold green]")
    fetch_trade_history()
    fetch_open_positions()
    
    manager = PortfolioManager()
    print_nav_table(manager, force_download=True)
    
    console.print("\n[bold green]>>> Step 2: Ingesting Trades into trade_journal.db...[/bold green]")
    process_ytd_only()
    
    console.print("\n[bold green]>>> Step 3: Syncing Historical Prices (prices.db)...[/bold green]")
    handle_sync_prices(silent=True)
    
    console.print("\n[bold green]SUCCESS: Full system sync complete.[/bold green]")

def handle_manage_positions():
    while True:
        console.print("\n[bold yellow]--- MANAGE POSITIONS & RISK ---[/bold yellow]")
        print("1. ATR Discovery & Analysis (Calculator)")
        print("2. Quick Assign Strategy (Direct Entry)")
        print("3. Manual Trade Entries (Ledger)")
        print("0. Back")
        
        choice = input("\nChoice: ").strip()
        if choice == '1': handle_atr_calculator()
        elif choice == '2': handle_assign_risk()
        elif choice == '3': handle_manual_trades()
        elif choice == '0': break

def handle_maintenance():
    while True:
        console.print("\n[bold magenta]--- SYSTEM MAINTENANCE ---[/bold magenta]")
        print("1. Rebuild Trades (Surgical wipe, preserve risk profiles)")
        print("2. Sync Trade History (Fetch latest IBKR CSV)")
        print("3. Re-ingest ALL local CSVs (Full History Replay)")
        print("4. Sync Historical Prices (Manual)")
        print("0. Back")
        
        choice = input("\nChoice: ").strip()
        if choice == '1': handle_rebuild_db()
        elif choice == '2': fetch_trade_history()
        elif choice == '3': process_local_csvs()
        elif choice == '4': handle_sync_prices()
        elif choice == '0': break

def handle_sync_prices(silent=False):
    if not silent:
        console.print("\n[bold cyan]--- SYNC HISTORICAL PRICES ---[/bold cyan]")
    
    manager = PortfolioManager()
    open_positions = manager.get_open_positions_hybrid()
    
    if not open_positions:
        if not silent: console.print("[yellow]No open positions found to sync.[/yellow]")
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

    if not silent: console.print("\n[bold green]Price sync complete.[/bold green]")

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

def parse_input_line(line):
    """Common parser for Ticker, Date, Price line."""
    parts = [p.strip() for p in line.split(',')]
    if len(parts) < 3:
        raise ValueError("Need at least Ticker, Date, and Price.")
    
    ticker = parts[0].upper()
    date_val = parse(parts[1]).strftime("%Y-%m-%d")
    price = float(parts[2])
    
    # Optional 4th part could be Side or Qty depending on context
    remaining = parts[3:] if len(parts) > 3 else []
    return ticker, date_val, price, remaining

def handle_manual_trades():
    while True:
        console.print("\n[bold blue]--- MANAGE MANUAL ENTRIES ---[/bold blue]")
        trades = get_manual_trades()
        if not trades:
            print("No manual trades found.")
        else:
            print(f"{'ID':<5} | {'Date':<12} | {'Ticker':<8} | {'Side':<6} | {'Qty':<8} | {'Price':<8}")
            print("-" * 60)
            for t in trades:
                print(f"{t['id']:<5} | {t['date']:<12} | {t['ticker']:<8} | {t['side']:<6} | {t['quantity']:<8,.0f} | {t['price']:<8,.2f}")
        
        console.print("\nOptions: [bold]A[/bold]dd Entry, [bold]D[/bold]elete ID, [bold]B[/bold]ack")
        opt = input("Choice: ").strip().upper()
        
        if opt == 'A':
            print("\nFormat: Ticker, Date, Price, Side (buy/sell), Qty, [conid]")
            print("Example: AAPL, 21 Feb 2026, 112.5, buy, 100, 265598")
            line = input("Entry: ").strip()
            if not line: continue
            
            try:
                ticker, date_val, price, extra = parse_input_line(line)
                if len(extra) < 2:
                    console.print("[red]Error: Need Side and Qty.[/red]")
                    continue
                side, qty = extra[0].upper(), float(extra[1])
                conid = extra[2] if len(extra) > 2 else None
                
                add_trade(date=date_val, ticker=ticker, side=side, quantity=qty, price=price, source='MANUAL', conid=conid)
                console.print(f"[green]SUCCESS: Added {side} {qty} {ticker} @ {price}[/green]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                
        elif opt == 'D':
            tid = input("Enter ID to delete: ").strip()
            if tid: delete_trade(tid)
        elif opt == 'B': break

def handle_atr_calculator():
    """Launch the interactive Risk Assignment Workspace."""
    from risk_workspace import run_risk_workspace
    run_risk_workspace()

def handle_assign_risk():
    """Simple direct risk assignment."""
    console.print("\n[bold yellow]--- ASSIGN RISK STRATEGY ---[/bold yellow]")
    print("Format: Ticker, Conid, ATR, Type (Fixed/Trailing)")
    line = input("Input: ").strip()
    if not line: return
    try:
        parts = [p.strip() for p in line.split(',')]
        ticker, conid, atr, s_type = parts[0].upper(), parts[1], float(parts[2]), parts[3].upper()
        set_position_risk(conid, ticker, atr, s_type)
        console.print(f"[green]SUCCESS: {ticker} assigned {atr} {s_type}[/green]")
    except Exception as e: console.print(f"[red]Error: {e}[/red]")

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

def main():
    sync_config.smart_sync()
    init_db()
    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        if choice == '1': handle_sync_all()
        elif choice == '2': handle_manage_positions()
        elif choice == '3': handle_view_dashboard()
        elif choice == '4': handle_maintenance()
        elif choice == '0': sys.exit()
        else: console.print("[red]Invalid option.[/red]")

if __name__ == "__main__":
    main()
