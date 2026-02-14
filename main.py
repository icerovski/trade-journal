import sys
from pathlib import Path
from db import init_db, archive_database
from ibkr import import_trades_from_file, fetch_trade_history, sync_ibkr_trades
from dashboard import print_nav_table, print_rich_portfolio
from portfolio_manager import PortfolioManager
from config import DATA_DIR

def show_menu():
    print("\n--- PRIVATE EQUITY DASHBOARD ---")
    print("1. View Portfolio (All Assets)")
    print("2. View Portfolio (Stocks Only)")
    print("---------------------------")
    print("3. Fetch/Import Trades (DB Legacy)")
    print("4. Fetch NAV Balance")
    print("0. Exit")

def handle_trades_menu():
    """Legacy menu for database operations."""
    print("\n1. Download from IBKR (Last 365 Days)")
    print("2. Import from local file (trades_manual.csv)")
    print("3. Incremental Sync from IBKR (YTD + Prev FY)")
    choice = input("Choice: ").strip()
    
    if choice == '1':
        fetch_trade_history(365)
    elif choice == '2':
        import_trades_from_file('trades_manual.csv')
    elif choice == '3':
        sync_ibkr_trades()

def main():
    # Initialize DB (Optional)
    init_db()
    
    # Path to your CSV
    csv_path = DATA_DIR / 'trades_manual.csv'

    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        
        if choice == '1':
            manager = PortfolioManager(csv_path)
            
            # 1. Fetch NAV
            nav_data = manager.fetch_nav_data(force_download=False)
            real_nav = nav_data[0] if nav_data else None
            
            # 2. Get Data (Passing NAV for % calc)
            df = manager.get_dashboard(total_nav=real_nav)
            print_rich_portfolio(df, total_nav_override=real_nav)

        elif choice == '2':
            manager = PortfolioManager(csv_path)
            
            nav_data = manager.fetch_nav_data(force_download=False)
            real_nav = nav_data[0] if nav_data else None
            
            # Filter for STK only
            df = manager.get_dashboard(asset_class_filter='STK', total_nav=real_nav)
            print_rich_portfolio(df, total_nav_override=real_nav)

        elif choice == '3':
            handle_trades_menu()
    
        elif choice == '4':
            print("\n--- Fetching Balances ---")
            manager = PortfolioManager(csv_path)
            print_nav_table(manager)

        elif choice == '0':
            print("Exiting...")
            sys.exit()
        
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()