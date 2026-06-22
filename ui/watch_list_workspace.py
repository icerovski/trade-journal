import pandas as pd
from typing import Dict, Optional
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, DataTable, Static, Label, Input, Button
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from textual.message import Message
from textual import on, work

from core.portfolio_manager import PortfolioManager
from core.stop_loss import audit_position_risk, calculate_position_risk, get_atr_discovery_data
from db import get_all_monitored_profiles, delete_risk_profile, set_position_risk, get_presets
from logger import logger, suppress_console_logging
from .chart_utils import launch_price_chart
from core.confluence import evaluate_confluence
from core.ui_utils import UIUtils


class AddProspectScreen(ModalScreen):
    """Dedicated add-to-watchlist entry point: prompt for a ticker symbol.

    Returns the entered symbol (uppercased, stripped) on submit, or None on
    cancel. The heavy lifting (price fetch, ATR discovery, persistence) happens
    in the parent workspace's background worker.
    """

    CSS = """
    AddProspectScreen { align: center middle; }
    #add-container {
        width: 50;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #add-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #add-buttons { height: auto; margin-top: 1; align-horizontal: right; }
    #add-buttons Button { margin-left: 2; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="add-container"):
            yield Label("ADD WATCH-LIST PROSPECT", id="add-title")
            yield Input(placeholder="Ticker symbol (e.g. AAPL)", id="add-input")
            with Horizontal(id="add-buttons"):
                yield Button("Add", id="btn-add", variant="success")
                yield Button("Cancel", id="btn-add-cancel", variant="default")

    def on_mount(self) -> None:
        self.query_one("#add-input", Input).focus()

    @on(Input.Submitted, "#add-input")
    def _on_submit(self, event: Input.Submitted) -> None:
        self._commit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            self._commit()
        else:
            self.dismiss(None)

    def _commit(self) -> None:
        symbol = self.query_one("#add-input", Input).value.strip().upper()
        self.dismiss(symbol or None)

    def action_cancel(self) -> None:
        self.dismiss(None)

class WatchListWorkspace(App):
    """
    Command Center for the Confluence Zone Discovery Method.
    Displays all monitored tickers (Prospects & Owned) and runs technical analysis.
    """
    TITLE = "WATCH LIST COMMAND CENTER"
    SUB_TITLE = "Institutional Confluence & Trend Analysis"

    CSS = """
    Screen {
        background: $surface;
    }
    #main-container {
        height: 1fr;
        width: 100%;
    }
    #prospects-table {
        width: 35%;
        height: 1fr;
        border-right: tall $secondary;
    }
    #analysis-panel {
        width: 65%;
        height: 1fr;
        padding: 1 2;
        background: $surface-darken-1;
    }
    .panel-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        padding-bottom: 1;
        border-bottom: solid $secondary;
        width: 100%;
    }
    .metric-label {
        color: $text-muted;
    }
    .metric-value {
        text-style: bold;
        color: $text;
    }
    .box {
        margin-bottom: 1;
        padding: 1;
        border: solid $secondary;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("q", "exit_app", "Exit"),
        Binding("a", "add_prospect", "Add"),
        Binding("r", "refresh_data", "Refresh"),
        Binding("d", "delete_prospect", "Delete Prospect"),
        Binding("g", "show_chart", "Chart"),
    ]

    class AnalysisLoaded(Message):
        """Internal message when background math completes."""
        def __init__(self, ticker: str, data: dict):
            self.ticker = ticker
            self.data = data
            super().__init__()

    class ProspectAdded(Message):
        """Internal message when the add-prospect worker finishes (success or not)."""
        def __init__(self, ticker: str, ok: bool, msg: str):
            self.ticker = ticker
            self.ok = ok
            self.msg = msg
            super().__init__()

    def __init__(self):
        super().__init__()
        self.pm = PortfolioManager()
        self.current_ticker: Optional[str] = None
        self.analysis_cache: Dict[str, dict] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            yield DataTable(id="prospects-table", cursor_type="row")
            with Vertical(id="analysis-panel"):
                yield Label("CONFLUENCE & TREND ANALYSIS", classes="panel-header")
                with Vertical(id="analysis-content"):
                    yield Static("[dim]Select a ticker to run analysis...[/dim]", id="loading-text")
                    
                    # Trend Status
                    with Vertical(classes="box"):
                        yield Label("Trend Engine (200-DMA)", classes="metric-label")
                        yield Static("...", id="trend-status", classes="metric-value")
                    
                    # Confluence Zones
                    with Vertical(classes="box"):
                        yield Label("Confluence Strength", classes="metric-label")
                        yield Static("...", id="confluence-strength", classes="metric-value")
                        yield DataTable(id="confluence-table", cursor_type="none")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#prospects-table", DataTable)
        table.add_column("TICKER", key="col_ticker")
        table.add_column("STATUS", key="col_status")
        table.add_column("PRICE", key="col_price")
        table.add_column("BUFFER %", key="col_buffer")
        table.add_column("RISK %", key="col_risk")
        table.add_column("ATR", key="col_atr")
        
        c_table = self.query_one("#confluence-table", DataTable)
        c_table.add_column("Indicator")
        c_table.add_column("Price Dist %")
        c_table.add_column("Price Dist ATR")
        c_table.add_column("Stop Dist %")
        c_table.add_column("Stop Dist ATR")
        
        self.load_prospects()

    def load_prospects(self) -> None:
        table = self.query_one("#prospects-table", DataTable)
        table.clear()
        
        # Get total NAV for risk calculation
        nav_res = self.pm.fetch_nav_data()
        total_nav, nav_ccy = (nav_res[0], nav_res[1]) if nav_res else (0.0, "???")

        # Use PortfolioManager to get enriched watch list data
        df, _ = self.pm.get_dashboard_df(include_watch=True, total_nav=total_nav, silent=True)
        self.sub_title = UIUtils.nav_subtitle(total_nav, nav_ccy, len(df))
        if df.empty:
            self.notify("No monitored profiles found. Press [a] to add a ticker.")
            return

        # Sort: Prospects first, then Active
        df['SortOrder'] = df['account_id'].apply(lambda x: 0 if x == 'WATCHLIST' else 1)
        df = df.sort_values(['SortOrder', 'Ticker'])

        for _, row in df.iterrows():
            status_display = "[bold yellow]WATCH[/]" if row['account_id'] == 'WATCHLIST' else "[bold green]OWNED[/]"
            
            # Formatting metrics
            price_val = row['Price']
            buffer_val = row['Down_Pct']
            risk_val = row['risk_pct_nav']
            
            table.add_row(
                f"[bold cyan]{row['Ticker']}[/]",
                status_display,
                f"{price_val:,.2f}",
                f"{buffer_val:,.1f}%",
                f"{risk_val:.1f}%",
                f"{row['ATR']:.2f}",
                key=row['Ticker']
            )
        
        if not df.empty:
            table.focus()

    @on(DataTable.RowHighlighted, "#prospects-table")
    def on_prospect_highlighted(self, event: DataTable.RowHighlighted) -> None:
        ticker = event.row_key.value
        self.current_ticker = ticker
        
        self.query_one("#loading-text", Static).update(f"[bold yellow]Running math for {ticker}...[/]")
        self.query_one("#trend-status", Static).update("...")
        self.query_one("#confluence-strength", Static).update("...")
        self.query_one("#confluence-table", DataTable).clear()
        
        if ticker in self.analysis_cache:
            self.post_message(self.AnalysisLoaded(ticker, self.analysis_cache[ticker]))
        else:
            self.run_background_math(ticker)

    @work(exclusive=True, thread=True)
    def run_background_math(self, ticker: str) -> None:
        try:
            with suppress_console_logging():
                data = get_atr_discovery_data(ticker, pd.Timestamp.now().strftime("%Y-%m-%d"), 0.0, mapper=self.pm.mapper)
            if data:
                self.post_message(self.AnalysisLoaded(ticker, data))
        except Exception as e:
            logger.error(f"Watch List Math Error for {ticker}: {e}")

    @on(AnalysisLoaded)
    def on_analysis_loaded(self, message: AnalysisLoaded) -> None:
        if message.ticker != self.current_ticker:
            return
            
        self.analysis_cache[message.ticker] = message.data
        data = message.data
        
        self.query_one("#loading-text", Static).update(f"Technical Audit: [bold cyan]{message.ticker}[/]. Price: [bold]{data['current_price']:,.2f}[/]")
        
        # 1. Trend Analysis
        trend_data = data.get('trend_data', {})
        if trend_data.get('status') == 'OK':
            t_info = trend_data['dma200_trend']
            dir_str = "🟢 UP" if t_info['direction'] == 'UP' else "🔴 DOWN"
            sig_str = f"[bold green]{t_info['signal']}[/]" if t_info['signal'] == 'BUY' else (f"[bold red]{t_info['signal']}[/]" if t_info['signal'] == 'SELL' else "[yellow]NEUTRAL[/]")
            self.query_one("#trend-status", Static).update(
                f"{dir_str} ({t_info['consecutive_days']} days) | Trigger: {sig_str}"
            )
        else:
            self.query_one("#trend-status", Static).update("[dim]Insufficient data for 200-DMA trend.[/dim]")

        # 2. Confluence Analysis
        # Extract 14d ATR for the math
        r_14d = next((r for r in data['rows'] if r.label == "14d" and r.stop_type == "FIXED"), None)
        atr_14 = r_14d.atr_wilder if r_14d else (data['current_price'] * 0.05)
        
        # Pull the specific Watch List prospect to get its configured stop
        profiles = get_all_monitored_profiles()
        p_cfg = next((p for p in profiles if p.ticker == message.ticker), None)
        assigned_atr = p_cfg.atr_value if p_cfg else atr_14
        
        stop_price = data['current_price'] - assigned_atr
        
        dmas = trend_data.get('dmas', {})

        # Build the ordered level map and score it through the shared engine.
        indicators = [
            'DMA200', 'EMA200',
            'DMA100', 'EMA100',
            'DMA50', 'EMA50',
            'DMA10', 'EMA10'
        ]
        levels = {name: dmas.get(name) for name in indicators}
        conf = evaluate_confluence(data['current_price'], stop_price, levels, atr_14)

        # Populate Table — one row per level, highlighting in-zone distances.
        c_table = self.query_one("#confluence-table", DataTable)
        c_table.clear()
        for lvl in conf['levels']:
            p_style = "bold green" if lvl['price_in_zone'] else "white"
            s_style = "bold cyan" if lvl['stop_in_zone'] else "white"
            # Indicator, Price Dist (%), Price Dist (ATR), Stop Dist (%), Stop Dist (ATR)
            c_table.add_row(
                lvl['name'],
                f"[{p_style}]{lvl['price_pct']:.2f}%[/]",
                f"[{p_style}]{lvl['price_atr']:.2f}R[/]",
                f"[{s_style}]{lvl['stop_pct']:.2f}%[/]",
                f"[{s_style}]{lvl['stop_atr']:.2f}R[/]"
            )

        # Strength = in-zone hits within CONFLUENCE_ATR_THRESHOLD of price or stop.
        strength = conf['strength']
        score_color = "green" if strength >= 3 else ("yellow" if strength >= 1 else "red")
        self.query_one("#confluence-strength", Static).update(f"[{score_color}]{strength}-Point Cluster Detected[/]")

    def action_show_chart(self) -> None:
        if not self.current_ticker:
            return
        profiles = get_all_monitored_profiles()
        p_cfg = next((p for p in profiles if p.ticker == self.current_ticker), None)
        conid = str(p_cfg.conid) if p_cfg else None
        yf_ticker = self.pm.mapper.resolve_yf_ticker(self.current_ticker, conid=int(conid) if conid else None)
        launch_price_chart(self.current_ticker, conid=conid, yf_ticker=yf_ticker)

    def action_delete_prospect(self) -> None:
        if not self.current_ticker:
            return
        # Find the conid for this ticker in the DB
        profiles = get_all_monitored_profiles()
        p_cfg = next((p for p in profiles if p.ticker == self.current_ticker), None)
        if p_cfg:
            delete_risk_profile(p_cfg.conid)
            self.notify(f"Stopped monitoring {self.current_ticker}.")
            self.analysis_cache.pop(self.current_ticker, None)
            self.load_prospects()

    def action_add_prospect(self) -> None:
        def _on_closed(symbol: Optional[str]) -> None:
            if symbol:
                self.notify(f"Adding {symbol}…")
                self.add_prospect_worker(symbol)
        self.push_screen(AddProspectScreen(), _on_closed)

    @work(exclusive=False, thread=True)
    def add_prospect_worker(self, symbol: str) -> None:
        """Resolve, price, and persist a new WATCH prospect. Runs off the UI thread;
        marshals the result back via ProspectAdded for the table refresh + notify."""
        symbol = symbol.strip().upper()
        try:
            with suppress_console_logging():
                # Duplicate guard — one WATCH/ACTIVE profile per ticker.
                if any(p.ticker == symbol for p in get_all_monitored_profiles()):
                    self.post_message(self.ProspectAdded(symbol, False, f"{symbol} is already monitored."))
                    return

                # ATR discovery validates the ticker and (via its trend-analysis call)
                # caches prices under PROSPECT:{symbol}, so the name is immediately
                # scannable and chartable.
                data = get_atr_discovery_data(
                    symbol, pd.Timestamp.now().strftime("%Y-%m-%d"), 0.0, mapper=self.pm.mapper
                )
                if not data or not data.get('rows'):
                    self.post_message(self.ProspectAdded(symbol, False, f"Couldn't resolve or price {symbol}."))
                    return

                row = next((r for r in data['rows'] if r.label == "14d" and r.stop_type == "TRAILING"), None)
                if row is None:
                    self.post_message(self.ProspectAdded(symbol, False, f"No daily ATR available for {symbol}."))
                    return

                presets = get_presets() or {}
                base = presets.get('B', {})
                max_r = base.get('max_r_pct', 0.60)
                max_exp = base.get('max_exp_pct', 3.0)

                set_position_risk(
                    f"PROSPECT:{symbol}", symbol, row.atr_wilder, "TRAILING",
                    status="WATCH", max_r_pct=max_r, max_exp_pct=max_exp,
                    inception_stop=row.stop_price, inception_atr=row.atr_wilder,
                    profile="B", reset_sl=True,
                )
            self.post_message(self.ProspectAdded(symbol, True, f"Added {symbol} to the watch list (TRAILING / Base)."))
        except Exception as e:
            logger.error(f"Add prospect error for {symbol}: {e}")
            self.post_message(self.ProspectAdded(symbol, False, f"Error adding {symbol}: {e}"))

    @on(ProspectAdded)
    def on_prospect_added(self, message: ProspectAdded) -> None:
        self.notify(message.msg, severity="information" if message.ok else "warning")
        if message.ok:
            self.analysis_cache.pop(message.ticker, None)
            self.load_prospects()

    def action_refresh_data(self) -> None:
        self.analysis_cache.clear()
        self.load_prospects()

def run_watch_list_workspace():
    WatchListWorkspace().run()

if __name__ == "__main__":
    run_watch_list_workspace()
