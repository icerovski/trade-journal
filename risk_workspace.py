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
    Allows bulk assignment of ATR-based risk strategies.
    """
    TITLE = "RISK ASSIGNMENT WORKSPACE"
    SUB_TITLE = "Batch ATR Discovery & Strategy Mapping"
    
    CSS = """
    Screen {
        background: $surface;
    }
    #main-layout {
        layout: horizontal;
        height: 1fr;
    }
    #left-pane {
        width: 55%;
        height: 1fr;
        border-right: tall $primary;
    }
    #right-pane {
        width: 45%;
        height: 1fr;
        padding: 1 2;
    }
    DataTable {
        height: 1fr;
        border: solid $secondary;
    }
    .panel-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #discovery-table {
        height: 15;
        margin-bottom: 1;
    }
    #input-container {
        border: tall $accent;
        padding: 1 2;
        background: $surface-lighten-1;
        height: auto;
    }
    Input {
        width: 1fr;
        margin-right: 1;
    }
    Select {
        width: 20;
    }
    #preview-label {
        margin-top: 1;
        color: $success;
        text-style: italic;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Back to Menu"),
        Binding("s", "save_all", "Save All Changes", show=True),
        Binding("r", "refresh", "Refresh Data", show=True),
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
        self.drafts: Dict[str, Dict] = {} # {conid: {atr, type, ticker}}
        self.current_conid: Optional[str] = None
        self.discovery_cache: Dict[str, dict] = {}
        self.total_nav = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-layout"):
            with Vertical(id="left-pane"):
                yield Label("PORTFOLIO POSITIONS", classes="panel-header")
                yield DataTable(id="portfolio-table")
            with Vertical(id="right-pane"):
                yield Label("ATR DISCOVERY ENGINE", classes="panel-header")
                yield DataTable(id="discovery-table", classes="discovery-table")
                with Vertical(id="input-container"):
                    yield Label("ASSIGN RISK STRATEGY", classes="panel-header")
                    with Horizontal():
                        yield Input(placeholder="Multiplier (1.5) or % (10%)", id="atr-input")
                        yield Select(
                            options=[("Trailing", "TRAILING"), ("Fixed", "FIXED")],
                            value="TRAILING",
                            id="stop-type-select"
                        )
                    yield Label("", id="preview-label")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#portfolio-table")
        table.cursor_type = "row"
        # Using explicit keys for reliable cell updates
        table.add_column("TICKER", key="col_ticker")
        table.add_column("PRICE", key="col_price")
        table.add_column("CURR ATR", key="col_atr")
        table.add_column("ATR %", key="col_atr_pct")
        table.add_column("TYPE", key="col_type")
        table.add_column("STATUS", key="col_status")
        
        disc_table = self.query_one("#discovery-table")
        disc_table.add_columns("LABEL", "ATR (W)", "STOP", "ATR %", "P/L STOP", "BUF %")
        
        self.load_portfolio()

    def load_portfolio(self) -> None:
        """Fetch current holdings and risk settings."""
        self.positions = self.pm.get_open_positions_hybrid(asset_class_filter='STK')
        self.positions.sort(key=lambda x: x.ticker)
        risk_settings = get_all_risk_settings()
        
        nav_res = self.pm.fetch_nav_data()
        self.total_nav = nav_res[0] if nav_res else 0.0
        
        table = self.query_one("#portfolio-table")
        table.clear()
        
        for pos in self.positions:
            conid_str = str(pos.conid)
            current = risk_settings.get(conid_str)
            
            # Check if we have a pending draft for this item
            if conid_str in self.drafts:
                atr_val = f"{self.drafts[conid_str]['atr']:.2f}"
                stop_type = self.drafts[conid_str]['type']
                status = "[bold yellow]PENDING[/]"
            else:
                atr_val = f"{current[0]:.2f}" if current else "---"
                stop_type = current[1] if current else "---"
                status = "SET" if current else "---"
            
            atr_pct = f"{(float(atr_val) / pos.entry_price * 100):.1f}%" if atr_val != "---" and pos.entry_price > 0 else "---"
            
            table.add_row(
                pos.ticker,
                f"{pos.current_price or pos.mark_price:,.2f}",
                atr_val,
                atr_pct,
                stop_type,
                status,
                key=conid_str
            )

    @on(DataTable.RowHighlighted, "#portfolio-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Trigger async discovery when a position is highlighted."""
        conid = event.row_key.value
        self.current_conid = conid
        
        # Sync input with draft or clear
        input_widget = self.query_one("#atr-input")
        if conid in self.drafts:
            # We don't want to overwrite the user's multiplier string with the final ATR float
            # but for now we'll just show the pending value.
            input_widget.placeholder = f"Current Pending: {self.drafts[conid]['atr']:.2f}"
        else:
            input_widget.placeholder = "Multiplier (1.5) or % (10%)"
            
        if conid in self.discovery_cache:
            self.update_discovery_ui(self.discovery_cache[conid])
        else:
            self.fetch_atr_data(conid)

    @work(exclusive=True, thread=True)
    def fetch_atr_data(self, conid: str) -> None:
        """Background worker to fetch institutional analysis."""
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
        table = self.query_one("#discovery-table")
        table.clear()
        for row in data['rows']:
            pl_color = "green" if row.pl_at_stop >= 0 else "red"
            table.add_row(
                row.label,
                f"{row.atr_wilder:.2f}",
                f"{row.stop_price:,.2f}",
                f"{row.atr_base_pct:.1f}%",
                f"[{pl_color}]{row.pl_at_stop:,.0f}[/]",
                f"{row.buffer_pct:.1f}%"
            )

    @on(Input.Changed, "#atr-input")
    @on(Select.Changed, "#stop-type-select")
    def on_strategy_change(self) -> None:
        """Handle drafting a new risk strategy."""
        if not self.current_conid: return
        
        atr_text = self.query_one("#atr-input").value.strip()
        stop_type = self.query_one("#stop-type-select").value
        
        if not atr_text:
            return

        try:
            pos = next((p for p in self.positions if str(p.conid) == self.current_conid), None)
            disc_data = self.discovery_cache.get(self.current_conid)
            if not pos: return

            final_atr = 0.0
            # 1. Percentage Mode (Needs discovery data for base price)
            if atr_text.endswith('%') and disc_data:
                pct = float(atr_text[:-1]) / 100
                base = disc_data['max_price'] if stop_type == 'TRAILING' else disc_data['entry_price']
                final_atr = base * pct
            # 2. Multiplier or Absolute Mode
            else:
                try:
                    val = float(atr_text)
                    # Heuristic: If val is small and discovery data exists, assume multiplier of Daily ATR
                    if 0.1 <= val <= 5.0 and disc_data and disc_data['rows']:
                        daily_atr = disc_data['rows'][0].atr_wilder
                        final_atr = daily_atr * val
                    else:
                        final_atr = val
                except ValueError:
                    return
            
            if final_atr > 0:
                self.drafts[self.current_conid] = {'atr': final_atr, 'type': stop_type, 'ticker': pos.ticker}
                # Update UI Table Row
                table = self.query_one("#portfolio-table")
                table.update_cell(self.current_conid, "col_status", "[bold yellow]PENDING[/]")
                table.update_cell(self.current_conid, "col_atr", f"{final_atr:.2f}")
                table.update_cell(self.current_conid, "col_type", stop_type)
                
                self.query_one("#preview-label").update(f"Preview: [bold cyan]{pos.ticker}[/] ATR [bold yellow]{final_atr:.2f}[/] ({stop_type})")
        except Exception as e:
            logger.error(f"Input Parsing Error: {e}")

    def action_save_all(self) -> None:
        """Commit all drafts to the database."""
        if not self.drafts:
            self.notify("No pending changes to save.", severity="warning")
            return
        
        count = 0
        for conid, draft in self.drafts.items():
            set_position_risk(conid, draft['ticker'], draft['atr'], draft['type'])
            count += 1
            
        self.notify(f"SUCCESS: Saved {count} risk profiles.")
        self.drafts.clear()
        self.load_portfolio()
        self.query_one("#atr-input").value = ""
        self.query_one("#preview-label").update("")

    def action_refresh(self) -> None:
        self.discovery_cache.clear()
        self.load_portfolio()

def run_risk_workspace():
    app = RiskWorkspace()
    app.run()

if __name__ == "__main__":
    run_risk_workspace()
