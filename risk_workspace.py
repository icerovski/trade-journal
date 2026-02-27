import pandas as pd
import threading
from typing import Dict, Optional
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Label, Input, Select
from textual.containers import Horizontal, Vertical, Container
from textual.binding import Binding
from textual.message import Message
from textual import on, work

from core.portfolio_manager import PortfolioManager
from core.risk_engine import get_atr_discovery_data
from db import get_all_risk_settings, set_position_risk
from logger import logger

class RiskWorkspace(App):
    """
    Interactive Risk Assignment Workspace.
    Highly optimized for bulk strategy mapping with side-by-side Fixed vs Trailing.
    """
    TITLE = "RISK ASSIGNMENT WORKSPACE"
    SUB_TITLE = "Batch Strategy Mapping | [F1] Help"
    
    CSS = """
    Screen {
        background: $surface;
    }
    #main-layout {
        layout: horizontal;
        height: 1fr;
    }
    #left-pane {
        width: 60%;
        height: 1fr;
        border-right: tall $primary;
        padding-right: 1;
    }
    #right-pane {
        width: 40%;
        height: 1fr;
        padding-left: 1;
    }
    #discovery-layout {
        layout: vertical;
        height: auto;
        border-bottom: solid $secondary;
    }
    .discovery-sub-pane {
        height: 10;
        border-bottom: solid $secondary;
        padding: 0 1;
    }
    .base-price-label {
        background: $surface-lighten-1;
        color: $accent;
        text-align: center;
        text-style: bold;
        margin-bottom: 0;
        height: 1;
    }
    #portfolio-table {
        height: 1fr;
    }
    .discovery-table {
        height: 6;
    }
    .panel-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        text-align: center;
        background: $surface-darken-1;
        height: 1;
    }
    #position-context {
        background: $surface-darken-2;
        border: solid $secondary;
        padding: 1 2;
        margin-bottom: 1;
        height: 4;
        color: $text;
    }
    #input-container {
        border-top: solid $accent;
        padding: 0;
        background: $surface-lighten-1;
        height: auto;
        margin-top: 0;
    }
    #input-container Horizontal {
        height: 3;
        margin: 0;
    }
    #help-panel {
        background: $surface-darken-2;
        color: $text-muted;
        padding: 1 2;
        height: auto;
        border-top: tall $primary;
        display: none;
    }
    Input {
        width: 1fr;
        height: 3;
        margin-right: 1;
    }
    Select {
        width: 15;
        height: 3;
    }
    Select > .select--control {
        height: 3;
    }
    #preview-label {
        color: $success;
        text-style: italic;
        height: 1;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Back"),
        Binding("s", "save_all", "Save All"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "toggle_help", "Help"),
    ]

    class DiscoveryDataLoaded(Message):
        """Internal message when async ATR data is ready."""
        def __init__(self, conid: str, data: dict):
            self.conid = conid
            self.data = data
            super().__init__()

    def __init__(self):
        super().__init__()
        self.pm = PortfolioManager()
        self.positions = []
        self.drafts: Dict[str, Dict] = {} 
        self.current_conid: Optional[str] = None
        self.discovery_cache: Dict[str, dict] = {}
        self.total_nav = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-layout"):
            with Vertical(id="left-pane"):
                yield Label("PORTFOLIO RISK STATUS", classes="panel-header")
                yield DataTable(id="portfolio-table")
                
                with Vertical(id="input-container"):
                    yield Label("ASSIGN RISK STRATEGY", classes="panel-header")
                    with Horizontal():
                        yield Input(placeholder="Mult (1.5) or % (10%)", id="atr-input")
                        yield Select(
                            options=[("T", "TRAILING"), ("F", "FIXED")],
                            value="TRAILING",
                            id="stop-type-select"
                        )
                    yield Label("", id="preview-label")
            
            with Vertical(id="right-pane"):
                yield Label("ASSET CONTEXT", classes="panel-header")
                yield Static("Select a position...", id="position-context")
                
                with Container(id="discovery-layout"):
                    with Vertical(id="fixed-pane", classes="discovery-sub-pane"):
                        yield Label("FIXED STOP (Protection)", classes="panel-header")
                        yield Label("Base: ---", id="fixed-base", classes="base-price-label")
                        dt_fixed = DataTable(id="fixed-table", classes="discovery-table")
                        dt_fixed.can_focus = False
                        yield dt_fixed
                    with Vertical(id="trailing-pane", classes="discovery-sub-pane"):
                        yield Label("TRAILING STOP (Profit Harvest)", classes="panel-header")
                        yield Label("Base: ---", id="trailing-base", classes="base-price-label")
                        dt_trail = DataTable(id="trailing-table", classes="discovery-table")
                        dt_trail.can_focus = False
                        yield dt_trail
                
                yield Static(self.get_definitions_text(), id="help-panel")
        yield Footer()

    def get_definitions_text(self) -> str:
        return (
            "[bold white]DEFINITIONS & FORMULAS[/]\n"
            "• [bold]Base Price:[/] Reference point (Avg Cost for Fixed | Max High for Trailing)\n"
            "• [bold]Stop Price:[/] Base Price - ATR. Absolute exit threshold.\n"
            "• [bold]SL %:[/] decrease from [bold]BASE[/] price to Stop. (ATR / Base)\n"
            "• [bold]P/L Stop:[/] Total expected P/L from entry if triggered. (Stop - Entry) * Qty\n"
            "• [bold]R (% NAV):[/] Potential loss from Entry as % of total Portfolio NAV.\n"
            "• [bold]Buf %:[/] Distance from [bold]CURRENT[/] price to Stop. Your safety cushion."
        )

    def action_toggle_help(self) -> None:
        panel = self.query_one("#help-panel")
        panel.display = not panel.display

    def on_mount(self) -> None:
        # 1. Portfolio Table (Left Pane - 10 Columns)
        table = self.query_one("#portfolio-table")
        table.cursor_type = "row"
        table.add_column("TICKER", key="col_ticker")
        table.add_column("PRICE", key="col_price")
        table.add_column("ATR", key="col_atr")
        table.add_column("STOP", key="col_stop")
        table.add_column("SL %", key="col_sl_pct")
        table.add_column("P/L STOP", key="col_pl_stop")
        table.add_column("R", key="col_r")
        table.add_column("BUF %", key="col_buf_pct")
        table.add_column("TYPE", key="col_type")
        table.add_column("STATUS", key="col_status")
        
        # 2. Discovery Tables (Right Pane)
        for table_id in ["#fixed-table", "#trailing-table"]:
            dt = self.query_one(table_id)
            dt.add_column("WIN")
            dt.add_column("ATR")
            dt.add_column("STOP")
            dt.add_column("SL%")
            dt.add_column("P/L")
            dt.add_column("R")
            dt.add_column("BUF%")
        
        self.load_portfolio()

    def load_portfolio(self) -> None:
        """Loads positions and calculates metrics for existing risk strategies."""
        # 1. Fetch NAV FIRST to ensure R calculations in Discovery Pane are non-zero
        nav_res = self.pm.fetch_nav_data()
        self.total_nav = nav_res[0] if nav_res else 0.0
        
        # 2. Sync local positions list for worker threads
        self.positions = self.pm.get_open_positions_hybrid(asset_class_filter='STK')
        
        # 3. Get fully enriched data for the main grid
        df = self.pm.get_dashboard_df(asset_class_filter='STK', total_nav=self.total_nav, silent=True)
        if df.empty: return
        
        df = df.sort_values("Ticker")
        table = self.query_one("#portfolio-table")
        table.clear()
        
        for _, row in df.iterrows():
            conid_str = str(row['conid'])
            
            # Formatting values for the main grid
            has_risk = pd.notnull(row['ATR']) and row['ATR'] > 0
            
            atr_val = f"{row['ATR']:.2f}" if has_risk else "---"
            sl_price = f"{row['SL_Price']:,.2f}" if has_risk else "---"
            sl_pct = f"{row['sl_pct_base']:.1f}%" if has_risk else "---"
            pl_stop = f"{row['Risk_Val']:,.0f}" if has_risk else "---"
            r_val = f"{row['risk_pct_nav']:.1f}%" if has_risk else "---" # One decimal place
            buf_pct = f"{row['Down_Pct']:.1f}%" if has_risk else "---"
            stop_type = row['StopType'][:1] if has_risk else "---" # F or T
            
            # Status Logic
            if conid_str in self.drafts:
                status = "[bold yellow]PENDING[/]"
            else:
                status = "SET" if has_risk else "---"
            
            # Apply color to R
            if has_risk:
                r_num = row['risk_pct_nav']
                r_color = "red" if r_num >= 1.0 else ("yellow" if r_num >= 0.5 else "white")
                r_display = f"[{r_color}]{r_val}[/]"
                
                pl_color = "green" if row['Risk_Val'] >= 0 else "red"
                pl_display = f"[{pl_color}]{pl_stop}[/]"
            else:
                r_display = r_val
                pl_display = pl_stop

            table.add_row(
                row['Ticker'],
                f"{row['Price']:,.2f}",
                atr_val,
                sl_price,
                sl_pct,
                pl_display,
                r_display,
                buf_pct,
                stop_type,
                status,
                key=conid_str
            )

    @on(DataTable.RowHighlighted, "#portfolio-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        conid = event.row_key.value
        self.current_conid = conid
        
        # Immediate context update for responsiveness
        self.update_context_only()
        
        if conid in self.discovery_cache:
            self.update_discovery_ui(self.discovery_cache[conid])
        else:
            self.query_one("#fixed-table").clear()
            self.query_one("#trailing-table").clear()
            self.fetch_atr_data(conid)

    def update_context_only(self) -> None:
        """Updates the top right panel with asset info without waiting for market data."""
        if not self.positions:
            self.positions = self.pm.get_open_positions_hybrid(asset_class_filter='STK')
            
        p_name, p_entry = "---", "---"
        for p in self.positions:
            if str(p.conid) == self.current_conid:
                p_name = p.name
                p_entry = p.date_entry.strftime('%d-%b-%y') if pd.notnull(p.date_entry) else '---'
                break

        self.query_one("#position-context").update(
            f"[bold yellow]{p_name}[/]\n"
            f"Date of first entry: {p_entry}"
        )

    @work(exclusive=True, thread=True)
    def fetch_atr_data(self, conid: str) -> None:
        # Re-fetch positions if needed
        if not self.positions:
            self.positions = self.pm.get_open_positions_hybrid(asset_class_filter='STK')
            
        pos = next((p for p in self.positions if str(p.conid) == conid), None)
        if not pos: return
        
        data = get_atr_discovery_data(
            pos.ticker, 
            pos.date_entry.strftime("%Y-%m-%d"), 
            pos.entry_price,
            conid=pos.conid,
            qty=pos.qty,
            inst_multiplier=pos.multiplier,
            total_nav=self.total_nav
        )
        if data:
            self.discovery_cache[conid] = data
            self.post_message(self.DiscoveryDataLoaded(conid, data))

    @on(DiscoveryDataLoaded)
    def on_discovery_loaded(self, message: DiscoveryDataLoaded) -> None:
        if message.conid == self.current_conid:
            self.update_discovery_ui(message.data)

    def update_discovery_ui(self, data: dict) -> None:
        # Update context summary
        self.update_context_only()

        self.query_one("#fixed-base").update(f"Base: {data['entry_price']:,.2f}")
        self.query_one("#trailing-base").update(f"Base: {data['max_price']:,.2f}")

        fixed_table = self.query_one("#fixed-table")
        trail_table = self.query_one("#trailing-table")
        fixed_table.clear()
        trail_table.clear()

        for row in data['rows']:
            pl_color = "green" if row.pl_at_stop >= 0 else "red"
            r_color = "red" if row.pl_pct_nav >= 1.0 else ("yellow" if row.pl_pct_nav >= 0.5 else "white")
            
            row_vals = (
                row.label,
                f"{row.atr_wilder:.2f}",
                f"{row.stop_price:,.2f}",
                f"{row.atr_base_pct:.1f}%",
                f"[{pl_color}]{row.pl_at_stop:,.0f}[/]",
                f"[{r_color}]{row.pl_pct_nav:.1f}%[/]", # One decimal place
                f"{row.buffer_pct:.1f}%"
            )
            
            if row.stop_type == "FIXED":
                fixed_table.add_row(*row_vals)
            else:
                trail_table.add_row(*row_vals)

    @on(Input.Changed, "#atr-input")
    @on(Select.Changed, "#stop-type-select")
    def on_strategy_change(self) -> None:
        if not self.current_conid: return
        atr_text = self.query_one("#atr-input").value.strip()
        stop_type = self.query_one("#stop-type-select").value
        if not atr_text: return

        try:
            disc_data = self.discovery_cache.get(self.current_conid)
            if not disc_data: return

            final_atr = 0.0
            if atr_text.endswith('%'):
                pct = float(atr_text[:-1]) / 100
                base = disc_data['max_price'] if stop_type == 'TRAILING' else disc_data['entry_price']
                final_atr = base * pct
            else:
                try:
                    val = float(atr_text)
                    if 0.1 <= val <= 5.0 and disc_data['rows']:
                        daily_atr = next((r.atr_wilder for r in disc_data['rows'] if r.label == '14d'), disc_data['rows'][0].atr_wilder)
                        final_atr = daily_atr * val
                    else:
                        final_atr = val
                except ValueError: return
            
            if final_atr > 0:
                self.drafts[self.current_conid] = {'atr': final_atr, 'type': stop_type, 'ticker': disc_data['ticker']}
                table = self.query_one("#portfolio-table")
                table.update_cell(self.current_conid, "col_status", "[bold yellow]PENDING[/]")
                table.update_cell(self.current_conid, "col_atr", f"{final_atr:.2f}")
                table.update_cell(self.current_conid, "col_type", stop_type[:1])
                # We could update other columns here too, but they'd require more recalculation
                self.query_one("#preview-label").update(f"Preview: [bold cyan]{disc_data['ticker']}[/] ATR [bold yellow]{final_atr:.2f}[/] ({stop_type})")
        except Exception as e: logger.error(f"Input Error: {e}")

    def action_save_all(self) -> None:
        if not self.drafts: return
        for conid, draft in self.drafts.items():
            set_position_risk(conid, draft['ticker'], draft['atr'], draft['type'])
        self.notify(f"Saved {len(self.drafts)} profiles.")
        self.drafts.clear()
        self.load_portfolio()
        self.query_one("#atr-input").value = ""

    def action_refresh(self) -> None:
        self.discovery_cache.clear()
        self.load_portfolio()

def run_risk_workspace():
    app = RiskWorkspace()
    app.run()

if __name__ == "__main__":
    run_risk_workspace()
