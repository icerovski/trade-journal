# main.py
import sys
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from ibkr import fetch_opening_balance, fetch_ytd_trades, fetch_latest_prices
from dashboard import render_dashboard
from db import init_db, archive_database

console = Console()

def main_menu():
    console.print("")
    console.print(Panel("[bold]1.[/bold] View Dashboard  [bold]2.[/bold] Fetch Prices  [bold]3.[/bold] Fetch History  [bold]0.[/bold] Exit", border_style="blue", title="MENU"))

def main():
    init_db()
    console.clear()
    
    while True:
        main_menu()
        choice = Prompt.ask("Select Option", choices=["1", "2", "3", "4", "9", "0"], default="1")
        
        if choice == '1':
            render_dashboard()
            
        elif choice == '2':
            console.print("[cyan]Fetching latest NAV & Prices...[/cyan]")
            if fetch_latest_prices():
                render_dashboard()
            else:
                console.print("[red]Failed to fetch prices.[/red]")
                
        elif choice == '3':
            console.print("[cyan]Updating Trade History...[/cyan]")
            fetch_ytd_trades()
            
        elif choice == '9':
            archive_database()
            
        elif choice == '0':
            console.print("Goodbye!")
            sys.exit()

if __name__ == "__main__":
    main()