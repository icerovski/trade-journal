# main.py
import sys
from db import init_db, add_trade
from manager import get_portfolio_df, get_atr_gauge, parse_input_string
from ibkr_service import fetch_ibkr_xml, parse_and_import_xml

# --- CONSTANTS ---
TRADE_PROMPT = """
Enter trade details as: Ticker, Date, Price, Quantity
Examples:
  AAPL, 21 Jun 2025, 210, 10
  TSLA, 2025-06-24, 180.50, 3
"""

def show_menu():
    print("\n--- SIMPLE TRADING JOURNAL ---")
    print("1. Add Buy")
    print("2. Add Sell")
    print("3. Check Risk/ATR")
    print("4. View Portfolio")
    print("5. Fetch Data from IBKR (Download Only)")
    print("6. Update DB from XML (Import)")
    print("7. Exit")
    return input("Choice: ").strip()

def input_trade(side):
    print(TRADE_PROMPT)
    raw = input("Input: ").strip()
    try:
        data = parse_input_string(raw)
        if data['quantity'] <= 0:
            print("❌ Quantity must be > 0")
            return
        add_trade(data['date'], data['ticker'], side, data['quantity'], data['price'])
        print(f"✅ Trade recorded.")
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
                print(
                    f"{label:<13} "
                    f"{atr:>8.2f} "
                    f"{val['fsl']:>10.2f} "
                    f"{val['fpct']:>8.2f}% "
                    f"{val['tsl']:>10.2f} "
                    f"{val['tpct']:>8.2f}%"
                )
            else:
                print(f"{label:<13} {'-':>8} {'-':>10} {'-':>9} {'-':>10} {'-':>9}")
        print("-" * 75)
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

if __name__ == "__main__":
    init_db()
    while True:
        choice = show_menu()
        if choice == '1':
            input_trade("BUY")
        elif choice == '2':
            input_trade("SELL")
        elif choice == '3':
            check_risk()
        elif choice == '4':
            view_portfolio()
        elif choice == '5':
            # WORKFLOW A: Fetch, then ask to update
            success = fetch_ibkr_xml()
            if success:
                ask = input("\nDo you want to update the database from this file now? (y/n): ").lower().strip()
                if ask == 'y':
                    parse_and_import_xml()
        elif choice == '6':
            # WORKFLOW B: Update independently
            parse_and_import_xml()
        elif choice == '7':
            print("Goodbye.")
            sys.exit()