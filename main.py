import sys
from pathlib import Path
from db import init_db, archive_database
from ibkr import import_trades_from_file, fetch_trade_history
from dashboard import print_nav_table, print_rich_portfolio
from portfolio_manager import PortfolioManager
from config import DATA_DIR

def show_menu():
    print("\n--- PRIVATE EQUITY DASHBOARD ---")
    print("1. View Portfolio (All Assets)")
    print("2. View Portfolio (Stocks Only)")
    print("---------------------------")
    print("7. Fetch/Import Trades (DB Legacy)")
    print("9. Fetch NAV Balance")
    print("0. Exit")

def handle_trades_menu():
    """Legacy menu for database operations if you still need them."""
    print("\n1. Download from IBKR (Last 365 Days)")
    print("2. Import from local file (trades_manual.xml)")
    choice = input("Choice: ").strip()
    
    if choice == '1':
        fetch_trade_history(365)
    elif choice == '2':
        import_trades_from_file('trades_manual.xml')

def main():
    # Initialize DB (Optional, if you still use it for history)
    init_db()
    
    # Path to your CSV
    csv_path = DATA_DIR / 'trades_manual.csv'

    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        
        if choice == '1':
            # 1. Initialize
            manager = PortfolioManager(csv_path)
            
            # 2. Fetch NAV (for correct Header AUM)
            # We don't force download here to be fast; use Option 9 to force refresh
            nav_data = manager.fetch_nav_data(force_download=False)
            real_nav = nav_data[0] if nav_data else None
            
            # 3. Get Data & Print
            df = manager.get_dashboard()
            print_rich_portfolio(df, total_nav_override=real_nav)

        elif choice == '2':
            manager = PortfolioManager(csv_path)
            
            # Filter for STK only
            nav_data = manager.fetch_nav_data(force_download=False)
            real_nav = nav_data[0] if nav_data else None
            
            df = manager.get_dashboard(asset_class_filter='STK')
            print_rich_portfolio(df, total_nav_override=real_nav)

        elif choice == '7':
            handle_trades_menu()

        elif choice == '9':
            print("\n--- Fetching Balances ---")
            manager = PortfolioManager(csv_path)
            print_nav_table(manager)

        elif choice == '10':
            archive_database()
            
        elif choice == '0':
            print("Exiting...")
            sys.exit()
        
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()