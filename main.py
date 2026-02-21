import sys
import warnings
# Suppress specific deprecation warnings from third-party libraries (e.g. yfinance/pandas)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="yfinance")

from db import init_db, get_manual_trades, delete_trade, add_trade, set_position_risk
from services.ibkr import download_trade_report, process_local_csvs, process_ytd_only, fetch_trade_history, fetch_open_positions
from dashboard import print_nav_table, print_rich_portfolio, run_live_dashboard, calculate_dashboard_data
from core.portfolio_manager import PortfolioManager
from core.risk_engine import calculate_atr_metrics
import sync_config
import pandas as pd
import os
from datetime import datetime
from dateutil.parser import parse
from config import DB_PATH

def show_menu():
    print("\n--- PRIVATE EQUITY DASHBOARD ---")
    print("1. Fetch Recent Data (Trades, Positions, NAV)")
    print("2. Update Database (YTD Only) - Fast update using current year CSVs")
    print("-" * 32)
    print("3. Rebuild Database (Full)   - Wipe and re-import all historical CSVs")
    print("-" * 32)
    print("4. Manage Manual Trades")
    print("5. Calculate Position ATR")
    print("6. Assign Risk/ATR to Position")
    print("7. View Portfolio Dashboard")
    print("8. Sync Historical Prices (Local DB)")
    print("0. Exit")

def handle_sync_prices():
    print("\n--- SYNC HISTORICAL PRICES ---")
    print("This will fetch missing history for all open positions and store it in your OneDrive DB.")
    manager = PortfolioManager()
    open_positions = manager.get_open_positions_hybrid()
    
    if not open_positions:
        print("No open positions found to sync.")
        return

    from services.price_service import PriceService
    from rich.progress import Progress
    from rich.console import Console
    
    ps = PriceService()
    console = Console()
    
    with Progress() as progress:
        task = progress.add_task("[cyan]Syncing prices...", total=len(open_positions))
        
        for pos in open_positions:
            try:
                yf_ticker = manager.mapper.resolve_yf_ticker(pos.ticker)
                ps.fetch_and_store(pos.conid, yf_ticker)
                progress.update(task, advance=1, description=f"[cyan]Synced {pos.ticker}")
            except Exception as e:
                console.print(f"[red]Error syncing {pos.ticker}: {e}[/red]")
                progress.update(task, advance=1)

    print("\nSync complete.")

def handle_fetch_recent_data():
    print("\n--- FETCH RECENT DATA ---")
    print("1. Standard Daily Sync (YTD Trades, Positions, NAV)")
    print("2. Fetch Specific Year (Historical Trades Only)")
    choice = input("Choice: ").strip()

    if choice == '1':
        print("\n-> Fetching Trades (YTD)...")
        fetch_trade_history()
        print("-> Fetching Open Positions snapshot...")
        fetch_open_positions()
        print("-> Fetching NAV Balance...")
        handle_fetch_nav()
    elif choice == '2':
        year_input = input("Enter Year (e.g. 2024): ").strip()
        year = int(year_input) if year_input else datetime.now().year - 1
        download_trade_report(year=year, is_ytd=False)
    else:
        print("Invalid choice.")

def handle_fetch_nav():
    manager = PortfolioManager()
    print_nav_table(manager, force_download=True)

def handle_update_db():
    print("\nUpdating database using YTD files...")
    process_ytd_only()

def handle_rebuild_db():
    print("\nWARNING: This will wipe the current database and re-import all history.")
    confirm = input("Are you absolutely sure? (y/N): ").strip().lower()
    if confirm == 'y':
        if DB_PATH.exists():
            os.remove(DB_PATH)
            print(f"Deleted {DB_PATH.name}")
        init_db()
        print("Database structure re-initialized.")
        process_local_csvs()
        print("Full rebuild complete.")
    else:
        print("Aborted.")

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
        print("\n--- MANAGE MANUAL TRADES ---")
        trades = get_manual_trades()
        if not trades:
            print("No manual trades found.")
        else:
            print(f"{'ID':<5} | {'Date':<12} | {'Ticker':<8} | {'Side':<6} | {'Qty':<8} | {'Price':<8}")
            print("-" * 60)
            for t in trades:
                print(f"{t['id']:<5} | {t['date']:<12} | {t['ticker']:<8} | {t['side']:<6} | {t['quantity']:<8,.0f} | {t['price']:<8,.2f}")
        
        print("\nOptions: [A]dd Trade, [D]elete ID, [B]ack")
        opt = input("Choice: ").strip().upper()
        
        if opt == 'A':
            print("\nFormat: Ticker, Date, Price, Side (buy/sell), Qty")
            print("Example: AAPL, 21 Feb 2026, 112.5, buy, 100")
            line = input("Entry: ").strip()
            if not line: continue
            
            try:
                ticker, date_val, price, extra = parse_input_line(line)
                if len(extra) < 2:
                    print("Error: Need Side and Qty for manual trades.")
                    continue
                side = extra[0].upper()
                qty = float(extra[1])
                
                add_trade(date=date_val, ticker=ticker, side=side, quantity=qty, price=price, source='MANUAL')
                print(f"SUCCESS: Added {side} {qty} {ticker} @ {price}")
            except Exception as e:
                print(f"Error parsing entry: {e}")
                
        elif opt == 'D':
            tid = input("Enter ID to delete: ").strip()
            if tid:
                delete_trade(tid)
                print(f"Deleted trade {tid}")
        elif opt == 'B':
            break

