# dashboard.py
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich import box
from datetime import datetime
from manager import get_portfolio_data

console = Console()

def render_dashboard():
    """
    Fetches data and renders the rich dashboard.
    """
    console.print("\n[bold cyan]⏳ Calculating Metrics...[/bold cyan]")
    df, nav = get_portfolio_data()
    console.clear()

    # --- HEADER PANEL ---
    # Shows specific NAV and current timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Safely sum Unrealized P/L
    total_unr_pl = df['unrealized_pl'].sum() if not df.empty else 0.0
    pl_color = "green" if total_unr_pl >= 0 else "red"

    header_text = (
        f"[bold white]TOTAL NAV:   [/bold white] [bold green]${nav:,.2f}[/bold green]\n"
        f"[dim]As of {timestamp}[/dim]\n"
        f"[bold white]Total P/L:   [/bold white] [{pl_color}]${total_unr_pl:,.2f}[/{pl_color}]"
    )
    
    console.print(Panel(header_text, title="🚀 PORTFOLIO DASHBOARD", border_style="cyan"))

    if df.empty:
        console.print(Panel("[yellow]No open positions found in pricing snapshot.[/yellow]", title="Warning"))
        return

    # --- MAIN TABLE ---
    table = Table(box=box.SIMPLE_HEAD, expand=True)
    
    # Columns
    table.add_column("Ticker", style="bold cyan")
    table.add_column("First Entry", style="dim white")
    table.add_column("Qty", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Mkt Value", justify="right", style="bold")
    table.add_column("Unr. P/L", justify="right")
    table.add_column("P/L %", justify="right")
    table.add_column("Ann. %", justify="right") # New Column

    # Rows
    for _, row in df.iterrows():
        # Color Logic
        pl_val = row['unrealized_pl']
        pl_pct = row['pl_pct']
        ann_pct = row['annualized_pct']
        
        c_pl = "green" if pl_val >= 0 else "red"
        c_ann = "green" if ann_pct >= 0 else "red"
        
        # Formatting
        entry_date = row['first_entry']
        
        # Handle < 1 year vs > 1 year display for Annualized
        ann_str = f"[{c_ann}]{ann_pct:.1f}%[/{c_ann}]"
        # Optional: Add an asterisk if it's < 1 year (simple return)
        if entry_date != "N/A":
            try:
                days = (datetime.now() - datetime.strptime(entry_date, '%Y-%m-%d')).days
                if days < 365:
                    ann_str += "*" # Mark as simple return
            except: pass

        table.add_row(
            row['ticker'],
            entry_date,
            f"{row['total_qty']:.1f}",
            f"{row['current_price']:.2f}",
            f"{row['avg_entry']:.2f}",
            f"${row['market_value']:,.0f}",
            f"[{c_pl}]${pl_val:,.0f}[/{c_pl}]",
            f"[{c_pl}]{pl_pct:.1f}%[/{c_pl}]",
            ann_str
        )

    console.print(table)
    console.print("[dim]* Annualized % shows Simple Return for positions held < 1 year[/dim]")