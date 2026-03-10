import pandas as pd
import threading
from datetime import datetime
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Label
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from textual.message import Message
from textual import on

from logger import logger, disable_console_logging, enable_console_logging
from core.portfolio_manager import PortfolioManager

class TradingCockpit(App):
    """
    Institutional-grade Trading Cockpit built with Textual.
    Fixed on Hybrid data method with 60s background refresh.
    """
    TITLE = "PRIVATE EQUITY TRADING COCKPIT"
    SUB_TITLE = "Institutional Risk Management | [F1] Help"
    
    CSS = """
    Screen {
        background: $surface;
    }
    #main-container {
        height: 1fr;
        width: 100%;
    }
    DataTable {
        width: 1fr;
        height: 1fr;
        border: tall $primary;
    }
    #details-panel {
        width: 45;
        min-width: 45;
        height: 1fr;
        background: $surface-darken-1;
        border: tall $secondary;
        padding: 1 2;
    }
    .status-bar {
        height: 1;
        background: $accent;
        color: white;
        padding: 0 1;
        width: 100%;
    }
    .bold-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #help-panel {
        background: $surface-darken-2;
        color: $text-muted;
        padding: 1 2;
        height: auto;
        border-top: tall $primary;
        # font-size: 0.9em;
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Exit"),
        Binding("r", "refresh_manual", "Manual Refresh"),
        Binding("1", "sort('Ticker')", "Sort: Ticker"),
        Binding("2", "sort('PL_Daily_Pct')", "Sort: P/L %"),
        Binding("3", "sort('PL_Inc_Pct')", "Sort: Unrl %"),
        Binding("4", "sort('MarketValue')", "Sort: Mkt Val"),
        Binding("a", "filter('None')", "All"),
        Binding("s", "filter('STK')", "Stocks"),
        Binding("o", "filter('OPT')", "Options"),
        Binding("b", "filter('BOND')", "Bonds"),
        Binding("t", "filter('BILL')", "Treasuries"),
        Binding("f1", "toggle_help", "Help"),
    ]

    @staticmethod
    def color_fmt(val, fmt=",.0f", suffix=""):
        """Centralized color scheme: Green for positive, Red for negative."""
        color = "green" if val >= 0 else "red"
        return f"[{color}]{val:{fmt}}{suffix}[/]"

    class DataRefreshed(Message):
        """Internal message to update UI after background fetch."""
        def __init__(self, df: pd.DataFrame, df_view: pd.DataFrame, nav: float, report_date: str):
            self.df = df
            self.df_view = df_view
            self.nav = nav
            self.report_date = report_date
            super().__init__()

    def __init__(self, pm: PortfolioManager, asset_filter=None, sort_by="Ticker"):
        super().__init__()
        self.pm = pm
        self.asset_filter = asset_filter
        self.sort_by = sort_by
        self.df = pd.DataFrame()
        self.total_nav = 0.0
        self.report_date = "---"
        self._exit_flag = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            yield DataTable(id="holdings-table")
            with Vertical(id="details-panel"):
                yield Label("POSITION DETAILS", classes="bold-header")
                yield Static("Select a ticker to see analysis...", id="details-text")
        yield Label("Initializing...", id="status-bar", classes="status-bar")
        yield Static(self.get_help_text(), id="help-panel")
        yield Footer()

    def get_help_text(self) -> str:
        return (
            "[bold white]TRADING COCKPIT LEGEND[/]\n"
            "• [bold]Sort Keys:[/] [1]Ticker | [2]Daily P/L % | [3]Unrealized % | [4]Market Value\n"
            "• [bold]Filter Keys:[/] [A]ll | [S]tocks | [O]ptions | [B]onds | [T]reasuries\n"
            "• [bold]Indicators:[/] 🔴 Stop Breached | 🟢 Target Price Reached\n"
            "• [bold]AAGR:[/] Annualized Aggregate Growth Rate (Compound Annual Growth)\n"
            "• [bold]R (% NAV):[/] Total risk of current stop loss as a percentage of total Portfolio NAV."
        )

    def action_toggle_help(self) -> None:
        panel = self.query_one("#help-panel")
        panel.display = not panel.display

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("TICKER", "PRICE", "QTY", "P/L DAY", "P/L %", "UNRL P&L", "UNRL %", "COST VAL", "MKT VAL", "% NAV")
        
        # Start background loop thread
        self.refresh_thread = threading.Thread(target=self.refresh_loop, daemon=True)
        self.refresh_thread.start()

    def action_refresh_manual(self) -> None:
        """Manually trigger a refresh."""
        threading.Thread(target=self.fetch_data, daemon=True).start()

    def action_sort(self, sort_field: str) -> None:
        """Update sort preference and refresh UI immediately."""
        self.sort_by = sort_field
        if not self.df.empty:
            df_view = self.process_and_sort(self.df)
            self.update_ui(df_view, self.total_nav, self.report_date)

    def action_filter(self, asset_class: str) -> None:
        """Update asset filter and refresh UI immediately."""
        if asset_class == "None" or not asset_class:
            self.asset_filter = None
        else:
            self.asset_filter = asset_class
            
        if not self.df.empty:
            df_view = self.process_and_sort(self.df)
            self.update_ui(df_view, self.total_nav, self.report_date)

    def refresh_loop(self) -> None:
        """Background loop running in a dedicated thread (60s heartbeat)."""
        while not self._exit_flag.is_set():
            self.fetch_data()
            self._exit_flag.wait(timeout=60) # Fixed institutional refresh interval

    def fetch_data(self) -> None:
        """The actual heavy-lifting data fetch (Hybrid Method)."""
        try:
            self.update_status("[yellow]REFRESHING MARKET DATA...[/yellow]")
            disable_console_logging()
            
            nav_res = self.pm.fetch_nav_data(force_download=False)
            real_nav, _, r_date = nav_res if nav_res else (0.0, [], "---")
            
            # Always fetch ALL to allow dynamic in-memory filtering.
            df, _ = self.pm.get_dashboard_df(
                asset_class_filter=None, 
                total_nav=real_nav,
                silent=True
            )
            enable_console_logging()

            # Swift Swap: Always use current sort AND filter preference
            df_view = self.process_and_sort(df) if not df.empty else df
            self.post_message(self.DataRefreshed(df, df_view, real_nav, r_date))
            
        except Exception as e:
            logger.error(f"Fetch Error: {e}")
            self.update_status(f"[red]REFRESH ERROR: {e}[/red]")

    def update_status(self, msg: str):
        """Thread-safe status update."""
        def _update():
            try:
                self.query_one("#status-bar").update(msg)
            except Exception:
                pass

        if threading.get_ident() == self._thread_id:
            _update()
        else:
            self.call_from_thread(_update)

    @on(DataRefreshed)
    def handle_data_refresh(self, message: DataRefreshed) -> None:
        """Update UI components using the new data."""
        self.df = message.df
        self.total_nav = message.nav
        self.report_date = message.report_date
        self.update_ui(message.df_view, self.total_nav, self.report_date)

    def update_ui(self, df_view: pd.DataFrame, nav: float, report_date: str):
        """Internal UI update for the table and status bar."""
        table = self.query_one(DataTable)
        table.clear()

        for _, row in df_view.iterrows():
            # Breach Indicators
            ticker_display = str(row['Ticker'])
            if pd.notnull(row['SL_Price']) and row['Price'] <= row['SL_Price']:
                ticker_display = f"🔴 {ticker_display}"
            elif pd.notnull(row['TP_Price']) and row['Price'] >= row['TP_Price']:
                ticker_display = f"🟢 {ticker_display}"

            table.add_row(
                ticker_display,
                f"{row['Price']:,.2f}",
                f"{row['Qty']:,.0f}",
                self.color_fmt(row['PL_Daily']),
                self.color_fmt(row['PL_Daily_Pct'], ".1f", "%"),
                self.color_fmt(row['PL_Inc']),
                self.color_fmt(row['PL_Inc_Pct'], ".1f", "%"),
                f"{row['CostBasis']:,.0f}",
                f"{row['MarketValue']:,.0f}",
                f"{row['NavPct']:.1f}%"
            )

        filter_label = self.asset_filter if self.asset_filter else "ALL"
        self.update_status(f"IBKR: {report_date} | AUM: {nav:,.0f} | Filter: {filter_label} | Sort: {self.sort_by} | Last Update: {datetime.now().strftime('%H:%M:%S')}")
        self.update_details()

    @on(DataTable.RowSelected)
    @on(DataTable.RowHighlighted)
    def update_details(self) -> None:
        """Update sidebar with full institutional analysis."""
        try:
            table = self.query_one(DataTable)
            if table.cursor_row < 0 or self.df.empty:
                return

            df_view = self.process_and_sort(self.df)
            row_idx = table.cursor_row
            if row_idx < len(df_view):
                row = df_view.iloc[row_idx]

                # Risk Metrics Calculations
                s_type = str(row.get('StopType', '---'))
                atr_val = row.get('ATR', 0.0)
                # Volatility relative to Cost Basis (Initial Entry)
                atr_pct_cost = (atr_val / row['Entry'] * 100) if row['Entry'] > 0 else 0

                details = (
                    f"[bold yellow]{row['Name']}[/bold yellow]\n"
                    f"{'-'*35}\n"
                    f"[bold cyan]STRUCTURE[/bold cyan]\n"
                    f"Exchange:   {row.get('ListingExchange', '---')}\n"
                    f"Underlying: {row.get('UnderlyingSymbol', '---')}\n"
                    f"Asset Class: {row.get('AssetClass', '---')}\n"
                    f"Currency:   {row.get('CCY', '---')}\n\n"

                    f"[bold cyan]RISK PARAMETERS[/bold cyan]\n"
                    f"ATR (% of cost): {atr_val:.2f} ({atr_pct_cost:.1f}%)\n"
                    f"Stop Type:      {s_type}\n"
                    f"Stop Price:     [bold red]{row['SL_Price']:,.2f}[/]\n"
                    f"P/L at Stop:    {self.color_fmt(row['Risk_Val'], ',.0f')}\n"
                    f"Buffer to SL:   {self.color_fmt(row['Down_Pct'], '.1f', '%')}\n\n"

                    f"[bold cyan]TARGET PROFIT[/bold cyan]\n"
                    f"Target Price:   [bold green]{row['TP_Price']:,.2f}[/]\n"
                    f"P/L at Target:  {self.color_fmt(row['Reward_Val'], ',.0f')}\n"
                    f"Buffer to Tgt:  {self.color_fmt(row['Up_Pct'], '.1f', '%')}\n\n"

                    f"[bold magenta]PERFORMANCE[/bold magenta]\n"
                    f"First Entry:      {row['Date'].strftime('%d-%b-%y') if pd.notnull(row['Date']) else '---'}\n"
                    f"Avg Cost:         {row['Entry']:,.2f}\n"
                    f"High achieved:    {row['MaxSinceEntry']:,.2f}\n"
                    f"AAGR (Growth):    {self.color_fmt(row['AAGR'], '.1f', '%')}\n"
                    f"Holding Age:      {row['Age_Days']} days"
                )
                self.query_one("#details-text").update(details)
        except Exception as e:
            logger.error(f"Sidebar Update Error: {e}")

    def process_and_sort(self, df):
        """Generalized logic supporting dynamic field selection AND filtering."""
        if df.empty:
            return df

        if self.asset_filter and str(self.asset_filter) != "None":
            target_class = str(self.asset_filter).upper()
            if target_class == 'TREASURIES':
                target_class = 'BILL'
            df = df[df['AssetClass'].str.upper() == target_class]

        field_map = {"Pct": "PL_Inc_Pct", "PL": "PL_Inc"}
        actual_field = field_map.get(self.sort_by, self.sort_by)
        ascending = actual_field in ["Ticker", "Date", "AssetClass"]

        if actual_field in df.columns:
            return df.sort_values(actual_field, ascending=ascending)

        sort_cols = [c for c in ['AssetClass', 'Ticker'] if c in df.columns]
        return df.sort_values(sort_cols, ascending=True) if sort_cols else df

    def action_quit(self) -> None:
        """Handle clean shutdown."""
        self._exit_flag.set()
        self.exit()

def run_live_dashboard(portfolio_manager, sort_by="Ticker"):
    """Launch the cockpit with hardcoded institutional defaults."""
    app = TradingCockpit(portfolio_manager, None, sort_by)
    try:
        app.run()
    except KeyboardInterrupt:
        pass

def print_nav_table(portfolio_manager, force_download=False):
    """Rich-based fallback for simple CLI output."""
    from rich.table import Table
    from rich import box
    data = portfolio_manager.fetch_nav_data(force_download=force_download)
    if not data:
        return 0.0
    total, accounts, report_date = data
    table = Table(box=box.SIMPLE_HEAD, title=f"[bold]ACCOUNT BALANCES (IBKR {report_date})[/bold]")
    table.add_column("ALIAS", style="cyan")
    table.add_column("NAV", justify="right", style="green")
    for a in accounts:
        table.add_row(str(a['alias']), f"€{a['nav']:,.2f}")
    table.add_section()
    table.add_row("TOTAL", f"€{total:,.2f}")
    from rich.console import Console
    Console().print(table)
    return total
