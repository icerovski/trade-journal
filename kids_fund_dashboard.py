from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Label
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from core.portfolio_manager import PortfolioManager
from core.kids_fund_engine import KidsFundEngine
from config import KIDS_ACCOUNT_ID, KIDS_ASSETS

class KidsFundDashboard(App):
    """Interactive Dashboard for the Kids Private Wealth Fund."""
    TITLE = "KIDS FUND MANAGEMENT"
    SUB_TITLE = "Glide Path Audit & Individual Ownership"
    
    CSS = """
    Screen { background: $surface; }
    #main-container { layout: vertical; padding: 1; }
    .panel-header { text-style: bold; color: $accent; background: $surface-darken-1; text-align: center; height: 1; }
    #summary-bar { height: 6; border: solid $secondary; margin-bottom: 1; padding: 0 1; }
    #summary-bar-text { width: 30%; padding: 1; }
    #summary-table { width: 70%; height: 5; }
    #tables-container { layout: horizontal; height: 1fr; }
    #ownership-pane { width: 40%; height: 1fr; border-right: tall $primary; }
    #glide-pane { width: 60%; height: 1fr; padding-left: 1; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self):
        super().__init__()
        self.pm = PortfolioManager()
        self.engine = KidsFundEngine()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            yield Static("FUND SUMMARY", classes="panel-header")
            with Horizontal(id="summary-bar"):
                yield Static("Loading fund data...", id="summary-bar-text")
                yield DataTable(id="summary-table")
            
            with Horizontal(id="tables-container"):
                with Vertical(id="ownership-pane"):
                    yield Label("INDIVIDUAL OWNERSHIP (Units)", classes="panel-header")
                    yield DataTable(id="ownership-table")
                
                with Vertical(id="glide-pane"):
                    yield Label("GLIDE PATH AUDIT (Targets)", classes="panel-header")
                    yield DataTable(id="glide-table")
        yield Footer()

    def on_mount(self) -> None:
        # Setup Summary Table
        summary_table = self.query_one("#summary-table")
        summary_table.add_columns("TICKER", "TOTAL QTY", "VALUE (€)", "GROWTH/SAFETY")

        # Setup Ownership Table
        own_table = self.query_one("#ownership-table")
        own_table.add_columns("CHILD", "UNITS", "OWNERSHIP %", "NAV SHARE")
        
        # Setup Glide Table
        glide_table = self.query_one("#glide-table")
        glide_table.add_columns("CHILD", "AGE", "TARGET SAFETY %", "GROWTH (€)", "SAFETY (€)")
        
        self.action_refresh()

    def action_refresh(self) -> None:
        """Reloads all data and refreshes UI."""
        # 1. Fetch Account NAV and Holdings
        nav_total, accounts, _ = self.pm.fetch_nav_data()
        kids_account_nav = next((a['nav'] for a in accounts if str(a['alias']) == KIDS_ACCOUNT_ID), 0.0)
        
        # Filter main dashboard logic for just this account
        kids_holdings, _ = self.pm.get_dashboard_df(account_id=KIDS_ACCOUNT_ID, total_nav=kids_account_nav, silent=True)
        
        # 2. Get Ownership Data
        kids_data = self.engine.calculate_ownership()
        
        # 3. Get Glide Path Audit
        audit = self.engine.get_glide_path_audit(kids_data, kids_account_nav)
        
        # 4. Update Summary Bar
        summary = (
            f"[bold yellow]Account:[/] {KIDS_ACCOUNT_ID}\n"
            f"[bold yellow]Total Fund NAV:[/] €{kids_account_nav:,.2f}"
        )
        self.query_one("#summary-bar-text", Static).update(summary)
        
        # 5. Populate Holdings Summary Table
        summary_table = self.query_one("#summary-table")
        summary_table.clear()
        for _, row in kids_holdings.iterrows():
            is_growth = row['Ticker'] == KIDS_ASSETS['GROWTH']['ticker']
            cat_label = "[bold green]GROWTH[/]" if is_growth else "[bold blue]SAFETY[/]"
            summary_table.add_row(
                row['Ticker'],
                f"{row['Qty']:,.0f}",
                f"€{row['MarketValue']:,.2f}",
                cat_label
            )
        
        # 6. Populate Ownership Table
        own_table = self.query_one("#ownership-table")
        own_table.clear()
        for name, data in kids_data.items():
            child_nav = kids_account_nav * (data['ownership_pct'] / 100.0)
            own_table.add_row(
                name,
                f"{data['current_units']:,.2f}",
                f"{data['ownership_pct']:.2f}%",
                f"€{child_nav:,.2f}"
            )
            
        # 7. Populate Glide Table
        glide_table = self.query_one("#glide-table")
        glide_table.clear()
        for res in audit:
            glide_table.add_row(
                res['name'],
                str(res['age']),
                f"{res['target_safety_pct']:.0f}%",
                f"€{res['target_growth_val']:,.0f}",
                f"€{res['target_safety_val']:,.0f}"
            )

def run_kids_fund_dashboard():
    KidsFundDashboard().run()

if __name__ == "__main__":
    run_kids_fund_dashboard()
