import pandas as pd
import re
from typing import Dict, Optional
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Label, Input, Button, TabbedContent, TabPane
from textual.containers import Horizontal, Vertical, Container, ScrollableContainer
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual import on, work

from core.portfolio_manager import PortfolioManager
from core.stop_loss import audit_position_risk, calculate_position_risk, get_atr_discovery_data
from core.ui_utils import UIUtils
from .chart_utils import launch_price_chart
from services.ui_components import HelpScreen
from db import set_position_risk, get_presets, save_preset, update_preset_profiles, get_setting, save_setting
from logger import logger, suppress_console_logging
from constants import RISK_RED_MULTIPLIER, EXPOSURE_RED_MULTIPLIER

PRESETS = {
    "S": {"label": "Small",       "max_exp_pct": 1.5, "max_r_pct": 0.30},
    "B": {"label": "Base",        "max_exp_pct": 3.0, "max_r_pct": 0.60},
    "L": {"label": "Large/Index", "max_exp_pct": 5.0, "max_r_pct": 1.00},
}
ACTION_THRESHOLD_PCT = 10.0

def _load_presets_from_db():
    """Sync in-memory PRESETS and settings from the DB."""
    global ACTION_THRESHOLD_PCT
    try:
        for key, vals in get_presets().items():
            if key in PRESETS:
                PRESETS[key].update(vals)
        ACTION_THRESHOLD_PCT = float(get_setting('action_threshold_pct', '10.0'))
    except Exception:
        pass

_WS_TRIM = {
    ('M2', 'TREND'):   (0.15, "Token trim 15% — preserve trend runway"),
    ('M2', 'NORMAL'):  (0.33, "Trim 33%"),
    ('M2', 'RANGING'): (0.50, "Trim 50% — protect gains"),
    ('TP', 'TREND'):   (0.20, "Trim 20% — raise TP to weekly ATR level"),
    ('TP', 'NORMAL'):  (0.33, "Trim 33% or close; keep runner if RR > 1.0"),
    ('TP', 'RANGING'): (1.00, "Close position — no trend support"),
}
_STAGE_C  = {'PRE-M1': 'dim', 'M1': 'cyan', 'M2': 'yellow', 'TP': 'green'}
_REGIME_C = {'TREND': 'green', 'NORMAL': 'white', 'RANGING': 'red'}

def _exit_guidance_str(pos, cur_p: float) -> str:
    stage  = getattr(pos, 'exit_stage', '')
    regime = getattr(pos, 'trend_regime', 'NORMAL')
    dma    = getattr(pos, 'regime_dma', '')
    dma200 = getattr(pos, 'regime_dma200', 0.0)
    m1     = getattr(pos, 'm1_price', 0.0)
    m2     = getattr(pos, 'm2_price', 0.0)
    tp     = getattr(pos, 'tp_price', 0.0) or 0.0

    if not stage:
        return ""

    sc = _STAGE_C.get(stage, 'white')
    rc = _REGIME_C.get(regime, 'white')

    # ── Milestone ladder ──────────────────────────────────────────────────────
    order   = ('PRE-M1', 'M1', 'M2', 'TP')
    cur_idx = order.index(stage) if stage in order else 0

    def _ms(label, price, idx):
        if price <= 0:
            return f"[dim]{label}: ---[/]"
        if idx < cur_idx:
            return f"[green]{label}: {price:,.2f} ✓[/]"
        if idx == cur_idx:
            return f"[{sc}][bold]{label}: {price:,.2f} ◄[/][/]"
        return f"[dim]{label}: {price:,.2f}[/]"

    ladder = (f"  {_ms('M1', m1, 1)}   {_ms('M2', m2, 2)}   {_ms('TP', tp, 3)}\n")

    # ── Regime calculation breakdown ─────────────────────────────────────────
    dma_signal = dma.split(' ')[0] if dma else 'NEUTRAL'
    dma_days_str = dma.split(' ')[1].strip('()d') if ' ' in dma else '0'
    dma_days = int(dma_days_str) if dma_days_str.isdigit() else 0
    dma_c = 'green' if dma_signal == 'BUY' else ('red' if dma_signal == 'SELL' else 'yellow')

    if dma200 > 0 and cur_p > 0:
        diff = cur_p - dma200
        diff_c = 'green' if diff >= 0 else 'red'
        dma200_str = f"{dma200:,.2f}  (price [{diff_c}]{'+' if diff>=0 else ''}{diff:,.2f}[/] vs DMA)"
    else:
        dma200_str = "---"

    if regime == 'TREND':
        verdict = f"[green]Rising {dma_days}d (≥ 21) → TREND[/]"
    elif regime == 'NORMAL':
        verdict = f"[white]Rising {dma_days}d (10–20) → NORMAL[/]"
    else:
        if dma_signal == 'SELL':
            verdict = f"[red]Declining {dma_days}d → RANGING[/]"
        else:
            verdict = f"[red]Rising only {dma_days}d (< 10) → RANGING[/]"

    calc = (
        f"\n  REGIME CALCULATION:\n"
        f"  200-DMA:    {dma200_str}\n"
        f"  DMA signal: [{dma_c}]{dma_signal} ({dma_days}d)[/]  →  {verdict}\n"
    )

    # ── Action ────────────────────────────────────────────────────────────────
    action = ""
    key = (stage, regime)
    if key in _WS_TRIM:
        pct, desc = _WS_TRIM[key]
        shares = max(1, int(pos.qty * pct))
        action = f"\n  [bold]→ {desc} (~{shares} sh)[/]\n"

    return (
        f"\n──────────────────────────────────────────\n"
        f"EXIT STAGE: [{sc}][bold]{stage}[/][/]   "
        f"Regime: [{rc}][bold]{regime}[/][/]\n"
        f"{ladder}"
        f"{calc}"
        f"{action}"
    )

def _preset_legend(active: str = "") -> str:
    parts = []
    for key, p in PRESETS.items():
        color = "bold cyan" if key == active else "dim"
        parts.append(f"[{color}][{key}] {p['label']}: E:{p['max_exp_pct']} R:{p['max_r_pct']}[/]")
    return "  ·  ".join(parts)

# =============================================================================
# 1. UI COMPONENTS
# =============================================================================
class AdaptiveInputContainer(Container):
    """
    A container that swaps between horizontal and vertical layouts 
    based on available width to prevent text clipping.
    """
    def on_resize(self, event) -> None:
        if self.size.width < 100:  # Threshold for "small laptop screen"
            self.styles.layout = "vertical"
            self.styles.height = "auto"
        else:
            self.styles.layout = "horizontal"
            self.styles.height = 3

