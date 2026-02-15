import sys
from pathlib import Path
from db import init_db
from ibkr import download_trade_report, process_local_csvs, fetch_trade_history
from dashboard import print_nav_table, print_rich_portfolio, run_live_dashboard, calculate_dashboard_data
from portfolio_manager import PortfolioManager
from config import DATA_DIR, IBKR_QUERY_ID_NAV, IBKR_NAV_XML

def show_menu():
    print("\n--- PRIVATE EQUITY DASHBOARD ---")
    print("1. Fetch Trades from IBKR")
    print("2. Fetch NAV Balance from IBKR")
    print("3. Incorporate CSVs into Database")
    print("4. View Portfolio Dashboard")
    print("0. Exit")

def handle_fetch_trades():
    print("\n--- FETCH TRADES ---")
    print("1. Fetch Current Year (YTD)")
    print("2. Fetch Specific Year (Full Year)")
    choice = input("Choice: ").strip()
    
    if choice == '1':
        fetch_trade_history() # Downloads into trades.csv
    elif choice == '2':
        year_input = input("Enter Year (e.g. 2025): ").strip()
        from datetime import datetime
        year = int(year_input) if year_input else datetime.now().year - 1
        download_trade_report(year=year, is_ytd=False)
    else:
        print("Invalid choice.")

def handle_fetch_nav():
    print("\n--- FETCH NAV ---")
    manager = PortfolioManager()
    # This force_download=True triggers the actual IBKR call
    print_nav_table(manager, force_download=True)

def ask_asset_class():
    print("\n--- SELECT INSTRUMENTS ---")
    print("1. ALL Assets")
    print("2. STOCKS (Common + ETFs)")
    print("3. OPTIONS")
    print("4. BONDS")
    print("5. TREASURIES")
    choice = input("Choice: ").strip()
    
    if choice == '2':
        return ['STK', 'ETF']
    elif choice == '3':
        return 'OPT'
    elif choice == '4':
        return 'BOND'
    elif choice == '5':
        return 'BILL' # IBKR often uses 'BILL' for treasuries
    return None # All

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
    # Initialize DB
    init_db()
    
    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        
        if choice == '1':
            handle_fetch_trades()

        elif choice == '2':
            handle_fetch_nav()

        elif choice == '3':
            process_local_csvs()

        elif choice == '4':
            filter_val = ask_asset_class()
            sort_val = ask_sort_by()
            
            print("\n1. Static View")
            print("2. Live View (30s refresh)")
            view_type = input("Choice: ").strip()
            
            manager = PortfolioManager()
            if view_type == '2':
                run_live_dashboard(manager, asset_class_filter=filter_val, sort_by=sort_val)
            else:
                df, real_nav, report_date = calculate_dashboard_data(manager, asset_class_filter=filter_val)
                print_rich_portfolio(df, total_nav_override=real_nav, report_date=report_date, sort_by=sort_val)

        elif choice == '0':
            print("Exiting...")
            sys.exit()
        
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()