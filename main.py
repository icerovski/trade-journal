import sys
from db import init_db, get_manual_trades, delete_trade, add_trade
from ibkr import download_trade_report, process_local_csvs, fetch_trade_history, fetch_open_positions
from dashboard import print_nav_table, print_rich_portfolio, run_live_dashboard, calculate_dashboard_data
from portfolio_manager import PortfolioManager
import pandas as pd
from datetime import datetime

def show_menu():
    print("\n--- PRIVATE EQUITY DASHBOARD ---")
    print("1. Fetch Trades from IBKR")
    print("2. Fetch Open Positions from IBKR")
    print("3. Fetch NAV Balance from IBKR")
    print("4. Incorporate CSVs into Database")
    print("5. Manage Manual Trades")
    print("6. View Portfolio Dashboard")
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
            print("\nFormat: Ticker, Side (buy/sell), Qty, Price, Date (optional)")
            print("Example: aapl, buy, 100, 112.5, 21 Feb 2026")
            line = input("Entry: ").strip()
            if not line: continue
            
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 4:
                print("Error: Invalid format. Need at least Ticker, Side, Qty, Price.")
                continue
            
            try:
                ticker = parts[0].upper()
                side = parts[1].upper()
                qty = float(parts[2])
                price = float(parts[3])
                
                # Date handling
                if len(parts) >= 5:
                    from dateutil.parser import parse
                    date_val = parse(parts[4]).strftime("%Y-%m-%d")
                else:
                    date_val = datetime.now().strftime("%Y-%m-%d")
                
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

def ask_asset_class():
    print("\n--- SELECT INSTRUMENTS ---")
    print("1. ALL Assets")
    print("2. STOCKS")
    print("3. OPTIONS")
    print("4. BONDS")
    print("5. TREASURIES")
    choice = input("Choice: ").strip()
    
    if choice == '2':
        return 'STK'
    elif choice == '3':
        return 'OPT'
    elif choice == '4':
        return 'BOND'
    elif choice == '5':
        return 'BILL' 
    return None 

def ask_sort_by():
    print("\n--- SORT BY ---")
    print("1. Ticker (A-Z)")
    print("2. Market Value (High-Low)")
    print("3. P/L % (High-Low)")
    choice = input("Choice (default 1): ").strip()
    
    if choice == '2':
        return "MarketValue"
    elif choice == '3':
        return "Pct"
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
        elif choice == '6':
            filter_val = ask_asset_class()
            sort_val = ask_sort_by()
            
            print("\n--- CALCULATION METHOD ---")
            print("1. Hybrid (Verified by IBKR Snapshot)")
            print("2. Ledger (Pure Database Replay)")
            method_choice = input("Choice (default 1): ").strip()
            use_ledger = (method_choice == '2')

            print("\n1. Static View\n2. Live View (30s refresh)")
            view_type = input("Choice: ").strip()
            
            manager = PortfolioManager()
            if view_type == '2':
                run_live_dashboard(manager, asset_class_filter=filter_val, sort_by=sort_val, use_ledger=use_ledger)
            else:
                df, real_nav, report_date = calculate_dashboard_data(manager, asset_class_filter=filter_val, use_ledger=use_ledger)
                print_rich_portfolio(df, total_nav_override=real_nav, report_date=report_date, sort_by=sort_val)
        elif choice == '0':
            print("Exiting...")
            sys.exit()
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()