def handle_atr_calculator():
    print("\n--- ATR CALCULATOR ---")
    print("1. ATR for ALL EXISTING Stocks (Batch Mode)")
    print("2. ATR for a NEW Position (Manual Input)")
    choice = input("Choice: ").strip()

    manager = PortfolioManager()
    from db import get_all_risk_settings
    risk_settings = get_all_risk_settings()

    # Ask for optional multiplier/buffer
    multiplier_input = input("Noise Buffer Multiplier (e.g., 1.5, 2.0) [default 1.0]: ").strip()
    try:
        multiplier = float(multiplier_input) if multiplier_input else 1.0
    except ValueError:
        print("Invalid multiplier. Using 1.0.")
        multiplier = 1.0

    if choice == '1':
        print("\n-> Fetching open stock positions...")
        open_positions = manager.get_open_positions_hybrid(asset_class_filter='STK')
        
        if not open_positions:
            print("No open stock positions found.")
            return

        # Sort alphabetically by ticker
        open_positions.sort(key=lambda x: x.ticker)

        from rich.console import Console
        console = Console()
        
        print(f"-> Found {len(open_positions)} stock positions. Calculating ATR metrics...")
        
        for pos in open_positions:
            ticker = pos.ticker
            conid = pos.conid
            date_val = pos.date_entry.strftime("%Y-%m-%d")
            price = pos.entry_price
            
            # Show current setting if exists (Now includes highest_sl)
            current = risk_settings.get(ticker)
            if current:
                atr_val, stop_type, h_sl = current
                current_str = f"Current: {atr_val:.2f} ({stop_type}) | High-Water SL: {h_sl:,.2f}"
            else:
                current_str = "Current: NOT SET"
                
            console.print(f"\n[bold yellow]--- {ticker} ---[/bold yellow] (Entry: {date_val})")
            console.print(f"[dim]{current_str}[/dim]")

            with console.status(f"[bold green]Calculating ATR for {ticker}..."):
                table, raw_atrs = calculate_atr_metrics(ticker, date_val, price, multiplier=multiplier, conid=conid)
                console.print(table)
            
            # Interactive Choice
            if raw_atrs:
                print(f"\nUpdate ATR for {ticker}?")
                print("Format: [Value] [f/t]  (e.g., '4.05 t' for 4.05 Trailing, '3.5 f' for 3.5 Fixed)")
                print("Options from table (just enter the number or type custom value):")
                options = list(raw_atrs.keys())
                for i, label in enumerate(options, 1):
                    print(f"{i}. {label}: {raw_atrs[label]:.2f}")
                print("Press [Enter] to SKIP / No Change")
                
                user_input = input("Entry: ").strip().lower()
                if not user_input:
                    print(f"Skipping {ticker}.")
                else:
                    try:
                        # Check if it's a simple index choice from the list
                        if user_input.isdigit() and 1 <= int(user_input) <= len(options):
                            idx = int(user_input) - 1
                            selected_val = raw_atrs[options[idx]]
                            # If they just gave a number, we still need stop type
                            stop_choice = input("Stop Type (f)ixed or (t)railing? [default t]: ").strip().lower()
                            stop_type = "FIXED" if stop_choice == 'f' else "TRAILING"
                            set_position_risk(ticker, selected_val, stop_type)
                            print(f"SUCCESS: {ticker} updated to {selected_val:.2f} ({stop_type})")
                        
                        # Check for 'Value [f/t]' format
                        else:
                            parts = user_input.split()
                            if len(parts) >= 2:
                                val = float(parts[0])
                                stop_char = parts[1]
                                stop_type = "FIXED" if stop_char == 'f' else "TRAILING"
                                set_position_risk(ticker, val, stop_type)
                                print(f"SUCCESS: {ticker} updated to {val:.2f} ({stop_type})")
                            elif len(parts) == 1:
                                # Just a value, ask for type
                                val = float(parts[0])
                                stop_choice = input("Stop Type (f)ixed or (t)railing? [default t]: ").strip().lower()
                                stop_type = "FIXED" if stop_choice == 'f' else "TRAILING"
                                set_position_risk(ticker, val, stop_type)
                                print(f"SUCCESS: {ticker} updated to {val:.2f} ({stop_type})")
                    except ValueError:
                        print("Invalid format. Use 'Value f' or 'Value t'. Skipping.")
            
            console.print("-" * 40)
                
        return 
    elif choice == '2':
        print("\nEnter details as: Ticker, Date, Price, [conid]")
        print("Example: AAPL, 24 jun 2025, 180.5, 265598")
        line = input("Input: ").strip()
        if not line: return
        try:
            parts = [p.strip() for p in line.split(',')]
            ticker = parts[0].upper()
            date_val = parse(parts[1]).strftime("%Y-%m-%d")
            price = float(parts[2])
            conid = parts[3] if len(parts) > 3 else None
            
            from rich.console import Console
            console = Console()
            with console.status("[bold green]Calculating ATR metrics..."):
                table, _ = calculate_atr_metrics(ticker, date_val, price, multiplier=multiplier, conid=conid)
                console.print(table)
        except Exception as e:
            print(f"Error: {e}")
            return
    else:
        print("Invalid choice.")
        return


