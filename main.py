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
    print("2. LIVE Portfolio (30s Refresh)")
    print("---------------------------")
    print("3. Sync & Manage Trades")
    print("4. Fetch NAV Balance")
    print("0. Exit")

def ask_asset_class():
    print("\n--- SELECT INSTRUMENTS ---")
    print("1. ALL Assets")
    print("2. STOCKS (Common + ETFs)")
    print("3. OPTIONS")
    print("4. BONDS")
    choice = input("Choice: ").strip()
    
    if choice == '2':
        return ['STK', 'ETF']
    elif choice == '3':
        return 'OPT'
    elif choice == '4':
        return 'BOND'
    return None # All

def handle_trades_menu():
    """Menu for trade synchronization and management."""
    print("\n1. Download from IBKR (Legacy - 365 Days)")
    print("2. Import from local file (trades_manual.csv)")
    print("3. Full Sync from IBKR (Recommended)")
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
            filter_val = ask_asset_class()
            manager = PortfolioManager() # Loads from DB
            df, real_nav, report_date = calculate_dashboard_data(manager, asset_class_filter=filter_val)
            print_rich_portfolio(df, total_nav_override=real_nav, report_date=report_date)

        elif choice == '2':
            filter_val = ask_asset_class()
            manager = PortfolioManager()
            run_live_dashboard(manager, asset_class_filter=filter_val)

        elif choice == '3':
            handle_trades_menu()
    
        elif choice == '4':
            print("\n--- Fetching Balances (Local) ---")
            manager = PortfolioManager()
            print_nav_table(manager, force_download=False)

        elif choice == '0':
            print("Exiting...")
            sys.exit()
        
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()