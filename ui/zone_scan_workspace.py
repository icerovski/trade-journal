"""Entry/Exit Zone Scanner — Textual workspace.

Scans the live universe (ACTIVE holdings + status='WATCH' prospects) for
confluence zones, rendering the ZONE / ZONE-MOMO tag, converging signals, the
chosen stop (base or momentum micro-structure), target, and position size under
each risk preset. Display-only; never writes to the database.

The volume profile underneath is a daily-bar approximation, not tick-derived —
flagged in the footer.
"""

import sqlite3
from typing import Optional

import pandas as pd
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import DataTable, Footer, Header, Label, Static
from textual import on, work

from config import PRICES_DB_PATH
from core.portfolio_manager import PortfolioManager
from core.ui_utils import UIUtils
from core.zone_scan import build_zone_report
from core.calibration import get_calibration
from db import get_presets, get_setting
from logger import logger, suppress_console_logging
from services.price_service import PriceService

# Fallback presets if the DB matrix is empty (mirrors risk_workspace defaults).
_DEFAULT_PRESETS = {
    "S": {"label": "Small", "max_r_pct": 0.30, "max_exp_pct": 1.5},
    "B": {"label": "Base", "max_r_pct": 0.60, "max_exp_pct": 3.0},
    "L": {"label": "Large/Index", "max_r_pct": 1.00, "max_exp_pct": 5.0},
}


def _load_ohlcv(conid: str) -> pd.DataFrame:
    """Daily OHLCV for a conid from prices.db, in the lowercase/date-column shape
    the zone scanner expects."""
    if not conid:
        return pd.DataFrame()
    conn = sqlite3.connect(PRICES_DB_PATH)
    try:
        return pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices_daily "
            "WHERE conid = ? ORDER BY date ASC",
            conn, params=(str(conid),),
        )
    finally:
        conn.close()