# =============================================================================
# 2. PRESET MATRIX SCREEN
# =============================================================================
class PresetMatrixScreen(ModalScreen):
    """Modal for editing and persisting preset risk profile definitions."""

    BINDINGS = [
        Binding("ctrl+s", "commit", "Commit"),
        Binding("escape", "dismiss_cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="matrix-container"):
            yield Label("PRESET DEFINITIONS", classes="panel-header")
            yield Label("  [dim]Key  Label            E%       R%[/]")
            for key, p in PRESETS.items():
                with Horizontal(classes="matrix-row"):
                    yield Label(f"  [bold cyan][{key}][/]  {p['label']:<14}", classes="matrix-label-col")
                    yield Input(str(p['max_exp_pct']), id=f"e_{key}", classes="matrix-input")
                    yield Input(str(p['max_r_pct']),   id=f"r_{key}", classes="matrix-input")
            yield Label("  [dim]─────────────────────────────────────────────[/]")
            with Horizontal(classes="matrix-row"):
                yield Label("  [dim]Action threshold (% of position)[/]", classes="matrix-label-col")
                yield Input(str(ACTION_THRESHOLD_PCT), id="action_threshold", classes="matrix-input")
            with Horizontal(id="matrix-buttons"):
                yield Button("COMMIT", id="btn-commit", variant="success")
                yield Button("Cancel", id="btn-cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-commit":
            self._commit()
        else:
            self.dismiss([])

    def action_commit(self) -> None:
        self._commit()

    def _commit(self) -> None:
        global ACTION_THRESHOLD_PCT
        new_vals: dict[str, tuple[float, float]] = {}
        for key in PRESETS:
            try:
                new_e = float(self.query_one(f"#e_{key}", Input).value)
                new_r = float(self.query_one(f"#r_{key}", Input).value)
            except ValueError:
                self.notify(f"Invalid value for preset {key}", severity="error")
                return
            new_vals[key] = (new_r, new_e)

        try:
            new_threshold = float(self.query_one("#action_threshold", Input).value)
        except ValueError:
            self.notify("Invalid action threshold", severity="error")
            return

        changed = [
            key for key, (new_r, new_e) in new_vals.items()
            if new_r != PRESETS[key]["max_r_pct"] or new_e != PRESETS[key]["max_exp_pct"]
        ]
        for key, (new_r, new_e) in new_vals.items():
            PRESETS[key]["max_r_pct"] = new_r
            PRESETS[key]["max_exp_pct"] = new_e
        for key in changed:
            new_r, new_e = new_vals[key]
            save_preset(key, PRESETS[key]["label"], new_r, new_e)
            update_preset_profiles(key, new_r, new_e)

        ACTION_THRESHOLD_PCT = new_threshold
        save_setting('action_threshold_pct', str(new_threshold))

        self.dismiss(changed)

    def action_dismiss_cancel(self) -> None:
        self.dismiss([])


# =============================================================================
# 3. MAIN WORKSPACE APPLICATION
# =============================================================================
class RiskWorkspace(App):
    TITLE = "RISK ASSIGNMENT WORKSPACE"
    SUB_TITLE = "Portfolio Audit & Strategy Lab | [F1] Help"
    
    CSS = """
    Screen { background: $surface; }
    
    #main-layout { layout: horizontal; height: 1fr; }
    #left-pane { width: 60%; height: 1fr; border-right: tall $primary; padding-right: 1; }
    #right-pane { width: 40%; height: 1fr; padding-left: 1; }
    #portfolio-table { height: 1fr; }
    
    #sidebar-scroll {
        height: 55%;
        border: solid $secondary;
        background: $surface-darken-2;
        overflow-y: scroll;
        scrollbar-gutter: stable;
    }
    
    #discovery-layout { 
        height: 45%;
        border: solid $secondary;
        background: $surface-darken-2;
        scrollbar-gutter: stable;
        overflow-y: auto;
        overflow-x: hidden;
        scrollbar-size: 2 2;
    }
    
    #fixed-stop-table, #trailing-stop-table {
        height: auto;
        width: 100%;
        min-height: 5;
        overflow-x: scroll;
    }
    
    .base-price-label { background: $surface-lighten-1; color: $accent; text-align: center; text-style: bold; height: 1; }
    .panel-header { text-style: bold; color: $accent; text-align: center; background: $surface-darken-1; height: 1; }
    
    #position-context { 
        padding: 0 1;
        color: $text; 
    }
    
    #strategy-lab { 
        border-top: solid $secondary; 
        background: $surface-lighten-1; 
        height: auto; 
        min-height: 6;
        padding: 0 1; 
    }
    #lab-inputs {
        margin-top: 0;
        height: 3;
    }
    #discover-input { width: 2fr; min-width: 20; }
    #atr-input { width: 3fr; min-width: 40; }
    #preset-legend { height: 1; text-align: center; padding: 0 1; }
    #help-modal { background: $surface-darken-3; border: tall $accent; width: 80%; height: 80%; padding: 1 2; align: center middle; margin: 5 10; }
    #close-hint { text-align: center; color: $text-muted; margin-top: 1; }
    
    .table-section-label {
        background: $surface-lighten-1;
        color: $text;
        padding: 0 1;
        text-style: bold;
        margin-top: 0;
        width: 100%;
    }
    PresetMatrixScreen { align: center middle; }
    #matrix-container {
        width: 58;
        height: 24;
        border: tall $accent;
        background: $surface-darken-1;
        padding: 1 2;
    }
    .matrix-row { height: 3; }
    .matrix-label-col { width: 26; content-align: left middle; }
    .matrix-input { width: 12; margin: 0 1; }
    #matrix-buttons { height: 3; margin-top: 1; align: center middle; }
    #matrix-buttons Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Back"),
        Binding("s", "save_all", "Save All"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "toggle_help", "Help"),
        Binding("g", "show_chart", "Chart"),
        Binding("m", "open_matrix", "Presets"),
    ]

    class DiscoveryDataLoaded(Message):
        def __init__(self, conid: str, data: dict):
            self.conid = conid
            self.data = data
            super().__init__()

    def __init__(self):
        super().__init__()
        self.pm = PortfolioManager()
        self.positions = []
        self.enriched_data = pd.DataFrame()
        self.drafts: Dict[str, Dict] = {}
        self.current_conid: Optional[str] = None
        self.discovery_cache: Dict[str, dict] = {}
        self.total_nav = 0.0
        self.nav_ccy = "USD"

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-layout"):
            with Vertical(id="left-pane"):
                yield Label("PORTFOLIO RISK STATUS", classes="panel-header")
                yield DataTable(id="portfolio-table")
                with Vertical(id="strategy-lab"):
                    yield Label("RISK STRATEGY & TICKER DISCOVERY", classes="panel-header")
                    with Horizontal(id="lab-inputs"):
                        yield Input(
                            placeholder="Discover Ticker (e.g. NVDA)",
                            id="discover-input"
                        )
                        yield Input(
                            placeholder="F: price  |  T: %/$  |  [P:S/B/L] [R:x] [E:x]",
                            id="atr-input"
                        )
                    yield Label(_preset_legend(), id="preset-legend")
            with Vertical(id="right-pane"):
                yield Label("ASSET CONTEXT & RISK AUDIT", classes="panel-header")
                with ScrollableContainer(id="sidebar-scroll"):
                    yield Static("Select a position...", id="position-context")
                
                yield Label("ATR DISCOVERY & CONFLUENCE", classes="panel-header")
                with ScrollableContainer(id="discovery-layout"):
                    yield Label("[bold cyan]FIXED STOP | BASE: ENTRY[/]", classes="table-section-label", id="fixed-label")
                    yield DataTable(id="fixed-stop-table")
                    yield Label("[bold magenta]TRAILING STOP | BASE: HIGH[/]", classes="table-section-label", id="trailing-label")
                    yield DataTable(id="trailing-stop-table")
        yield Footer()

    def on_mount(self) -> None:
        _load_presets_from_db()
        self.query_one("#preset-legend", Label).update(_preset_legend())
        table = self.query_one("#portfolio-table", DataTable)
        table.cursor_type = "row"
        table.add_column("TICKER", key="col_ticker")
        table.add_column("ACTION", key="col_action")
        table.add_column("STOP BASE", key="col_base")
        table.add_column("ATR", key="col_atr")
        table.add_column("STOP P", key="col_stop_p")
        table.add_column("SL %", key="col_sl_pct")
        table.add_column("P/L STOP", key="col_pl_stop")
        table.add_column("MKT VAL", key="col_mkt_val")
        table.add_column("COST", key="col_cost")
        table.add_column("CUR P", key="col_cur_p")
        table.add_column("AVG COST", key="col_avg_cost")
        table.add_column("% NAV", key="col_nav_pct")
        table.add_column("R", key="col_r")
        table.add_column("RR", key="col_rr")
        
        # Setup Fixed Stop Table
        table_f = self.query_one("#fixed-stop-table", DataTable)
        table_f.can_focus = False
        for col, key in [("WIN", "f_win"), ("ATR(W)", "f_atr_w"), ("SL%(W)", "f_sl_w"), ("ATR(S)", "f_atr_s"), ("SL%(S)", "f_sl_s"), ("STOP", "f_stop"), ("QTY", "f_qty"), ("P/L", "f_pl"), ("R", "f_r"), ("BUF%", "f_buf")]:
            table_f.add_column(col, key=key, width=(10 if col == "WIN" else None))

        # Setup Trailing Stop Table
        table_t = self.query_one("#trailing-stop-table", DataTable)
        table_t.can_focus = False
        for col, key in [("WIN", "t_win"), ("ATR(W)", "t_atr_w"), ("SL%(W)", "t_sl_w"), ("ATR(S)", "t_atr_s"), ("SL%(S)", "t_sl_s"), ("STOP", "t_stop"), ("QTY", "t_qty"), ("P/L", "t_pl"), ("R", "t_r"), ("BUF%", "t_buf")]:
            table_t.add_column(col, key=key, width=(10 if col == "WIN" else None))
        
        self.load_portfolio()

    def load_portfolio(self) -> None:
        """Syncs Ledger and calculates metrics, including Stop-Breach signals."""
        nav_res = self.pm.fetch_nav_data()
        if nav_res:
            self.total_nav, self.nav_ccy, _, _ = nav_res
        else:
            self.total_nav = 0.0
            self.nav_ccy = "???"

        self.enriched_data, self.positions = self.pm.get_dashboard_df(asset_class_filter=['STK'], total_nav=self.total_nav, silent=True, include_watch=True)
        self.sub_title = UIUtils.nav_subtitle(self.total_nav, self.nav_ccy, len(self.enriched_data), "[F1] Help")
        if self.enriched_data.empty:
            return
        table = self.query_one("#portfolio-table", DataTable)
        table.clear()
        for _, row in self.enriched_data.sort_values("Ticker").iterrows():
            conid_str = str(row['conid'])
            has_risk = pd.notnull(row['ATR']) and row['ATR'] > 0
            max_r_pct = row.get('MaxRPct', 1.0)
            max_exp_pct = row.get('MaxExpPct', 5.0)
            
            risk_above_limit = row['risk_pct_nav'] > max_r_pct
            exp_above_limit = row['NavPct'] > max_exp_pct
            
            profile_key = row.get('Profile') or ''
            stop_prefix = f"{row['StopType'][:1]}:{profile_key}" if profile_key else row['StopType'][:1]
            ticker_display = f"[{stop_prefix}] {row['Ticker']}"
            if conid_str in self.drafts:
                d = self.drafts[conid_str]
                ticker_display = f"[bold yellow]* [{d['type'][:1]}] {row['Ticker']}"
                max_r_pct = d.get('max_r_pct', max_r_pct)
                max_exp_pct = d.get('max_exp_pct', max_exp_pct)
            
            # 1. Base Variables
            cur_p_val = row['Price']
            sl_p = row['SL_Price']
            tp_p = row.get('TP_Price')

            # 2. Meaningful Action & Warning Logic
            action_display = ""
            adj = 0
            if has_risk and self.total_nav > 0:
                effective_entry = row['Entry'] if row['Entry'] > 0 else row['Price']
                res = audit_position_risk(
                    cur_p_val, sl_p, effective_entry, row['Qty'], row.get('Multiplier', 1.0),
                    self.total_nav, max_r_pct=max_r_pct, max_exp_pct=max_exp_pct,
                    fx_rate=row.get('FXRate', 1.0)
                )
                adj = res['adjustment']
                qty = row['Qty']
                
                if qty == 0: # Prospect
                    action_display = f"[bold cyan]BUY {int(adj)}[/]"
                else:
                    adj_pct = (adj / qty) * 100
                    add_threshold = max(1, int(qty * ACTION_THRESHOLD_PCT / 100.0))
                    trim_threshold = max(1, int(qty * ACTION_THRESHOLD_PCT / 100.0))

                    if adj > add_threshold:
                        action_display = f"[bold green]+{adj_pct:.1f}%[/]"
                    elif adj < -trim_threshold:
                        action_display = f"[bold red]{adj_pct:.1f}%[/]"
                        # Add WARNING icon only if the trimming threshold is breached
                        ticker_display += " [bold red]⚠[/]"

            cur_p_display = f"{cur_p_val:,.2f}"
            if has_risk and pd.notnull(sl_p) and cur_p_val <= sl_p:
                cur_p_display = f"[on red][bold white] {cur_p_display} [/][/]"
            else:
                if has_risk and pd.notnull(tp_p) and cur_p_val >= tp_p:
                    ticker_display += " [bold cyan]★[/]"
                r_val = f"{row['risk_pct_nav']:.1f}% ({max_r_pct:.1f}%)"
            nav_val = f"{row['NavPct']:.1f}% ({max_exp_pct:.1f}%)"
            r_color = "red" if row['risk_pct_nav'] > (max_r_pct * RISK_RED_MULTIPLIER) else ("yellow" if row['risk_pct_nav'] > max_r_pct else "white")
            exp_color = "red" if row['NavPct'] > (max_exp_pct * EXPOSURE_RED_MULTIPLIER) else ("yellow" if row['NavPct'] > max_exp_pct else "white")
            
            pl_display = UIUtils.color_fmt(row['Risk_Val']) if has_risk else "---"
            mkt_val  = row['MarketValue']
            cost_val = row['CostBasis']
            mkt_color   = "green" if mkt_val >= cost_val else "red"
            mkt_display  = f"[{mkt_color}]{mkt_val:,.0f}[/]" if row['Qty'] > 0 else "---"
            cost_display = f"{cost_val:,.0f}" if cost_val > 0 else "---"
            rr_val = row['RR_Ratio']
            rr_display = f"{rr_val:.2f}" if has_risk else "---"
            rr_color = "green" if rr_val > 3.0 else ("yellow" if rr_val > 1.0 else "red")
            
            # ATR column: for FIXED, show entry→stop distance; for TRAILING show ATR value
            if has_risk:
                if row['StopType'] == 'FIXED' and row['Entry'] > 0 and pd.notnull(row['SL_Price']):
                    atr_display = f"{(row['Entry'] - row['SL_Price']):.2f}"
                else:
                    atr_display = f"{row['ATR']:.2f}"
            else:
                atr_display = "---"

            table.add_row(
                ticker_display,
                action_display,
                f"{(row['MaxSinceEntry'] if row['StopType'] == 'TRAILING' else row['Entry']):,.2f}",
                atr_display,
                f"{row['SL_Price']:,.2f}" if has_risk else "---",
                f"{row['sl_pct_base']:.1f}%" if has_risk else "---",
                pl_display,
                mkt_display,
                cost_display,
                cur_p_display,
                f"{row['Entry']:,.2f}" if row['Entry'] > 0 else "---",
                f"[{exp_color}]{nav_val}[/]", 
                f"[{r_color}]{r_val}[/]", 
                f"[{rr_color}]{rr_display}[/]",
                key=conid_str
            )

    @on(DataTable.RowHighlighted, "#portfolio-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        conid = event.row_key.value
        self.current_conid = conid
        try:
            self.query_one("#discover-input", Input).value = ""
        except Exception:
            pass
        self.refresh_risk_checklist() 
        if conid in self.discovery_cache:
            self.update_discovery_ui(conid, self.discovery_cache[conid])
        else:
            self.query_one("#fixed-stop-table", DataTable).clear()
            self.query_one("#trailing-stop-table", DataTable).clear()
            self.fetch_atr_data(conid)

    def refresh_risk_checklist(self, hypo_stop: Optional[float] = None, hypo_atr: Optional[float] = None, hypo_max_r: Optional[float] = None, hypo_max_exp: Optional[float] = None, hypo_qty: Optional[float] = None, hypo_entry: Optional[float] = None) -> None:
        if not self.current_conid:
            return
        pos = next((p for p in self.positions if str(p.conid) == self.current_conid), None)
        if not pos:
            return
        
        # Prospect Price Recovery: Phantom positions have 0.0 price until cache is checked
        disc = self.discovery_cache.get(self.current_conid)
        cur_p = hypo_entry if hypo_entry is not None else (pos.current_price or pos.mark_price)
        if cur_p == 0 and disc:
            cur_p = disc.get('current_price', 0.0)

        active_max_r = hypo_max_r if hypo_max_r is not None else pos.max_r_pct
        active_max_exp = hypo_max_exp if hypo_max_exp is not None else pos.max_exp_pct
        active_qty = hypo_qty if hypo_qty is not None else pos.qty
        active_entry = hypo_entry if hypo_entry is not None else (pos.entry_price if pos.entry_price > 0 else cur_p)
        stop_p = hypo_stop if hypo_stop is not None else pos.sl_price
        
        audit_content = "[dim]Enter ATR/Stop in Lab to calculate risk...[/]"
        integ_content = "---"
        pilot_content = ""
        
        is_modeling = self.current_conid in self.drafts
        
        # Determine effective stop for audit logic (Default to entry if none set)
        effective_stop = stop_p if pd.notnull(stop_p) else active_entry
        
        if pd.notnull(effective_stop) and cur_p > 0:
            is_safe = cur_p > effective_stop
            buffer = ((cur_p - effective_stop) / cur_p * 100) if cur_p > 0 else 0
            integ_content = f"[bold {'green' if is_safe else 'red'}]Price {' > ' if is_safe else ' <= '} Stop[/] | {'[SAFE]' if is_safe else '[BREACHED]'} [dim]({buffer:.1f}% Buffer)[/]"
            res = audit_position_risk(cur_p, effective_stop, active_entry, active_qty, pos.multiplier, self.total_nav, max_r_pct=active_max_r, max_exp_pct=active_max_exp, fx_rate=pos.fx_rate)
            
            # For FIXED stop: pos.atr holds the stop price, not an ATR distance.
            # Resolve a proper ATR from inception_atr or discovery for efficiency/pilot calcs.
            if pos.stop_type == 'FIXED' and hypo_atr is None:
                disc_atr = next((r.atr_wilder for r in disc['rows'] if r.label == '14d'), None) if (disc and disc.get('rows')) else None
                effective_atr = disc_atr or (pos.inception_atr if (pos.inception_atr and pos.inception_atr > 0) else max(0.0, (active_entry or 0) - (stop_p or active_entry or 0)))
            else:
                effective_atr = hypo_atr if hypo_atr is not None else pos.atr

            atr_width = effective_atr
            efficiency = ((effective_stop + (3 * atr_width) - cur_p) / (cur_p - effective_stop) if cur_p > effective_stop else 0)

            # 2. Build Execution Plan
            exit_stage = getattr(pos, 'exit_stage', '')
            if res['is_breached']:
                exec_plan = "[bold red]STOP BREACHED. EXIT FULL POSITION NOW.[/]"
                target_qty = 0
            else:
                room = int(res['adjustment'])
                target_qty = int(pos.qty + room)
                if room > 0 and exit_stage in ('M1', 'M2', 'TP'):
                    # Sizing has headroom but position is in profit-taking — adding is wrong
                    exec_plan = f"  - [bold yellow]EXIT STAGE ACTIVE ({exit_stage}): Hold or trim — no new entries.[/]"
                    target_qty = int(pos.qty)
                elif room > 0:
                    exec_plan = f"  - [bold reverse green] ADD +{room} SHARES [/] @ {cur_p:,.2f} (To reach {target_qty} sh)"
                elif room < 0:
                    exec_plan = f"  - [bold reverse yellow] TRIM {abs(room)} SHARES [/] @ {cur_p:,.2f} (Limit: {active_max_exp}% Exp)"
                else:
                    exec_plan = "  - [bold white]MAX SIZE REACHED.[/] (No adjustment needed)"

            # 3. Final Layout Assembly
            cost_val = (pos.qty * active_entry * pos.multiplier)
            market_val = (pos.qty * cur_p * pos.multiplier)

            # HCM Exposure: Use higher of cost or market for capital budgeting
            hcm_exposure = max(cost_val, market_val)

            # Sizing Impact Table — post-action projection
            net_action = int(target_qty) - int(active_qty)
            if active_qty > 0 and self.total_nav > 0 and net_action != 0:
                if net_action > 0:
                    new_qty_t   = active_qty + net_action
                    new_entry_t = (active_entry * active_qty + cur_p * net_action) / new_qty_t
                else:
                    new_qty_t   = max(0.0, active_qty + net_action)
                    new_entry_t = active_entry if new_qty_t > 0 else 0.0
                new_cost_t = new_qty_t * new_entry_t * pos.multiplier
                new_mkt_t  = new_qty_t * cur_p * pos.multiplier
                new_hcm_t  = max(new_cost_t, new_mkt_t)
                new_R_t    = (new_entry_t - effective_stop) * new_qty_t * pos.multiplier * pos.fx_rate / self.total_nav * 100 if new_qty_t > 0 else 0.0
                new_E_t    = new_hcm_t * pos.fx_rate / self.total_nav * 100
                r_col  = "red" if new_R_t > active_max_r else ("yellow" if new_R_t > active_max_r * 0.8 else "green")
                e_col  = "red" if new_E_t > active_max_exp * 1.1 else ("yellow" if new_E_t >= active_max_exp else "green")
                cur_r  = res['current_risk_pct']
                cur_e  = res['current_exposure_pct']
                # ADD column values: per-transaction contributions (add up exactly to BALANCE)
                r_add  = (cur_p - effective_stop) * net_action * pos.multiplier * pos.fx_rate / self.total_nav * 100
                e_add  = cur_p * net_action * pos.multiplier * pos.fx_rate / self.total_nav * 100
                tx_hcm = net_action * cur_p * pos.multiplier  # pos.ccy, signed
                # HCM basis: mkt=market (winner, +unrealized), cst=cost (loser, -unrealized)
                beg_is_mkt  = market_val >= cost_val
                bal_is_mkt  = new_mkt_t >= new_cost_t
                basis_tag   = "green" if beg_is_mkt else "yellow"
                bal_hcm_col = "green" if bal_is_mkt else "yellow"
                basis_lim   = f"[{basis_tag}]{'mkt' if beg_is_mkt else 'cst':>7}[/]"
                r_lim       = f"{active_max_r:.2f}%"
                e_lim       = f"{active_max_exp:.2f}%"
                stop_flag   = pos.stop_type[:1]
                if pos.stop_type == 'TRAILING':
                    hwm = pos.max_since_entry if pos.max_since_entry > 0 else active_entry
                    sl_pct_beg = effective_atr / hwm * 100 if hwm > 0 else 0.0
                    sl_pct_add = sl_pct_beg   # ATR width is unchanged by the transaction
                    sl_pct_bal = sl_pct_beg
                else:  # FIXED
                    sl_pct_beg = max(0.0, active_entry - effective_stop) / active_entry * 100 if active_entry > 0 else 0.0
                    sl_pct_add = max(0.0, cur_p - effective_stop) / cur_p * 100 if cur_p > 0 else 0.0
                    sl_pct_bal = max(0.0, new_entry_t - effective_stop) / new_entry_t * 100 if new_entry_t > 0 else 0.0
                pl_s_beg    = (effective_stop - active_entry) * active_qty * pos.multiplier
                pl_s_add    = (effective_stop - cur_p) * net_action * pos.multiplier
                pl_s_bal    = (effective_stop - new_entry_t) * new_qty_t * pos.multiplier
                pl_s_beg_c  = "green" if pl_s_beg >= 0 else "red"
                pl_s_add_c  = "green" if pl_s_add >= 0 else "red"
                pl_s_bal_c  = "green" if pl_s_bal >= 0 else "red"
                sizing_table = (
                    f"──────────────────────────────────────────\n"
                    f"[bold]{'':8}{'INFO':>7}{'BAL-BEG':>9}{'ADD':>9}{'BALANCE':>9}[/]\n"
                    f"  {'Shares':<6}{'':>7}{int(active_qty):>9,}{net_action:>+9,}{int(new_qty_t):>9,}\n"
                    f"  {'Price':<6}{'':>7}{active_entry:>9.2f}{cur_p:>9.2f}{new_entry_t:>9.2f}  {pos.ccy}\n"
                    f"  {'Stop':<6}{stop_flag:>7}{effective_stop:>9.2f}{'---':>9}{effective_stop:>9.2f}  {pos.ccy}\n"
                    f"  {'SL%':<6}{'---':>7}{sl_pct_beg:>8.1f}%{sl_pct_add:>8.1f}%{sl_pct_bal:>8.1f}%\n"
                    f"  {'P/L@S':<6}{'---':>7}[{pl_s_beg_c}]{int(pl_s_beg):>+9,}[/][{pl_s_add_c}]{int(pl_s_add):>+9,}[/][{pl_s_bal_c}]{int(pl_s_bal):>+9,}[/]  {pos.ccy}\n"
                    f"  {'HCM':<6}{basis_lim}{hcm_exposure:>9,.0f}{int(tx_hcm):>+9,}[{bal_hcm_col}]{new_hcm_t:>9,.0f}[/]  {pos.ccy}\n"
                    f"  {'R%':<6}{r_lim:>7}{cur_r:>+8.2f}%{r_add:>+8.2f}%[bold {r_col}]{new_R_t:>+8.2f}%[/]\n"
                    f"  {'E%':<6}{e_lim:>7}{cur_e:>8.2f}%{e_add:>+8.2f}%[bold {e_col}]{new_E_t:>8.2f}%[/]\n"
                )
            else:
                sizing_table = ""
                tx_hcm = 0.0

            # Inception Stop Info
            incep_stop_str = f"{pos.inception_stop:,.2f}" if pos.inception_stop else "---"
            trailed_dist = (pos.sl_price - pos.inception_stop) if (pos.inception_stop and pos.sl_price) else 0
            trailed_str = f" [bold green](+{trailed_dist:,.2f} trailed)[/]" if trailed_dist > 0 else ""

            # Inception ATR Info
            incep_atr_str = f"{pos.inception_atr:.2f}" if pos.inception_atr else "---"
            vol_delta_str = ""
            if pos.inception_atr and pos.inception_atr > 0:
                vol_delta = (effective_atr / pos.inception_atr - 1) * 100
                vol_color = "red" if vol_delta > 10 else ("green" if vol_delta < -10 else "white")
                vol_delta_str = f" [bold {vol_color}]({'+' if vol_delta>0 else ''}{vol_delta:.1f}%)[/]"

            # R Compliance Restore — shown whenever risk budget is breached
            remediation_str = ""
            if res.get('stop_to_restore') is not None or res.get('shares_to_trim') is not None:
                remediation_str = "\n--------------------------------------\n[bold red]R COMPLIANCE RESTORE:[/]\n"
                if res.get('stop_to_restore') is not None:
                    remediation_str += f"  A) Raise stop → [bold cyan]{res['stop_to_restore']:,.2f}[/] (keep {int(active_qty)} sh)\n"
                if res.get('shares_to_trim') is not None and res['shares_to_trim'] >= 1:
                    remediation_str += f"  B) Trim [bold yellow]{int(res['shares_to_trim'])}[/] sh (keep stop @ {effective_stop:,.2f})"

            audit_content = (
                f"  - Risk: [bold {'red' if res['current_risk_pct'] > (active_max_r * 1.5) else ('yellow' if res['current_risk_pct'] > active_max_r else 'green')}]{res['current_risk_pct']:.2f}%[/] (Lim: {active_max_r}%)\n"
                f"  - Exp:  [bold {'red' if res['current_exposure_pct'] > (active_max_exp * 1.1) else ('yellow' if res['current_exposure_pct'] >= active_max_exp else 'green')}]{res['current_exposure_pct']:.2f}%[/] (Lim: {active_max_exp}%)\n"
                f"  - Efficiency: [bold {'green' if efficiency>=2.0 else ('yellow' if efficiency>=1.0 else 'red')}]{efficiency:.2f} RR[/]\n"
                f"{sizing_table}"
                f"--------------------------------------\n"
                f"INCEPTION STOP: [bold]{incep_stop_str}[/]{trailed_str}\n"
                f"INCEPTION ATR:  [bold]{incep_atr_str}[/]{vol_delta_str}\n"
                f"{remediation_str}"
                f"--------------------------------------\n"
                f"PLAN:\n"
                f"{exec_plan}\n"
                f"{_exit_guidance_str(pos, cur_p)}"
            )

        incep_str = pos.date_entry.strftime("%Y-%m-%d") if pd.notnull(pos.date_entry) else "Unknown"
        audit_header = f"[bold yellow]{pos.ticker}[/] ({pos.name})\nINCEPTION: [bold cyan]{incep_str}[/]"
        if is_modeling:
            audit_header = "[bold reverse yellow] MODELING STRATEGY [/]\n" + audit_header
            
        audit_text = f"{audit_header}\n--------------------------------------\nINTEGRITY: {integ_content}\n--------------------------------------\n{audit_content}"
        self.query_one("#position-context", Static).update(audit_text)

    @work(exclusive=True, thread=True)
    def fetch_atr_data(self, conid: Optional[str], ticker: Optional[str] = None) -> None:
        if conid and not str(conid).startswith("PROSPECT:"):
            pos = next((p for p in self.positions if str(p.conid) == conid), None)
            if not pos:
                return
            t_sym, entry_p, entry_d, m, q = pos.ticker, pos.entry_price, pos.date_entry.strftime("%Y-%m-%d"), pos.multiplier, pos.qty
            max_r, max_exp = pos.max_r_pct, pos.max_exp_pct
        else:
            t_sym = ticker or str(conid).split(":")[-1]
            entry_p, entry_d, m, q = 0.0, pd.Timestamp.now().strftime("%Y-%m-%d"), 1.0, 0.0
            max_r, max_exp = 1.0, 5.0

        with suppress_console_logging():
            data = get_atr_discovery_data(t_sym, entry_d, entry_p, conid=(conid if conid and not str(conid).startswith("PROSPECT:") else None), qty=q, inst_multiplier=m, total_nav=self.total_nav, max_r_pct=max_r, max_exp_pct=max_exp, mapper=self.pm.mapper)
        if data:
            cache_id = conid or f"PROSPECT:{t_sym}"
            self.discovery_cache[cache_id] = data
            self.post_message(self.DiscoveryDataLoaded(cache_id, data))

    @on(DiscoveryDataLoaded)
    def on_discovery_loaded(self, message: DiscoveryDataLoaded) -> None:
        if message.conid == self.current_conid:
            self.update_discovery_ui(message.conid, message.data)
            self.refresh_risk_checklist()
            if self.query_one("#atr-input", Input).value:
                self.on_strategy_change()

    def update_discovery_ui(self, conid: str, data: dict) -> None:
        # Only update if the loaded data still matches the highlighted row
        if conid != self.current_conid:
            return
            
        table_f = self.query_one("#fixed-stop-table", DataTable)
        table_t = self.query_one("#trailing-stop-table", DataTable)
        table_f.clear()
        table_t.clear()
        
        m_r = data.get('max_r_pct', 1.0)
        
        # Update dynamic labels with base prices
        self.query_one("#fixed-label").update(f"[bold cyan]FIXED STOP | BASE: ENTRY ({data['entry_price']:,.2f})[/]")
        self.query_one("#trailing-label").update(f"[bold magenta]TRAILING STOP | BASE: HIGH ({data['max_price']:,.2f})[/]")

        # Section 1: FIXED STOP
        for r in [r for r in data['rows'] if r.stop_type == "FIXED"]:
            r_c = "red" if r.pl_pct_nav > (m_r * 1.5) else ("yellow" if r.pl_pct_nav > m_r else "white")
            # Calculate SMA SL% relative to Entry
            sma_sl_pct = (r.atr_sma / data['entry_price'] * 100) if data['entry_price'] > 0 else 0
            
            row_vals = (
                r.label, 
                f"{r.atr_wilder:.2f}", f"{r.atr_base_pct:.1f}%", 
                f"{r.atr_sma:.2f}", f"{sma_sl_pct:.1f}%",
                f"{r.stop_price:,.2f}", f"{int(r.qty)}", 
                f"[{'green' if r.pl_at_stop>=0 else 'red'}]{r.pl_at_stop:,.0f}[/]", 
                f"[{r_c}]{r.pl_pct_nav:.1f}%[/]", f"{r.buffer_pct:.1f}%"
            )
            table_f.add_row(*row_vals)

        # Section 2: TRAILING STOP
        for r in [r for r in data['rows'] if r.stop_type == "TRAILING"]:
            r_c = "red" if r.pl_pct_nav > (m_r * 1.5) else ("yellow" if r.pl_pct_nav > m_r else "white")
            # Calculate SMA SL% relative to Max High
            sma_sl_pct = (r.atr_sma / data['max_price'] * 100) if data['max_price'] > 0 else 0
            
            row_vals = (
                r.label, 
                f"{r.atr_wilder:.2f}", f"{r.atr_base_pct:.1f}%", 
                f"{r.atr_sma:.2f}", f"{sma_sl_pct:.1f}%",
                f"{r.stop_price:,.2f}", f"{int(r.qty)}", 
                f"[{'green' if r.pl_at_stop>=0 else 'red'}]{r.pl_at_stop:,.0f}[/]", 
                f"[{r_c}]{r.pl_pct_nav:.1f}%[/]", f"{r.buffer_pct:.1f}%"
            )
            table_t.add_row(*row_vals)

    @on(Input.Submitted, "#discover-input")
    def on_discover_submitted(self) -> None:
        ticker = self.query_one("#discover-input", Input).value.strip().upper()
        if not ticker:
            return
        table = self.query_one("#portfolio-table", DataTable)
        for r_key in table.rows:
            row_data = self.enriched_data[self.enriched_data['conid'].astype(str) == r_key.value] if not self.enriched_data.empty else pd.DataFrame()
            if not row_data.empty and row_data.iloc[0]['Ticker'] == ticker:
                table.move_cursor(row=table.get_row_index(r_key))
                return
        self.notify(f"DISCOVERING: {ticker}...")
        self.current_conid = f"PROSPECT:{ticker}"
        from models import Position
        phantom = Position(name=f"PROSPECT: {ticker}", ticker=ticker, conid=self.current_conid, asset_class='STK', ccy='USD', date_entry=pd.Timestamp.now(), qty=0.0, entry_price=0.0, account_id='WATCHLIST')
        if not any(p.conid == self.current_conid for p in self.positions):
            self.positions.append(phantom)
        if self.current_conid not in [r.value for r in table.rows]:
            table.add_row(f"[PROSPECT] {ticker}", "---", "---", "---", "---", "---", "---", "---", "---", "---", "---", key=self.current_conid)
        table.move_cursor(row=table.get_row_index(self.current_conid))
        self.fetch_atr_data(None, ticker=ticker)

    def action_toggle_help(self) -> None:
        self.push_screen(HelpScreen())

    @on(Input.Submitted, "#atr-input")
    def on_strategy_submitted(self) -> None:
        self.on_strategy_change()
        self.notify("Strategy Modeled.")

    @on(Input.Changed, "#atr-input")
    def on_strategy_change(self) -> None:
        if not self.current_conid:
            return
        raw = self.query_one("#atr-input", Input).value.strip().upper()
        if not raw:
            if self.current_conid in self.drafts:
                del self.drafts[self.current_conid]
            self.query_one("#preset-legend", Label).update(_preset_legend())
            self.refresh_risk_checklist()
            return
        try:
            pos = next((p for p in self.positions if str(p.conid) == self.current_conid), None)
            disc = self.discovery_cache.get(self.current_conid)
            if not pos:
                return
            
            f_atr, s_type, m_r, m_e = pos.atr, pos.stop_type, pos.max_r_pct, pos.max_exp_pct

            active_preset = ""
            p_m = re.search(r"P:([SBL])", raw)
            if p_m:
                preset = PRESETS.get(p_m.group(1))
                if preset:
                    m_r = preset["max_r_pct"]
                    m_e = preset["max_exp_pct"]
                    active_preset = p_m.group(1)
                raw = raw.replace(p_m.group(0), "").strip()

            r_m = re.search(r"R:([0-9\.]+)", raw)
            if r_m:
                m_r = float(r_m.group(1))
                raw = raw.replace(r_m.group(0), "").strip()
            e_m = re.search(r"E:([0-9\.]+)", raw)
            if e_m:
                m_e = float(e_m.group(1))
                raw = raw.replace(e_m.group(0), "").strip()
            
            if 'T' in raw:
                s_type = "TRAILING"
                raw = raw.replace('T', "").strip()
            elif 'F' in raw:
                s_type = "FIXED"
                raw = raw.replace('F', "").strip()
            
            cur_p_d = disc['current_price'] if disc else (pos.current_price or pos.mark_price)
            cached_hwm = disc.get('max_price', 0.0) if disc else 0.0
            hwm = max(pos.entry_price, cur_p_d, pos.mark_price, cached_hwm, pos.max_since_entry)
            base_p = hwm if s_type == 'TRAILING' else pos.entry_price
            if base_p == 0:
                base_p = cur_p_d
            
            val_m = re.search(r"([\$0-9\.%]+)", raw)
            if val_m:
                v = val_m.group(1)
                is_d = v.startswith('$')
                num = float(v[1:] if is_d else (v[:-1] if v.endswith('%') else v))
                if s_type == 'FIXED':
                    f_atr = num  # for FIXED: the value IS the literal stop price
                else:
                    f_atr = num if is_d else base_p * (num / 100.0)

            if s_type == 'FIXED':
                sl_p = f_atr
            else:
                sl_p = base_p - f_atr
            
            # Hypothetical Quantity (Sizing Discovery)
            calc_q = pos.qty
            if calc_q == 0 and self.total_nav > 0:
                dist_sh = abs(base_p - sl_p) * pos.multiplier
                risk_q = (self.total_nav * (m_r / 100.0)) / dist_sh if dist_sh > 0 else float('inf')
                exp_q = (self.total_nav * (m_e / 100.0)) / (cur_p_d * pos.multiplier) if cur_p_d > 0 else 0
                calc_q = int(min(risk_q, exp_q))
            
            hypo_entry = pos.entry_price if pos.entry_price > 0 else base_p
            risk_v = (sl_p - hypo_entry) * calc_q * pos.multiplier
            hypo_r = (abs(base_p - sl_p) * calc_q * pos.multiplier / self.total_nav * 100) if self.total_nav > 0 else 0
            
            # HCM Exposure for Modeling
            modeled_qty = pos.qty if pos.qty > 0 else calc_q
            modeled_hcm_val = max(hypo_entry, cur_p_d) * modeled_qty * pos.multiplier
            modeled_nav_pct = (modeled_hcm_val / self.total_nav * 100) if self.total_nav > 0 else 0

            table = self.query_one("#portfolio-table", DataTable)
            t_pfx = f"[{s_type[:1]}]"
            display_ticker = f"[bold yellow]* {'[PROSPECT]' if str(self.current_conid).startswith('PROSPECT:') else t_pfx} {pos.ticker}"
            if hypo_r > m_r or modeled_nav_pct > m_e:
                display_ticker += " [bold red]⚠[/]"

            table.update_cell(self.current_conid, "col_ticker", display_ticker)
            # For FIXED: base is entry, col_atr shows implicit distance (entry - stop price)
            if s_type == 'FIXED':
                display_base = hypo_entry
                display_dist = hypo_entry - sl_p
                pct_ref = hypo_entry
            else:
                display_base = base_p
                display_dist = f_atr
                pct_ref = base_p

            table.update_cell(self.current_conid, "col_base", f"{display_base:,.2f}")
            table.update_cell(self.current_conid, "col_atr", f"{display_dist:.2f}")
            table.update_cell(self.current_conid, "col_stop_p", f"{sl_p:,.2f}")
            table.update_cell(self.current_conid, "col_sl_pct", f"{(display_dist / pct_ref * 100 if pct_ref > 0 else 0):.1f}%")
            table.update_cell(self.current_conid, "col_pl_stop", f"[{'green' if risk_v >= 0 else 'red'}]{risk_v:,.0f}[/]")
            table.update_cell(self.current_conid, "col_cur_p", f"{cur_p_d:,.2f}")
            table.update_cell(self.current_conid, "col_avg_cost", f"{hypo_entry:,.2f}")
            table.update_cell(self.current_conid, "col_nav_pct", f"{modeled_nav_pct:.1f}% ({m_e:.1f}%)")
            table.update_cell(self.current_conid, "col_r", f"[{'red' if hypo_r>(m_r*1.5) else 'yellow' if hypo_r>m_r else 'white'}]{hypo_r:.1f}% ({m_r:.1f}%) [/]")
            
            # For FIXED: f_atr is the stop price; get the real ATR from discovery for inception_atr
            if s_type == 'FIXED':
                save_incep_atr = next((r.atr_wilder for r in disc['rows'] if r.label == '14d'), None) if (disc and disc.get('rows')) else pos.inception_atr
            else:
                save_incep_atr = f_atr

            self.drafts[self.current_conid] = {'atr': f_atr, 'type': s_type, 'ticker': pos.ticker, 'max_r_pct': m_r, 'max_exp_pct': m_e, 'hypo_stop': sl_p, 'inception_atr': save_incep_atr, 'profile': active_preset if active_preset else None}
            self.query_one("#preset-legend", Label).update(_preset_legend(active_preset))
            self.refresh_risk_checklist(sl_p, f_atr, m_r, m_e, hypo_qty=calc_q, hypo_entry=hypo_entry)
            
        except Exception as e:
            logger.error(f"Modeling Error: {e}")

    def on_key(self, event) -> None:
        if event.key == "ctrl+j":
            if self.current_conid in self.drafts:
                d = self.drafts[self.current_conid]
                set_position_risk(self.current_conid, d['ticker'], d['atr'], d['type'], entry_type='SINGLE', scale_step=0.5, status=('WATCH' if str(self.current_conid).startswith("PROSPECT:") else 'ACTIVE'), max_r_pct=d.get('max_r_pct', 1.0), max_exp_pct=d.get('max_exp_pct', 5.0), reset_sl=True, inception_stop=d.get('hypo_stop'), inception_atr=d.get('inception_atr'), profile=d.get('profile'))
                self.notify(f"COMMITTED: {d['ticker']}")
                self.query_one("#atr-input", Input).value = ""
                self.query_one("#discover-input", Input).value = ""
                self.load_portfolio()
                self.query_one("#portfolio-table").focus()

    def action_show_chart(self) -> None:
        if not self.current_conid:
            return
        pos = next((p for p in self.positions if str(p.conid) == self.current_conid), None)
        if not pos:
            return
        yf_ticker = self.pm.mapper.resolve_yf_ticker(pos.ticker, conid=pos.conid)
        launch_price_chart(pos.ticker, conid=self.current_conid, yf_ticker=yf_ticker)

    def action_save_all(self) -> None:
        if not self.drafts:
            return
        for cid, d in self.drafts.items():
            set_position_risk(cid, d['ticker'], d['atr'], d['type'], entry_type='SINGLE', scale_step=0.5, status=('WATCH' if str(cid).startswith("PROSPECT:") else 'ACTIVE'), max_r_pct=d.get('max_r_pct', 1.0), max_exp_pct=d.get('max_exp_pct', 5.0), reset_sl=True, inception_stop=d.get('hypo_stop'), inception_atr=d.get('inception_atr'), profile=d.get('profile'))
        self.notify(f"SUCCESS: Saved {len(self.drafts)} strategies.")
        self.drafts.clear()
        self.load_portfolio()
        self.query_one("#atr-input", Input).value = ""

    def action_refresh(self) -> None:
        self.discovery_cache.clear()
        self.load_portfolio()

    def action_open_matrix(self) -> None:
        def on_closed(changed_keys):
            if changed_keys:
                self.query_one("#preset-legend", Label).update(_preset_legend())
                self.load_portfolio()
                self.notify(f"Presets updated: {', '.join(changed_keys)}")
        self.push_screen(PresetMatrixScreen(), on_closed)

def run_risk_workspace():
    RiskWorkspace().run()

if __name__ == "__main__":
    run_risk_workspace()