def handle_assign_risk():
    print("\n--- ASSIGN RISK/ATR TO POSITION ---")
    print("Format: Ticker, ATR Value, Stop Type (Fixed/Trailing)")
    print("Example: AAPL, 4.07, Trailing")
    line = input("Input: ").strip()
    if not line: return

    parts = [p.strip() for p in line.split(',')]
    if len(parts) < 3:
        print("Error: Need Ticker, ATR, and Type.")
        return

    try:
        ticker = parts[0].upper()
        atr = float(parts[1])
        stop_type = parts[2].upper()
        if stop_type not in ['FIXED', 'TRAILING']:
            print("Error: Type must be FIXED or TRAILING.")
            return
        
        set_position_risk(ticker, atr, stop_type)
        print(f"SUCCESS: Assigned {atr} {stop_type} stop to {ticker}")
    except Exception as e:
        print(f"Error: {e}")

def ask_asset_class():
    print("\n--- SELECT INSTRUMENTS ---")
    print("1. ALL Assets")
    print("2. STOCKS")
    print("3. OPTIONS")
    print("4. BONDS")
    print("5. TREASURIES")
    choice = input("Choice: ").strip()
    
    if choice == '2': return 'STK'
    elif choice == '3': return 'OPT'
    elif choice == '4': return 'BOND'
    elif choice == '5': return 'BILL' 
    return None 

def ask_sort_by():
    print("\n--- SORT BY ---")
    print("1. Ticker (A-Z)")
    print("2. Market Value (High-Low)")
    print("3. P/L % (High-Low)")
    print("4. P/L Absolute (High-Low)")
    print("5. Entry Date (Oldest First)")
    choice = input("Choice (default 1): ").strip()
    if choice == '2': return "MarketValue"
    elif choice == '3': return "Pct"
    elif choice == '4': return "PL"
    elif choice == '5': return "Date"
    return "Ticker"

def main():
    sync_config.smart_sync()
    init_db()
    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        
        if choice == '1': handle_fetch_recent_data()
        elif choice == '2': handle_update_db()
        elif choice == '3': handle_rebuild_db()
        elif choice == '4': handle_manual_trades()
        elif choice == '5': handle_atr_calculator()
        elif choice == '6': handle_assign_risk()
        elif choice == '7':
            filter_val = ask_asset_class()
            sort_val = ask_sort_by()
            print("\n--- CALCULATION METHOD ---")
            print("1. Hybrid (Verified by IBKR Snapshot)")
            print("2. Ledger (Pure Database Replay)")
            use_ledger = (input("Choice (default 1): ").strip() == '2')
            
            print("\n1. Static View (Interactive)")
            print("2. Live View (30s refresh)")
            view_type = input("Choice (default 1): ").strip()
            
            manager = PortfolioManager()
            if view_type == '2':
                run_live_dashboard(manager, asset_class_filter=filter_val, sort_by=sort_val, use_ledger=use_ledger, refresh_interval=30)
            else:
                run_live_dashboard(manager, asset_class_filter=filter_val, sort_by=sort_val, use_ledger=use_ledger, refresh_interval=None)
        elif choice == '8': handle_sync_prices()
        elif choice == '0':
            print("Exiting...")
            sys.exit()
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()
