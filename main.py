# main.py
import sys
from datetime import datetime
from db import init_db, add_trade, archive_database
from manager import get_atr_gauge, parse_input_string
from dashboard import dashboard_loop
from ibkr import fetch_opening_balance, fetch_ytd_trades, fetch_latest_prices # <--- Added

# --- CONSTANTS ---
TRADE_PROMPT = """
Enter trade details as: Ticker, Date, Price, Quantity
Examples:
  AAPL, 21 Jun 2025, 210, 10
  TSLA, 2025-06-24, 180.50, 3
"""

EXPIRY_PROMPT = """
Enter expiry details as: Ticker, Date, Quantity
(Price will be recorded as 0)
Example:
  AAPL250621C, 2025-06-21, 5
"""

def show_menu():
    print("\n--- SIMPLE TRADING JOURNAL ---")
    print("1. Add Buy")
    print("2. Add Sell")
    print("3. Record Expiry (Options)")
    print("4. Check Risk/ATR")
    print("5. View Portfolio (Dashboard)")
    print("6. Fetch Opening Balances (Snapshot)")
    print("7. Fetch Trades (Date Range)")
    print("8. Fetch Latest Prices (IBKR Snapshot)")
    print("9. ARCHIVE & START NEW YEAR")
    print("0. Exit")
    return input("Choice: ").strip()

def input_trade(side):
    print(TRADE_PROMPT)
    raw = input("Input: ").strip()
    try:
        data = parse_input_string(raw)
        if data['quantity'] <= 0:
            print("❌ Quantity must be > 0")
            return
        cat = "OPT" if len(data['ticker']) > 6 and any(c.isdigit() for c in data['ticker']) else "STK"
        add_trade(
            date=data['date'], 
            ticker=data['ticker'], 
            side=side, 
            quantity=data['quantity'], 
            price=data['price'],
            asset_category=cat,
            source="MANUAL"
        )
    except Exception as e:
        print(f"❌ Error: {e}")

def input_expiry():
    print(EXPIRY_PROMPT)
    raw = input("Input: ").strip()
    try:
        parts = [x.strip() for x in raw.split(",")]
        if len(parts) < 3:
            print("❌ Input must be: Ticker, Date, Quantity")
            return
        ticker = parts[0].upper()
        date = parts[1]
        qty = float(parts[2])
        add_trade(
            date=date, 
            ticker=ticker, 
            side="EXP", 
            quantity=qty, 
            price=0.0, 
            asset_category="OPT",
            notes="Manual Expiry",
            source="MANUAL"
        )
    except Exception as e:
        print(f"❌ Error: {e}")

def check_risk():
    print("\n--- ATR Gauge ---")
    print("Enter entry details as: Ticker, Date, Price")
    raw = input("Input: ").strip()
    try:
        data = parse_input_string(raw)
        print(f"\nFetching data for {data['ticker']}...")
        atr_data, highest_high = get_atr_gauge(data['ticker'], data['price'], data['date'])
        
        print(f"\nATR gauge for {data['ticker']} (Entry {data['price']:.2f}, Max {highest_high:.2f}):")
        print(f"{'Label':<13} {'ATR':>8} {'Fixed SL':>10} {'Fixed %':>9} {'Trail SL':>10} {'Trail %':>9}")
        print("-" * 75)
        for label, val in atr_data.items():
            atr = val['atr']
            if atr:
                print(f"{label:<13} {atr:>8.2f} {val['fsl']:>10.2f} {val['fpct']:>8.2f}% {val['tsl']:>10.2f} {val['tpct']:>8.2f}%")
            else:
                print(f"{label:<13} {'-':>8} {'-':>10} {'-':>9} {'-':>10} {'-':>9}")
        print("-" * 75)
    except Exception as e:
        print(f"❌ Error: {e}")

def view_portfolio_dashboard():
    dashboard_loop()

def handle_opening_balance():
    print("\n--- Fetch Opening Balance ---")
    print("This will import positions from IBKR Query 1.")
    last_year = datetime.now().year - 1
    default_date = f"{last_year}-12-31"
    date_input = input(f"Enter Balance Date (YYYY-MM-DD) [Default: {default_date}]: ").strip()
    target_date = date_input if date_input else default_date
    fetch_opening_balance(target_date)

def handle_ytd_trades():
    print("\n--- Fetch Trade History ---")
    print("This will import trades from IBKR Query 2.")
    this_year = datetime.now().year
    default_start = f"{this_year}-01-01"
    start_input = input(f"Start Date (YYYY-MM-DD) [Default: {default_start}]: ").strip()
    start_date = start_input if start_input else default_start
    end_input = input(f"End Date (YYYY-MM-DD) [Default: Today]: ").strip()
    fetch_ytd_trades(start_date, end_input)

def handle_latest_prices():
    print("\n--- Fetch Latest Prices ---")
    print("This runs the 'Open Positions' query to get a Pricing Snapshot.")
    print("It will NOT import new trades.")
    fetch_latest_prices()

def handle_reset():
    print("\n⚠️  WARNING: This will ARCHIVE the current database and start fresh.")
    print("You should do this at the start of a new year.")
    confirm = input("Type 'ARCHIVE' to confirm: ").strip()
    if confirm == "ARCHIVE":
        archive_database()
    else:
        print("Cancelled.")

if __name__ == "__main__":
    init_db()
    while True:
        choice = show_menu()
        if choice == '1': input_trade("BUY")
        elif choice == '2': input_trade("SELL")
        elif choice == '3': input_expiry()
        elif choice == '4': check_risk()
        elif choice == '5': view_portfolio_dashboard()
        elif choice == '6': handle_opening_balance()
        elif choice == '7': handle_ytd_trades()
        elif choice == '8': handle_latest_prices()
        elif choice == '9': handle_reset()
        elif choice == '0': 
            print("Goodbye.")
            sys.exit()