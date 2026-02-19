import sys
import warnings
# Suppress specific deprecation warnings from third-party libraries (e.g. yfinance/pandas)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="yfinance")

from db import init_db, get_manual_trades, delete_trade, add_trade, set_position_risk
from ibkr import download_trade_report, process_local_csvs, fetch_trade_history, fetch_open_positions
from dashboard import print_nav_table, print_rich_portfolio, run_live_dashboard, calculate_dashboard_data
from portfolio_manager import PortfolioManager
from risk_engine import calculate_atr_metrics
import sync_config
import pandas as pd
from datetime import datetime
from dateutil.parser import parse

def show_menu():
    print("\n--- PRIVATE EQUITY DASHBOARD ---")
    print("1. Fetch Trades from IBKR")
    print("2. Fetch Open Positions from IBKR")
    print("3. Fetch NAV Balance from IBKR")
    print("4. Incorporate CSVs into Database")
    print("5. Manage Manual Trades")
    print("6. Calculate Position ATR")
    print("7. Assign Risk/ATR to Position")
    print("8. View Portfolio Dashboard")
    print("9. Sync Config to OneDrive (Backup)")
    print("0. Exit")

def handle_fetch_trades():
    print("\n--- FETCH TRADES ---")
    print("1. Fetch Current Year (YTD)")
    print("2. Fetch Specific Year (Full Year)")
    choice = input("Choice: ").strip()
    
    if choice == '1':
        fetch_trade_history() 
    elif choice == '2':
        year_input = input("Enter Year (e.g. 2025): ").strip()
        year = int(year_input) if year_input else datetime.now().year - 1
        download_trade_report(year=year, is_ytd=False)
    else:
        print("Invalid choice.")

def handle_fetch_open_positions():
    print("\n--- FETCH OPEN POSITIONS ---")
    fetch_open_positions()

def handle_fetch_nav():
    print("\n--- FETCH NAV ---")
    manager = PortfolioManager()
    print_nav_table(manager, force_download=True)

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
    print("1. ATR for an EXISTING Position (Auto-fetch Date/Price)")
    print("2. ATR for a NEW Position (Manual Input)")
    choice = input("Choice: ").strip()

    manager = PortfolioManager()
    if choice == '1':
        ticker_input = input("Enter Ticker: ").strip().upper()
        if not ticker_input: return
        
        open_positions = manager.get_open_positions_hybrid()
        
        # Find matching ticker
        pos = next((p for p in open_positions if p['Ticker'].upper() == ticker_input), None)
        
        if pos:
            ticker = pos['Ticker']
            date_val = pos['Date']
            price = pos['Entry']
            print(f"-> Found existing position: {ticker} (Entry: {price:,.2f}, Date: {date_val})")
        else:
            print(f"Error: Ticker {ticker_input} not found in open positions.")
            return
    elif choice == '2':
        print("\nEnter details as: Ticker, Date, Price")
        print("Example: AAPL, 24 jun 2025, 180.5")
        line = input("Input: ").strip()
        if not line: return
        try:
            ticker, date_val, price, _ = parse_input_line(line)
        except Exception as e:
            print(f"Error: {e}")
            return
    else:
        print("Invalid choice.")
        return

    from rich.console import Console
    console = Console()
    with console.status("[bold green]Calculating ATR metrics..."):
        table = calculate_atr_metrics(ticker, date_val, price)
        console.print(table)

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
    choice = input("Choice (default 1): ").strip()
    if choice == '2': return "MarketValue"
    elif choice == '3': return "Pct"
    return "Ticker"

def main():
    init_db()
    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        
        if choice == '1': handle_fetch_trades()
        elif choice == '2': handle_fetch_open_positions()
        elif choice == '3': handle_fetch_nav()
        elif choice == '4': process_local_csvs()
        elif choice == '5': handle_manual_trades()
        elif choice == '6': handle_atr_calculator()
        elif choice == '7': handle_assign_risk()
        elif choice == '8':
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
                # Static view is now also interactive but without auto-refresh
                run_live_dashboard(manager, asset_class_filter=filter_val, sort_by=sort_val, use_ledger=use_ledger, refresh_interval=None)
        elif choice == '9':
            sync_config.backup()
        elif choice == '0':
            print("Exiting...")
            sys.exit()
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()