class ZoneScanWorkspace(App):
    TITLE = "ENTRY/EXIT ZONE SCANNER"
    SUB_TITLE = "Composite Volume Profile · Anchored VWAP · MA Confluence"

    CSS = """
    Screen { background: $surface; }
    #main-container { height: 1fr; width: 100%; }
    #results-table {
        width: 55%;
        height: 1fr;
        border-right: tall $secondary;
    }
    #detail-panel {
        width: 45%;
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
    .box {
        margin-bottom: 1;
        padding: 1;
        border: solid $secondary;
        background: $surface;
    }
    #footer-note { color: $text-muted; text-style: italic; margin-top: 1; }
    """

    BINDINGS = [
        Binding("q", "exit_app", "Exit"),
        Binding("r", "refresh", "Rescan"),
    ]

    class ScanLoaded(Message):
        def __init__(self, results: list, nav: float, nav_ccy: str):
            self.results = results
            self.nav = nav
            self.nav_ccy = nav_ccy
            super().__init__()

    def __init__(self):
        super().__init__()
        self.pm = PortfolioManager()
        self.ps = PriceService()
        self.results: list = []
        self.by_ticker: dict = {}

    def _load_or_fetch_ohlcv(self, item: dict) -> pd.DataFrame:
        """Cache-first price loader for the scan. Reads prices.db; if a conid has
        no cached history (the WATCH case — the daily sync covers only open
        positions), back-fills it once via PriceService, then re-reads.

        Open positions always have cache, so they never trigger a network round-
        trip here. A fetch failure on one ticker logs and returns empty rather
        than aborting the whole scan."""
        conid = item.get("conid")
        df = _load_ohlcv(conid)
        if not df.empty or not conid:
            return df

        try:
            yf_ticker = self.pm.mapper.resolve_yf_ticker(item.get("ticker", ""), conid=conid)
            if not yf_ticker:
                return df
            logger.info(f"Zone scan: back-filling prices for WATCH name {item.get('ticker')} ({yf_ticker})")
            self.ps.fetch_and_store(conid, yf_ticker)
        except Exception as e:
            logger.warning(f"Zone scan: price back-fill failed for {item.get('ticker')}: {e}")
            return df

        return _load_ohlcv(conid)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            yield DataTable(id="results-table", cursor_type="row")
            with Vertical(id="detail-panel"):
                yield Label("ZONE DETAIL", classes="panel-header")
                yield Static("[dim]Scanning universe…[/dim]", id="detail-header")
                with Vertical(classes="box"):
                    yield Label("Converging signals", classes="metric-label")
                    yield Static("…", id="detail-signals")
                with Vertical(classes="box"):
                    yield Label("Stop / Target", classes="metric-label")
                    yield Static("…", id="detail-plan")
                with Vertical(classes="box"):
                    yield Label("Position size by preset", classes="metric-label")
                    yield Static("…", id="detail-sizes")
                yield Static(
                    "Note: volume profile is a daily-bar approximation, not tick-derived.",
                    id="footer-note",
                )
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#results-table", DataTable)
        t.add_column("TAG", key="tag")
        t.add_column("TICKER", key="ticker")
        t.add_column("REGIME", key="regime")
        t.add_column("PRICE", key="price")
        t.add_column("DIST", key="dist")
        t.add_column("SIG", key="sig")
        t.add_column("STOP", key="stop")
        self.run_scan()

    @work(exclusive=True, thread=True)
    def run_scan(self) -> None:
        try:
            with suppress_console_logging():
                nav_res = self.pm.fetch_nav_data()
                total_nav, nav_ccy = (nav_res[0], nav_res[1]) if nav_res else (0.0, "???")

                _, positions = self.pm.get_dashboard_df(
                    include_watch=True, total_nav=total_nav, silent=True
                )
                universe = []
                for p in positions:
                    price = p.current_price or p.mark_price
                    universe.append({
                        "ticker": p.ticker,
                        "conid": str(p.conid),
                        "multiplier": p.multiplier or 1.0,
                        "price": price if price and price > 0 else None,
                    })

                presets = get_presets() or _DEFAULT_PRESETS
                calibration = get_calibration(get_setting('calibration_profile', 'default'))
                results = build_zone_report(universe, self._load_or_fetch_ohlcv,
                                            total_nav, presets, calibration=calibration)
            self.post_message(self.ScanLoaded(results, total_nav, nav_ccy))
        except Exception as e:
            logger.error(f"Zone scan error: {e}")
            self.post_message(self.ScanLoaded([], 0.0, "???"))

    @on(ScanLoaded)
    def on_scan_loaded(self, message: ScanLoaded) -> None:
        self.results = message.results
        self.by_ticker = {r["ticker"]: r for r in message.results}
        n_flagged = sum(1 for r in message.results if r["flagged"])
        self.sub_title = UIUtils.nav_subtitle(message.nav, message.nav_ccy, len(message.results))

        t = self.query_one("#results-table", DataTable)
        t.clear()
        if not self.results:
            self.query_one("#detail-header", Static).update("[yellow]No scannable tickers (no cached prices?).[/]")
            return

        for r in self.results:
            tag = r["tag"] or "—"
            tag_styled = (
                f"[bold magenta]{tag}[/]" if tag == "ZONE-MOMO"
                else f"[bold green]{tag}[/]" if tag == "ZONE"
                else f"[dim]{tag}[/]"
            )
            dist = f"{r['dist_to_zone_pct']:.2f}%" if r["dist_to_zone_pct"] is not None else "—"
            stop = f"{r['stop']:.2f}" if r["flagged"] else "—"
            regime = ("[magenta]MOMO[/]" if r["regime"] == "MOMENTUM" else "[dim]base[/]")
            t.add_row(
                tag_styled, f"[cyan]{r['ticker']}[/]", regime,
                f"{r['price']:,.2f}", dist, str(len(r["entry_signals"])), stop,
                key=r["ticker"],
            )
        self.query_one("#detail-header", Static).update(
            f"[bold]{n_flagged}[/] of {len(self.results)} flagged. Select a row for detail."
        )
        t.focus()

    @on(DataTable.RowHighlighted, "#results-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        r = self.by_ticker.get(event.row_key.value)
        if not r:
            return

        tag = r["tag"] or "no zone"
        color = "magenta" if r["regime"] == "MOMENTUM" else "green"
        self.query_one("#detail-header", Static).update(
            f"[bold {color}]{r['ticker']} — {tag}[/]   "
            f"price {r['price']:,.2f}  ·  regime {r['regime']}"
        )

        if r["entry_signals"]:
            lines = []
            for z in sorted(r["entry_signals"], key=lambda z: z["atr_distance"]):
                fort = " [yellow]★[/]" if z["is_fortress"] else ""
                lines.append(
                    f"  {z['name']:<12} {z['value']:>10,.2f}  "
                    f"({z['atr_distance']:.2f}R / {z['pct_distance']:.2f}%){fort}"
                )
            self.query_one("#detail-signals", Static).update("\n".join(lines))
        else:
            self.query_one("#detail-signals", Static).update("[dim]No converging signals at price.[/]")

        if r["flagged"]:
            tgt_src = "naked POC" if r.get("target_from_naked_poc") else "3R"
            self.query_one("#detail-plan", Static).update(
                f"  Stop:   [red]{r['stop']:,.2f}[/]  ({r['stop_source']}, −{r['stop_pct']:.1f}%)\n"
                f"  Target: [green]{r['target']:,.2f}[/]  ({tgt_src})\n"
                f"  Risk/share: {r['risk_per_share']:,.2f}"
            )
            sizes = "\n".join(
                f"  {s['label']:<12} ({s['max_r_pct']:.2f}R / {s['max_exp_pct']:.1f}% exp):"
                f"  [bold]{s['qty']:,}[/] sh"
                for s in r["sizes"].values()
            )
            self.query_one("#detail-sizes", Static).update(sizes)
        else:
            self.query_one("#detail-plan", Static).update("[dim]No zone flagged — nearest level shown in DIST.[/]")
            self.query_one("#detail-sizes", Static).update("[dim]—[/]")

    def action_refresh(self) -> None:
        self.query_one("#detail-header", Static).update("[dim]Rescanning…[/dim]")
        self.run_scan()

    def action_exit_app(self) -> None:
        self.exit()


def run_zone_scan_workspace():
    ZoneScanWorkspace().run()


if __name__ == "__main__":
    run_zone_scan_workspace()
