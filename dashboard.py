# dashboard.py
import os
import time
import sys
import pandas as pd
from manager import get_portfolio_df

# --- CONFIGURATION ---
REFRESH_SECONDS = 60
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_BOLD = "\033[1m"

# Column Config: (Display Name, DataFrame Column, Width, Format Specifier)
COLUMNS = [
    ("TICKER", "ticker", 8, "<"),       # Left align
    ("QTY", "total_qty", 8, ">.2f"),    # Right align, 2 decimals
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
    df = get_portfolio_df()
    
    if df.empty:
        print("\n📭 Portfolio is empty.")
        return False

    # 1. SORTING
    if sort_col in df.columns:
        df = df.sort_values(by=sort_col, ascending=ascending)

    # 2. HEADER
    header_parts = []
    for name, _, width, fmt_spec in COLUMNS:
        # FIX: Extract only the alignment character (<, >, ^) for the header string.
        # We ignore the ".2f" part because you can't format a Header String as a float.
        align = fmt_spec[0] if fmt_spec and fmt_spec[0] in "<>^" else "<"
        
        s = f"{name:{align}{width}}"
        header_parts.append(s)
    
    print(f"\n{COLOR_BOLD}" + " | ".join(header_parts) + f"{COLOR_RESET}")
    print("-" * (sum(c[2] for c in COLUMNS) + 3 * (len(COLUMNS) - 1)))

    # 3. ROWS
    for _, row in df.iterrows():
        row_parts = []
        for _, col_key, width, fmt_spec in COLUMNS:
            val = row.get(col_key)
            
            # Formatting Logic
            if isinstance(val, (int, float)):
                # If it's a number, use the full format (e.g. >.2f)
                val_str = f"{val:{fmt_spec}}"
            else:
                # If it's a string/null, fall back to simple string alignment
                align = fmt_spec[0] if fmt_spec and fmt_spec[0] in "<>^" else "<"
                val_str = f"{str(val):{align}{width}}"

            # Apply Color to P/L columns
            if col_key in ["unrealized_pl", "pl_pct"] and isinstance(val, (int, float)):
                if val > 0:
                    val_str = f"{COLOR_GREEN}{val_str}{COLOR_RESET}"
                elif val < 0:
                    val_str = f"{COLOR_RED}{val_str}{COLOR_RESET}"
            
            row_parts.append(val_str)
        
        print(" | ".join(row_parts))

    # 4. TOTALS
    print("-" * (sum(c[2] for c in COLUMNS) + 3 * (len(COLUMNS) - 1)))
    
    # Calculate totals safely
    total_pl = df['unrealized_pl'].sum() if 'unrealized_pl' in df else 0.0
    total_val = df['market_value'].sum() if 'market_value' in df else 0.0
    
    # Calc total cost basis to get accurate Total %
    total_cost = 0.0
    if 'total_qty' in df and 'avg_entry' in df:
        total_cost = (df['total_qty'] * df['avg_entry']).sum()
        
    total_pct = (total_pl / total_cost * 100) if total_cost else 0.0

    pl_color = COLOR_GREEN if total_pl >= 0 else COLOR_RED
    
    print(f"{COLOR_BOLD}TOTAL PORTFOLIO VALUE: ${total_val:,.2f}{COLOR_RESET}")
    print(f"Total Unrealized P/L:  {pl_color}${total_pl:,.2f} ({total_pct:.2f}%){COLOR_RESET}")
    return True

def dashboard_loop():
    """Main interactive loop for the dashboard."""
    sort_col = "ticker"
    ascending = True
    
    # Map friendly keys to DF columns
    sort_map = {
        "t": "ticker", "q": "total_qty", "e": "avg_entry", 
        "p": "current_price", "v": "market_value", "pl": "unrealized_pl", "%": "pl_pct"
    }

    while True:
        try:
            clear_screen()
            print(f"=== LIVE DASHBOARD (Sort: {sort_col.upper()}, Refresh: {REFRESH_SECONDS}s) ===")
            print("Commands: [r]efresh, [s]ort, [q]uit")
            
            has_data = print_dashboard(sort_col, ascending)

            if not has_data:
                input("\nPress Enter to return to menu...")
                break

            print(f"\nWaiting {REFRESH_SECONDS}s... (Press Ctrl+C to stop)")
            
            # Simple input strategy
            cmd = input("> ").strip().lower()

            if cmd == 'q':
                break
            elif cmd == 'r' or cmd == '':
                continue
            elif cmd == 's':
                print("\nSort Keys: [t]icker, [q]ty, [e]ntry, [p]rice, [v]alue, [pl] $, [%] return")
                key = input("Sort by: ").strip().lower()
                if key in sort_map:
                    sort_col = sort_map[key]
                    ascending = not ascending if sort_map[key] == sort_col else True
            
        except KeyboardInterrupt:
            break