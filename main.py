import sys
from pathlib import Path
from db import init_db, archive_database
from ibkr import import_trades_from_file, fetch_trade_history, sync_ibkr_trades
from dashboard import print_nav_table, print_rich_portfolio, run_live_dashboard, calculate_dashboard_data
from portfolio_manager import PortfolioManager
from config import DATA_DIR

def show_menu():
    print("\n--- PRIVATE EQUITY DASHBOARD ---")
    print("1. View Portfolio (Static)")
    print("2. View Portfolio (Stocks Only)")
    print("3. LIVE Portfolio (30s Refresh)")
    print("---------------------------")
    print("4. Sync & Manage Trades")
    print("5. Fetch NAV Balance")
    print("0. Exit")

def handle_trades_menu():
    """Menu for trade synchronization and management."""
    print("\n1. Download from IBKR (Legacy - 365 Days)")
    print("2. Import from local file (trades_manual.csv)")
    print("3. Incremental Sync from IBKR (Recommended)")
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
    
    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        
        if choice == '1':
            manager = PortfolioManager()
            df, real_nav = calculate_dashboard_data(manager)
            print_rich_portfolio(df, total_nav_override=real_nav)

        elif choice == '2':
            manager = PortfolioManager()
            df, real_nav = calculate_dashboard_data(manager, asset_class_filter='STK')
            print_rich_portfolio(df, total_nav_override=real_nav)

        elif choice == '3':
            manager = PortfolioManager()
            run_live_dashboard(manager)

        elif choice == '4':
            handle_trades_menu()
    
        elif choice == '5':
            print("\n--- Fetching Balances ---")
            manager = PortfolioManager()
            print_nav_table(manager)

        elif choice == '0':
            print("Exiting...")
            sys.exit()
        
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()