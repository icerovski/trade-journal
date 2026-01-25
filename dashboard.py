# dashboard.py
import os
import sys
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from manager import get_portfolio_data

# --- CONFIGURATION ---
REFRESH_SECONDS = 60

# Initialize Rich Console
console = Console()

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_dashboard(sort_col="ticker", ascending=True):
    """Fetches data and renders a beautiful table using Rich."""
    
    # 1. Fetch Data
    df, total_nav = get_portfolio_data()
    
    if df.empty and total_nav == 0:
        console.print(Panel("📭 Portfolio is empty.", style="yellow"))
        return False

    # 2. Sort Data
    if not df.empty and sort_col in df.columns:
        df = df.sort_values(by=sort_col, ascending=ascending)

    # 3. HEADER (NAV Summary)
    visible_equity = df['market_value'].sum() if not df.empty else 0.0
    
    summary_text = (
        f"[bold]Total Account NAV:[/bold]   [green]${total_nav:,.2f}[/green]  (All Assets)\n"
        f"[bold]Visible Stock Equity:[/bold] [blue]${visible_equity:,.2f}[/blue]"
    )
    console.print(Panel(summary_text, title="PORTFOLIO SNAPSHOT", expand=False))

    if df.empty:
        console.print("[italic dim]No active stock positions to display[/italic dim]")
        return True

    # 4. BUILD THE TABLE
    table = Table(box=box.SIMPLE_HEAD) # Clean, modern look
    
    # Define Columns (Rich handles width automatically)
    table.add_column("TICKER", justify="left", style="bold cyan")
    table.add_column("QTY", justify="right")
    table.add_column("ENTRY", justify="right")
    table.add_column("PRICE", justify="right")
    table.add_column("MKT VAL", justify="right")
    table.add_column("P/L $", justify="right")
    table.add_column("P/L %", justify="right")

    # 5. ADD ROWS
    for _, row in df.iterrows():
        # Color Logic for P/L
        pl_val = row['unrealized_pl']
        pl_pct = row['pl_pct']
        
        pl_color = "green" if pl_val >= 0 else "red"
        
        # Format values
        ticker = str(row['ticker'])
        qty = f"{row['total_qty']:,.2f}"
        entry = f"{row['avg_entry']:,.2f}"
        price = f"{row['current_price']:,.2f}"
        mkt_val = f"{row['market_value']:,.2f}"
        
        # Apply color tags to the specific P/L cells
        pl_str = f"[{pl_color}]{pl_val:,.2f}[/{pl_color}]"
        pct_str = f"[{pl_color}]{pl_pct:,.2f}%[/{pl_color}]"
        
        table.add_row(ticker, qty, entry, price, mkt_val, pl_str, pct_str)

    # 6. TOTALS ROW (Footer)
    total_pl = df['unrealized_pl'].sum()
    total_cost = (df['total_qty'] * df['avg_entry']).sum()
    total_pct = (total_pl / total_cost * 100) if total_cost else 0.0
    tot_color = "green" if total_pl >= 0 else "red"

    table.add_section() # Adds a nice separator line
    table.add_row(
        "TOTALS", 
        "", "", "", 
        f"[bold]${visible_equity:,.2f}[/bold]", 
        f"[bold {tot_color}]${total_pl:,.2f}[/bold {tot_color}]", 
        f"[bold {tot_color}]{total_pct:,.2f}%[/bold {tot_color}]"
    )

    console.print(table)
    return True

def dashboard_loop():
    sort_col = "ticker"
    ascending = True
    
    # Map for easy typing
    sort_map = {
        "t": "ticker", "q": "total_qty", "e": "avg_entry", 
        "p": "current_price", "v": "market_value", "pl": "unrealized_pl", "%": "pl_pct"
    }

    while True:
        try:
            clear_screen()
            print_dashboard(sort_col, ascending)
            
            console.print(f"\n[dim]Refresh: {REFRESH_SECONDS}s | [bold]S[/bold]ort | [bold]Q[/bold]uit[/dim]")
            
            cmd = input("> ").strip().lower()

            if cmd == 'q': break
            elif cmd == 'r' or cmd == '': continue
            elif cmd == 's':
                key = input("Sort by (t/q/e/p/v/pl/%): ").strip().lower()
                if key in sort_map:
                    if sort_map[key] == sort_col:
                        ascending = not ascending
                    else:
                        sort_col = sort_map[key]
                        ascending = True
        except KeyboardInterrupt:
            break