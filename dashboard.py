# dashboard.py
import os
import time
import sys
import pandas as pd
from manager import get_portfolio_data

# --- CONFIGURATION ---
REFRESH_SECONDS = 60
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_BOLD = "\033[1m"

COLUMNS = [
    ("TICKER", "ticker", 8, "<"),
    ("QTY", "total_qty", 8, ">.2f"),
    ("ENTRY", "avg_entry", 10, ">.2f"),
    ("PRICE", "current_price", 10, ">.2f"),
    ("MKT VAL", "market_value", 12, ">,.2f"),
    ("P/L $", "unrealized_pl", 12, ">,.2f"),
    ("P/L %", "pl_pct", 9, ">.2f"),
]

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_dashboard(sort_col="ticker", ascending=True):
    """Fetches data, sorts it, and prints the full dashboard."""
    # Retrieve Filtered DF AND the True Total NAV
    df, total_nav = get_portfolio_data()
    
    if df.empty and total_nav == 0:
        print("\n📭 Portfolio is empty.")
        return False

    # 1. SORTING
    if not df.empty and sort_col in df.columns:
        df = df.sort_values(by=sort_col, ascending=ascending)

    # 2. HEADER
    visible_equity = df['market_value'].sum() if not df.empty else 0.0
    
    print(f"\n{COLOR_BOLD}=== PORTFOLIO SNAPSHOT ==={COLOR_RESET}")
    print(f"Total Account NAV:   ${total_nav:,.2f}  (All Assets & Cash)")
    print(f"Visible Stock Equity: ${visible_equity:,.2f}")
    print("-" * 50)

    if df.empty:
        print("(No active stock positions to display)")
        return True

    # 3. TABLE HEADERS
    header_parts = []
    for name, _, width, fmt_spec in COLUMNS:
        align = fmt_spec[0] if fmt_spec and fmt_spec[0] in "<>^" else "<"
        s = f"{name:{align}{width}}"
        header_parts.append(s)
    
    print(f"\n{COLOR_BOLD}" + " | ".join(header_parts) + f"{COLOR_RESET}")
    print("-" * (sum(c[2] for c in COLUMNS) + 3 * (len(COLUMNS) - 1)))

    # 4. ROWS
    for _, row in df.iterrows():
        row_parts = []
        for _, col_key, width, fmt_spec in COLUMNS:
            val = row.get(col_key)
            if isinstance(val, (int, float)):
                val_str = f"{val:{fmt_spec}}"
            else:
                align = fmt_spec[0] if fmt_spec and fmt_spec[0] in "<>^" else "<"
                val_str = f"{str(val):{align}{width}}"

            if col_key in ["unrealized_pl", "pl_pct"] and isinstance(val, (int, float)):
                if val > 0: val_str = f"{COLOR_GREEN}{val_str}{COLOR_RESET}"
                elif val < 0: val_str = f"{COLOR_RED}{val_str}{COLOR_RESET}"
            
            row_parts.append(val_str)
        print(" | ".join(row_parts))

    # 5. FOOTER (Visible Only)
    print("-" * (sum(c[2] for c in COLUMNS) + 3 * (len(COLUMNS) - 1)))
    
    total_pl = df['unrealized_pl'].sum()
    total_cost = (df['total_qty'] * df['avg_entry']).sum()
    total_pct = (total_pl / total_cost * 100) if total_cost else 0.0

    pl_color = COLOR_GREEN if total_pl >= 0 else COLOR_RED
    
    print(f"{COLOR_BOLD}Visible Unrealized P/L: {pl_color}${total_pl:,.2f} ({total_pct:.2f}%){COLOR_RESET}")
    return True

def dashboard_loop():
    sort_col = "ticker"
    ascending = True
    sort_map = {"t": "ticker", "q": "total_qty", "e": "avg_entry", "p": "current_price", "v": "market_value", "pl": "unrealized_pl", "%": "pl_pct"}

    while True:
        try:
            clear_screen()
            print_dashboard(sort_col, ascending)
            print(f"\n[R]efresh ({REFRESH_SECONDS}s) | [S]ort | [Q]uit")
            
            cmd = input("> ").strip().lower()

            if cmd == 'q': break
            elif cmd == 'r' or cmd == '': continue
            elif cmd == 's':
                key = input("Sort by (t/q/e/p/v/pl/%): ").strip().lower()
                if key in sort_map:
                    sort_col = sort_map[key]
                    ascending = not ascending if sort_map[key] == sort_col else True
        except KeyboardInterrupt:
            break