# main.py
import sys
from datetime import datetime
from db import init_db, add_trade
from manager import get_portfolio_df, get_atr_gauge

def show_menu():
    print("\n--- SIMPLE TRADING JOURNAL ---")
    print("1. Add Trade (Buy/Sell)")
    print("2. View Portfolio")
    print("3. Check Risk/ATR")
    print("4. Exit")
    return input("Select: ").strip()

def input_trade():
    print("\n--- New Trade ---")
    ticker = input("Ticker: ").strip().upper()
    side = input("Side (BUY/SELL): ").strip().upper()
    qty = input("Quantity: ").strip()
    price = input("Price: ").strip()
    date = input(f"Date (YYYY-MM-DD) [Enter for Today]: ").strip()
    
    if not date:
        date = datetime.today().strftime('%Y-%m-%d')
        
    try:
        add_trade(date, ticker, side, qty, price)
    except Exception as e:
        print(f"❌ Error: {e}")

def view_portfolio():
    print("\n--- Current Holdings ---")
    df = get_portfolio_df()
    if df.empty:
        print("No open positions.")
        return

    print(f"{'TICKER':<8} {'QTY':<8} {'ENTRY':<10} {'PRICE':<10} {'P/L $':<10} {'P/L %':<8}")
    print("-" * 60)
    
    for _, row in df.iterrows():
        print(f"{row['ticker']:<8} "
              f"{row['total_qty']:<8.2f} "
              f"{row['avg_entry']:<10.2f} "
              f"{row['current_price']:<10.2f} "
              f"{row['unrealized_pl']:<10.2f} "
              f"{row['pl_pct']:<8.2f}%")

def check_risk():
    print("\n=== ATR / Stop-loss Gauge ===")
    ticker = input("Ticker: ").strip().upper()
    
    # Optional Inputs
    price_str = input("Entry Price [Enter to skip]: ").strip()
    entry_price = float(price_str) if price_str else None
    
    date_str = input("Entry Date (YYYY-MM-DD) [Enter to skip]: ").strip()
    
    print(f"\nFetching data for {ticker}...")
    
    # Call the manager logic
    try:
        atr_data, highest_high = get_atr_gauge(ticker, entry_price, date_str)
        
        max_str = f"{highest_high:.2f}" if highest_high else "-"
        entry_str = f"{entry_price:.2f}" if entry_price else "N/A"

        print(f"\nATR gauge for {ticker} (Entry {entry_str}, Max Since Entry {max_str}):")
        print(f"{'Label':<15} {'ATR':<8} {'Fixed SL':<10} {'Fixed %':<10} {'Trail SL':<10} {'Trail %':<8}")
        print("-" * 75)

        for label, (atr, fsl, fpct, tsl, tpct) in atr_data.items():
            print(
                f"{label:<15} "
                f"{(f'{atr:.2f}'  if atr  else '-'):<8} "
                f"{(f'{fsl:.2f}' if fsl else '-'):<10} "
                f"{(f'{fpct:.2f}%' if fpct else '-'):<10} "
                f"{(f'{tsl:.2f}' if tsl else '-'):<10} "
                f"{(f'{tpct:.2f}%' if tpct else '-'):<8}"
            )
        print("-" * 75)
        
    except Exception as e:
        print(f"❌ Error calculating ATR: {e}")

if __name__ == "__main__":
    init_db()
    while True:
        choice = show_menu()
        if choice == '1':
            input_trade()
        elif choice == '2':
            view_portfolio()
        elif choice == '3':
            check_risk()
        elif choice == '4':
            print("Goodbye.")
            sys.exit()