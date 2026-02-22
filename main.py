import sys
import warnings
# Suppress specific deprecation warnings from third-party libraries (e.g. yfinance/pandas)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="yfinance")

from db import init_db, get_manual_trades, delete_trade, add_trade, set_position_risk, wipe_trades_only
from services.ibkr import (
    download_trade_report, 
    process_local_csvs, 
    process_ytd_only, 
    fetch_trade_history, 
    fetch_open_positions,
    fetch_trade_confirmations,
    process_confirmations
)
from dashboard import print_nav_table, print_rich_portfolio, run_live_dashboard, calculate_dashboard_data
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
        print("1. ATR Discovery (Calculator)")
        print("2. Assign Risk Strategy (ATR/Stops)")
        print("3. Manual Trade Entries")
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
        print("2. Fetch Historical Year (Download old IBKR CSVs)")
        print("3. Re-ingest ALL local CSVs (Full History Replay)")
        print("4. Sync Historical Prices (Manual)")
        print("0. Back")
        
        choice = input("\nChoice: ").strip()
        if choice == '1': handle_rebuild_db()
        elif choice == '2':
            year_input = input("Enter Year (e.g. 2024): ").strip()
            year = int(year_input) if year_input else datetime.now().year - 1
            download_trade_report(year=year, is_ytd=False)
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
                yf_ticker = manager.mapper.resolve_yf_ticker(pos.ticker)
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
    console.print("\n[bold yellow]--- ATR DISCOVERY ---[/bold yellow]")
    print("1. Batch Mode (Existing Stocks)")
    print("2. Manual Mode (New Position)")
    choice = input("Choice: ").strip()

    manager = PortfolioManager()
    from db import get_all_risk_settings
    risk_settings = get_all_risk_settings()

    multiplier_input = input("Noise Buffer (e.g. 1.5) [default 1.0]: ").strip()
    try: multiplier = float(multiplier_input) if multiplier_input else 1.0
    except ValueError: multiplier = 1.0

    if choice == '1':
        open_positions = manager.get_open_positions_hybrid(asset_class_filter='STK')
        if not open_positions: return
        open_positions.sort(key=lambda x: x.ticker)
        
        for pos in open_positions:
            ticker, conid = pos.ticker, pos.conid
            date_val, price = pos.date_entry.strftime("%Y-%m-%d"), pos.entry_price
            
            current = risk_settings.get(str(conid))
            current_str = f"Current: {current[0]:.2f} ({current[1]}) | High SL: {current[2]:,.2f}" if current else "Current: NOT SET"
                
            console.print(f"\n[bold yellow]--- {ticker} ---[/bold yellow] ({current_str})")
            with console.status(f"Calculating ATR for {ticker}..."):
                table, raw_atrs = calculate_atr_metrics(ticker, date_val, price, multiplier=multiplier, conid=conid)
                console.print(table)
            
            if raw_atrs:
                print(f"\nUpdate {ticker}? (e.g. '1' for selection, '4.05 t' for custom Trailing, or Enter to skip)")
                options = list(raw_atrs.keys())
                for i, label in enumerate(options, 1): print(f"{i}. {label}: {raw_atrs[label]:.2f}")
                
                user_input = input("Entry: ").strip().lower()
                if not user_input: continue
                try:
                    if user_input.isdigit() and 1 <= int(user_input) <= len(options):
                        idx = int(user_input) - 1
                        val = raw_atrs[options[idx]]
                        stop_choice = input("Type (f)ixed/(t)railing [t]: ").strip().lower()
                        set_position_risk(conid, ticker, val, "FIXED" if stop_choice == 'f' else "TRAILING", start_date=date_val)
                    else:
                        parts = user_input.split()
                        val = float(parts[0])
                        set_position_risk(conid, ticker, val, "FIXED" if (len(parts) > 1 and parts[1] == 'f') else "TRAILING", start_date=date_val)
                except Exception: console.print("[red]Invalid. Skipping.[/red]")
    elif choice == '2':
        print("\nEnter: Ticker, Date, Price, conid")
        line = input("Input: ").strip()
        if not line: return
        try:
            parts = [p.strip() for p in line.split(',')]
            ticker, date_val, price, conid = parts[0].upper(), parse(parts[1]).strftime("%Y-%m-%d"), float(parts[2]), parts[3]
            with console.status("Calculating..."):
                table, _ = calculate_atr_metrics(ticker, date_val, price, multiplier=multiplier, conid=conid)
                console.print(table)
        except Exception as e: console.print(f"[red]Error: {e}[/red]")

def handle_assign_risk():
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

def ask_asset_class():
    console.print("\n[bold cyan]--- SELECT INSTRUMENTS ---[/bold cyan]")
    print("1. ALL | 2. STOCKS | 3. OPTIONS | 4. BONDS | 5. TREASURIES")
    choice = input("Choice: ").strip()
    return {'2': 'STK', '3': 'OPT', '4': 'BOND', '5': 'BILL'}.get(choice)

def ask_sort_by():
    console.print("\n[bold cyan]--- SORT BY ---[/bold cyan]")
    print("1. Ticker | 2. MarketValue | 3. P/L % | 4. P/L Abs | 5. Date")
    return {'2': 'MarketValue', '3': 'Pct', '4': 'PL', '5': 'Date'}.get(input("Choice: ").strip(), 'Ticker')

def handle_view_dashboard():
    """Fast-path dashboard with optional real-time refresh."""
    console.print("\n[bold cyan]--- VIEW DASHBOARD ---[/bold cyan]")
    
    # 1. Real-Time Refresh Prompt
    refresh_broker = input("Refresh Latest Snapshot + Intraday Trades? [y/N]: ").strip().lower()
    if refresh_broker in ['y', 'yes']:
        console.print("[bold green]>>> Fetching Fresh Snapshots...[/bold green]")
        fetch_open_positions()
        
        manager = PortfolioManager()
        print_nav_table(manager, force_download=True)
        
        console.print("[bold green]>>> Fetching Intraday Confirmations...[/bold green]")
        fetch_trade_confirmations()
        process_confirmations()
        
    # 2. Layout & Calculation Defaults
    console.print("\nDefaults: [bold]STOCKS[/bold], [bold]Ticker[/bold], [bold]Hybrid[/bold], [bold]Static[/bold]")
    fast_path = input("Use these layout defaults? [Y/n]: ").strip().lower()
    
    if fast_path in ['', 'y', 'yes']:
        f, s, l, r = 'STK', 'Ticker', False, None
    else:
        f = ask_asset_class()
        s = ask_sort_by()
        l = (input("\nMethod: 1. Hybrid [default] | 2. Ledger: ").strip() == '2')
        r_choice = input("View: 1. Static [default] | 2. Live (30s): ").strip()
        r = 30 if r_choice == '2' else None
        
    run_live_dashboard(PortfolioManager(), asset_class_filter=f, sort_by=s, use_ledger=l, refresh_interval=r)

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
