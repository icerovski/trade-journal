import pandas as pd
import re
from typing import Dict, Optional
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Label, Input, TabbedContent, TabPane
from textual.containers import Horizontal, Vertical, Container
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual import on, work

from core.portfolio_manager import PortfolioManager
from core.risk_engine import get_atr_discovery_data, RiskEngine
from db import set_position_risk
from logger import logger

# =============================================================================
# 1. HELP OVERLAY (The "F1" Pop-up)
# =============================================================================
class HelpScreen(ModalScreen):
    """An overlay screen providing definitions and shortcuts."""
    BINDINGS = [Binding("escape,f1", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        try:
            with open("docs/TECHNICAL_DOCS.md", "r", encoding="utf-8") as f:
                tech_docs = f.read()
        except Exception:
            tech_docs = "Documentation file not found."

        with Vertical(id="help-modal"):
            yield Label("HELP DESK & GLOSSARY", classes="panel-header")
            with TabbedContent(initial="tab-visuals"):
                with TabPane("Visual Glossary", id="tab-visuals"):
                    yield Static(
                        "[bold cyan]TABLE ICONS[/]\n"
                        "• [b][T/F/-][/]: Stop type (Trailing, Fixed, None)\n"
                        "• [b]\\[/S][/]: Scale-In Strategy is active\n"
                        "• [b][bold yellow]*[/][/]: Unsaved draft in the Sandbox\n\n"
                        "[bold cyan]ACTION TRIGGERS[/]\n"
                        "• [b][on red] Price [/][/]: [bold red]EMERGENCY.[/] Stop breached. Exit position.\n"
                        "• [b][bold cyan]★[/][/]: [bold cyan]TAKE PROFIT HIT.[/] Price reached 3x ATR target.\n"
                        "• [b][bold green]⬆[/][/]: [bold green]SCALE-IN TRIGGERED.[/] Add shares to reach next stage.\n\n"
                        "[bold cyan]COLOR METRICS[/]\n"
                        "• [b]Risk (% NAV):[/] [green]< Max R[/] | [yellow]Max R - 1.5x Max R[/] | [red]> 1.5x Max R[/]\n"
                        "• [b]RR (Efficiency):[/] [green]> 3.0[/] | [yellow]1.0 - 3.0[/] | [red]< 1.0[/]\n"
                    )
                with TabPane("Metrics & Audit", id="tab-metrics"):
                    yield Static(
                        "[bold cyan]RISK DEFINITIONS[/]\n"
                        "• [b]Stop Base:[/] Reference point (Avg Cost for Fixed | Max High for Trailing).\n"
                        "• [b]Stop P:[/] The absolute exit price (Base - ATR).\n"
                        "• [b]SL %:[/] Percentage decrease from BASE needed to hit stop.\n"
                        "• [b]R (% NAV):[/] Risk at Stop. Total potential loss as a % of your portfolio.\n"
                        "• [b]RR (Efficiency):[/] Reward-to-Risk Ratio. (TP - Price) / (Price - Stop).\n\n"
                        "[bold cyan]DUAL-CONSTRAINT AUDIT[/]\n"
                        "• [b]Risk Limit (Default 1.0%):[/] Potential Loss from Entry to Stop.\n"
                        "• [b]Exposure Limit (Default 5.0%):[/] Total Position Value limit.\n"
                    )
                with TabPane("Strategy Lab", id="tab-syntax"):
                    yield Static(
                        "Format: [bold cyan]VALUE [F/T] [S] [Step] [R:MaxR] [E:MaxExp][/]\n\n"
                        "• [b]VALUE:[/] Width of your stop. Numbers are treated as % by default (e.g., '15' = 15%).\n"
                        "• [b][F/T]:[/] Stop Type. 'F' = Fixed. 'T' = Trailing.\n"
                        "• [b][S]:[/] (Optional) Scale-In Flag. Activates the 3-Stage Pilot roadmap.\n"
                        "• [b][Step]:[/] (Optional) Scale-In Multiplier (e.g., 0.5 or 1.0).\n"
                        "• [b][R:MaxR]:[/] (Optional) Custom Risk Limit (e.g., 'R:0.5').\n"
                        "• [b][E:MaxExp]:[/] (Optional) Custom Exposure Limit (e.g., 'E:10.0').\n\n"
                        "[bold yellow]PARTIAL UPDATES[/]\n"
                        "You can update metrics individually (e.g., type 'R:0.5' to only change the risk limit).\n\n"
                        "[bold yellow]CONTROLS[/]\n"
                        "• [bold]ENTER:[/] Model hypothetically in the Lab and Grid.\n"
                        "• [bold]CTRL+ENTER:[/] Save permanently to Database.\n"
                    )
                with TabPane("Technical Documentation", id="tab-tech"):
                    yield Static(tech_docs)
            yield Label("Press ESC or F1 to Close", id="close-hint")

# =============================================================================
# 2. MAIN WORKSPACE APPLICATION
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
    #discovery-layout { layout: vertical; height: 1fr; }
    .discovery-sub-pane { height: 1fr; border-bottom: solid $secondary; padding: 0 1; }
    .base-price-label { background: $surface-lighten-1; color: $accent; text-align: center; text-style: bold; height: 1; }
    .panel-header { text-style: bold; color: $accent; text-align: center; background: $surface-darken-1; height: 1; }
    #position-context { background: $surface-darken-2; border: solid $secondary; padding: 1 2; margin-bottom: 1; height: auto; color: $text; }
    #strategy-lab { border-top: solid $secondary; background: $surface-lighten-1; height: 6; padding: 0 1; }
    #lab-inputs { height: 3; margin-top: 0; }
    #discover-input { width: 1fr; }
    #atr-input { width: 2fr; }
    #help-modal { background: $surface-darken-3; border: tall $accent; width: 80%; height: 80%; padding: 1 2; align: center middle; margin: 5 10; }
    #close-hint { text-align: center; color: $text-muted; margin-top: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Back"),
        Binding("s", "save_all", "Save All"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "toggle_help", "Help"),
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-layout"):
            with Vertical(id="left-pane"):
                yield Label("PORTFOLIO RISK STATUS", classes="panel-header")
                yield DataTable(id="portfolio-table")
                with Vertical(id="strategy-lab"):
                    yield Label("RISK STRATEGY & TICKER DISCOVERY", classes="panel-header")
                    with Horizontal(id="lab-inputs"):
                        yield Input(placeholder="Discover Ticker (e.g. NVDA)", id="discover-input")
                        yield Input(placeholder="[SL %] [F/T] [S] [Step] [R:MaxR] [E:MaxExp] (Enter: Model | Ctrl+Enter: Save)", id="atr-input")
            with Vertical(id="right-pane"):
                yield Label("ASSET CONTEXT & RISK AUDIT", classes="panel-header")
                yield Static("Select a position...", id="position-context")
                with Container(id="discovery-layout"):
                    with Vertical(id="fixed-pane", classes="discovery-sub-pane"):
                        yield Label("FIXED STOP (Protection)", classes="panel-header")
                        yield Label("Base: ---", id="fixed-base", classes="base-price-label")
                        dt_fixed = DataTable(id="fixed-table")
                        dt_fixed.can_focus = False
                        yield dt_fixed
                    with Vertical(id="trailing-pane", classes="discovery-sub-pane"):
                        yield Label("TRAILING STOP (Profit Harvest)", classes="panel-header")
                        yield Label("Base: ---", id="trailing-base", classes="base-price-label")
                        dt_trail = DataTable(id="trailing-table")
                        dt_trail.can_focus = False
                        yield dt_trail
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#portfolio-table")
        table.cursor_type = "row"
        table.add_column("TICKER", key="col_ticker")
        table.add_column("STOP BASE", key="col_base")
        table.add_column("ATR", key="col_atr")
        table.add_column("STOP P", key="col_stop_p")
        table.add_column("SL %", key="col_sl_pct")
        table.add_column("P/L STOP", key="col_pl_stop")
        table.add_column("CUR P", key="col_cur_p")
        table.add_column("% NAV", key="col_nav_pct")
        table.add_column("R", key="col_r")
        table.add_column("RR", key="col_rr")
        for table_id in ["#fixed-table", "#trailing-table"]:
            dt = self.query_one(table_id)
            dt.add_columns("WIN", "ATR (SMA)", "STOP", "SL% (SMA)", "P/L", "R", "BUF%")
        self.load_portfolio()

    def load_portfolio(self) -> None:
        """Syncs Ledger and calculates metrics, including Stop-Breach signals."""
        nav_res = self.pm.fetch_nav_data()
        self.total_nav = nav_res[0] if nav_res else 0.0
        self.enriched_data, self.positions = self.pm.get_dashboard_df(total_nav=self.total_nav, silent=True)
        if self.enriched_data.empty:
            return
        table = self.query_one("#portfolio-table")
        table.clear()
        for _, row in self.enriched_data.sort_values("Ticker").iterrows():
            conid_str = str(row['conid'])
            has_risk = pd.notnull(row['ATR']) and row['ATR'] > 0
            max_r_pct = row.get('MaxRPct', 1.0)
            max_exp_pct = row.get('MaxExpPct', 5.0)
            ticker_display = f"[{row['StopType'][:1]}{'/S' if row.get('EntryType') == 'SCALE_IN' else ''}] {row['Ticker']}"
            if conid_str in self.drafts:
                d = self.drafts[conid_str]
                ticker_display = f"[bold yellow]* [{d['type'][:1]}{'/S' if d['entry_type'] == 'SCALE_IN' else ''}] {row['Ticker']}"
                max_r_pct = d.get('max_r_pct', max_r_pct)
                max_exp_pct = d.get('max_exp_pct', max_exp_pct)
            cur_p_val = row['Price']
            sl_p = row['SL_Price']
            tp_p = row.get('TP_Price')
            cur_p_display = f"{cur_p_val:,.2f}"
            if has_risk and pd.notnull(sl_p) and cur_p_val <= sl_p:
                cur_p_display = f"[on red][bold white] {cur_p_display} [/][/]"
            else:
                if has_risk and pd.notnull(tp_p) and cur_p_val >= tp_p:
                    ticker_display += " [bold cyan]★[/]"
                if has_risk and row.get('EntryType') == 'SCALE_IN':
                    incep = row.get('Inception', row['Entry'])
                    pilot = RiskEngine.calculate_pilot_entry(cur_p_val, row['ATR'], self.total_nav, row.get('Multiplier', 1.0), incep, row['ATR'], row.get('ScaleStep', 0.5), max_r_pct=max_r_pct, max_exp_pct=max_exp_pct)
                    if row['Qty'] < pilot['full_target_qty'] * 0.95:
                        if (row['Qty'] <= pilot['full_target_qty'] * 0.4 and cur_p_val >= pilot['stage2_price']) or (row['Qty'] <= pilot['full_target_qty'] * 0.75 and cur_p_val >= pilot['stage3_price']):
                            ticker_display += " [bold green]⬆[/]"
            
            r_val = f"{row['risk_pct_nav']:.1f}% ({max_r_pct:.1f}%)"
            nav_val = f"{row['NavPct']:.1f}% ({max_exp_pct:.1f}%)"
            r_color = "red" if row['risk_pct_nav'] > (max_r_pct * 1.5) else ("yellow" if row['risk_pct_nav'] > max_r_pct else "white")
            exp_color = "red" if row['NavPct'] > (max_exp_pct * 1.1) else ("yellow" if row['NavPct'] > max_exp_pct else "white")
            pl_color = "green" if row['Risk_Val'] >= 0 else "red"
            pl_display = f"[{pl_color}]{row['Risk_Val']:,.0f}[/]" if has_risk else "---"
            rr_val = row['RR_Ratio']
            rr_display = f"{rr_val:.2f}" if has_risk else "---"
            rr_color = "green" if rr_val > 3.0 else ("yellow" if rr_val > 1.0 else "red")
            
            table.add_row(ticker_display, f"{(row['MaxSinceEntry'] if row['StopType'] == 'TRAILING' else row['Entry']):,.2f}", f"{row['ATR']:.2f}" if has_risk else "---", f"{row['SL_Price']:,.2f}" if has_risk else "---", f"{row['sl_pct_base']:.1f}%" if has_risk else "---", pl_display, cur_p_display, f"[{exp_color}]{nav_val}[/]", f"[{r_color}]{r_val}[/]", f"[{rr_color}]{rr_display}[/]", key=conid_str)

    @on(DataTable.RowHighlighted, "#portfolio-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        conid = event.row_key.value
        self.current_conid = conid
        try:
            self.query_one("#discover-input").value = ""
        except Exception:
            pass
        self.refresh_risk_checklist() 
        if conid in self.discovery_cache:
            self.update_discovery_ui(self.discovery_cache[conid])
        else:
            self.query_one("#fixed-table").clear()
            self.query_one("#trailing-table").clear()
            self.fetch_atr_data(conid)

    def refresh_risk_checklist(self, hypo_stop: Optional[float] = None, hypo_atr: Optional[float] = None, hypo_entry_type: Optional[str] = None, hypo_scale_step: Optional[float] = None, hypo_max_r: Optional[float] = None, hypo_max_exp: Optional[float] = None) -> None:
        if not self.current_conid:
            return
        pos = next((p for p in self.positions if str(p.conid) == self.current_conid), None)
        if not pos:
            return
        
        active_max_r = hypo_max_r if hypo_max_r is not None else pos.max_r_pct
        active_max_exp = hypo_max_exp if hypo_max_exp is not None else pos.max_exp_pct
        stop_p = hypo_stop if hypo_stop is not None else pos.sl_price
        cur_p = pos.current_price or pos.mark_price
        tp_p = pos.tp_price if hypo_stop is None else (stop_p + (3 * (hypo_atr or pos.atr)))
        
        audit_content = "[dim]Waiting for Strategy...[/]"
        integ_content = "---"
        pilot_content = ""
        if pd.notnull(stop_p):
            is_safe = cur_p > stop_p
            buffer = ((cur_p - stop_p) / cur_p * 100) if cur_p > 0 else 0
            integ_content = f"[bold {'green' if is_safe else 'red'}]Price {' > ' if is_safe else ' <= '} Stop[/] | {'[SAFE]' if is_safe else '[BREACHED]'} [dim]({buffer:.1f}% Buffer)[/]"
            res = RiskEngine.audit_position_risk(cur_p, stop_p, pos.entry_price, pos.qty, pos.multiplier, self.total_nav, max_r_pct=active_max_r, max_exp_pct=active_max_exp)
            
            rr_val = (tp_p - cur_p) / (cur_p - stop_p) if (tp_p and cur_p > stop_p) else 0.0
            audit_content = f"STATUS: [bold {res['status_color'].lower()}]{res['status_color']}[/]\n  - Risk: [bold {'red' if res['current_risk_pct'] > (active_max_r * 1.5) else ('yellow' if res['current_risk_pct'] > active_max_r else 'green')}]{res['current_risk_pct']:.2f}%[/] (Lim: {active_max_r}%)\n  - Exp:  [bold {'red' if res['current_exposure_pct'] > (active_max_exp * 1.1) else ('yellow' if res['current_exposure_pct'] >= active_max_exp else 'green')}]{res['current_exposure_pct']:.2f}%[/] (Lim: {active_max_exp}%)\n  - Efficiency: [bold {'green' if rr_val > 3.0 else 'white' if not tp_p else 'red'}]{rr_val:.2f} RR[/]\n  - Action: {('[bold red]STOP BREACHED. EXIT POSITION.[/]' if res['is_breached'] else (f'Room to add [bold]+{int(res['adjustment'])}[/] shares' if res['adjustment'] > 0 else (f'Trim by [bold]{int(abs(res['adjustment']))}[/] shares' if res['adjustment'] < 0 else '[bold]Max limit reached[/]')))}"
            
            atr_v = hypo_atr if hypo_atr is not None else pos.atr
            if atr_v > 0:
                daily_atr = atr_v
                if self.current_conid in self.discovery_cache and self.discovery_cache[self.current_conid]['rows']:
                    daily_atr = next((r.atr_wilder for r in self.discovery_cache[self.current_conid]['rows'] if r.label == '14d'), atr_v)
                
                pilot = RiskEngine.calculate_pilot_entry(cur_p, atr_v, self.total_nav, pos.multiplier, pos.entry_price, daily_atr, (hypo_scale_step or pos.scale_step), max_r_pct=active_max_r, max_exp_pct=active_max_exp)
                entry_t = (hypo_entry_type or pos.entry_type)
                if entry_t == 'SCALE_IN':
                    s2_add = max(0, int(pilot['full_target_qty'] * 2/3) - int(pos.qty))
                    s3_add = max(0, int(pilot['full_target_qty']) - (int(pos.qty) + s2_add))
                    roadmap_content = f"  - Current:   {int(pos.qty)} sh (@ {pos.entry_price:,.2f})\n  - [dim green]{'✓' if s2_add<=0 else ' '} Stage 2 @:  {pilot['stage2_price']:,.2f}[/] {'(Add +'+str(s2_add)+' sh)' if s2_add>0 else '(Filled)'}\n  - [dim green]{'✓' if s3_add<=0 else ' '} Stage 3 @:  {pilot['stage3_price']:,.2f}[/] {'(Add +'+str(s3_add)+' sh)' if s3_add>0 else '(Filled)'}\n  - [cyan]Target Outlay: {pilot['scale_in_outlay']:,.0f} {pos.ccy}[/]\n  - [yellow]Remaining Cap: {max(0, pilot['scale_in_outlay'] - (pos.qty * pos.entry_price * pos.multiplier)):,.0f} {pos.ccy}[/]"
                else:
                    roadmap_content = f"  - Current:   {int(pos.qty)} sh (@ {pos.entry_price:,.2f})\n  - Target:    {pilot['full_target_qty']} sh ({active_max_exp}% Exp Limit)\n  - [cyan]Target Outlay: {pilot['single_outlay']:,.0f} {pos.ccy}[/]\n  - [yellow]Remaining Cap: {max(0, (pilot['full_target_qty'] - pos.qty) * cur_p * pos.multiplier):,.0f} {pos.ccy}[/]"
                
                pilot_content = f"--------------------------------------\nPOSITION ROADMAP:{' [bold yellow](STAGE ACTIVE)[/]' if entry_t=='SCALE_IN' else ''}\n{roadmap_content}\n  - Pilot Stop: [bold]{pilot['stop']:,.2f}[/] (assigned ATR)\n  - Scale Step: [bold]{(hypo_scale_step or pos.scale_step)}x ATR[/]"
        
        incep_str = pos.date_entry.strftime("%Y-%m-%d") if pd.notnull(pos.date_entry) else "Unknown"
        audit_text = f"[bold yellow]{pos.ticker}[/] ({pos.name})\nINCEPTION: [bold cyan]{incep_str}[/]\n--------------------------------------\nINTEGRITY: {integ_content}\n--------------------------------------\nDUAL-AUDIT:\n{audit_content}{pilot_content}"
        self.query_one("#position-context").update(audit_text)

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
        
        data = get_atr_discovery_data(t_sym, entry_d, entry_p, conid=(conid if conid and not str(conid).startswith("PROSPECT:") else None), qty=q, inst_multiplier=m, total_nav=self.total_nav, max_r_pct=max_r, max_exp_pct=max_exp)
        if data:
            cache_id = conid or f"PROSPECT:{t_sym}"
            self.discovery_cache[cache_id] = data
            self.post_message(self.DiscoveryDataLoaded(cache_id, data))

    @on(DiscoveryDataLoaded)
    def on_discovery_loaded(self, message: DiscoveryDataLoaded) -> None:
        if message.conid == self.current_conid:
            self.update_discovery_ui(message.data)
            self.refresh_risk_checklist()
            if self.query_one("#atr-input").value:
                self.on_strategy_change()

    def update_discovery_ui(self, data: dict) -> None:
        self.query_one("#fixed-base").update(f"Base: {data['entry_price']:,.2f}")
        self.query_one("#trailing-base").update(f"Base: {data['max_price']:,.2f}")
        f_t, t_t = self.query_one("#fixed-table"), self.query_one("#trailing-table")
        f_t.clear()
        t_t.clear()
        for r in data['rows']:
            m_r = data.get('max_r_pct', 1.0)
            r_c = "red" if r.pl_pct_nav > (m_r * 1.5) else ("yellow" if r.pl_pct_nav > m_r else "white")
            row_vals = (r.label, f"{r.atr_wilder:.2f}", f"{r.stop_price:,.2f}", f"{r.atr_base_pct:.1f}%", f"[{'green' if r.pl_at_stop>=0 else 'red'}]{r.pl_at_stop:,.0f}[/]", f"[{r_c}]{r.pl_pct_nav:.1f}%[/]", f"{r.buffer_pct:.1f}%")
            if r.stop_type == "FIXED":
                f_t.add_row(*row_vals)
            else:
                t_t.add_row(*row_vals)

    @on(Input.Submitted, "#discover-input")
    def on_discover_submitted(self) -> None:
        ticker = self.query_one("#discover-input").value.strip().upper()
        if not ticker:
            return
        table = self.query_one("#portfolio-table")
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
            table.add_row(f"[PROSPECT] {ticker}", "---", "---", "---", "---", "---", "---", "---", "---", "---", key=self.current_conid)
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
        raw = self.query_one("#atr-input").value.strip().upper()
        if not raw:
            self.refresh_risk_checklist()
            return
        try:
            pos = next((p for p in self.positions if str(p.conid) == self.current_conid), None)
            disc = self.discovery_cache.get(self.current_conid)
            if not pos:
                return
            f_atr, s_type, e_type, step, m_r, m_e = pos.atr, pos.stop_type, pos.entry_type, pos.scale_step, pos.max_r_pct, pos.max_exp_pct
            
            r_m = re.search(r"R:([0-9\.]+)", raw)
            if r_m:
                m_r = float(r_m.group(1))
                raw = raw.replace(r_m.group(0), "").strip()
            e_m = re.search(r"E:([0-9\.]+)", raw)
            if e_m:
                m_e = float(e_m.group(1))
                raw = raw.replace(e_m.group(0), "").strip()
            s_m = re.search(r"\bS\s*([0-9\.]*)", raw)
            if s_m:
                e_type = "SCALE_IN"
                step = float(s_m.group(1)) if s_m.group(1) else step
                raw = raw.replace(s_m.group(0), "").strip()
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
                f_atr = num if is_d else base_p * (num / 100.0)
            
            sl_p = base_p - f_atr
            dist_s = (cur_p_d - sl_p)
            calc_q = pos.qty
            if calc_q == 0 and self.total_nav > 0:
                dist_sh = abs(base_p - sl_p) * pos.multiplier
                calc_q = int(min((self.total_nav * (m_r / 100.0)) / dist_sh if dist_sh > 0 else 0, (self.total_nav * (m_e / 100.0)) / (cur_p_d * pos.multiplier) if cur_p_d > 0 else 0))
            
            risk_v = (sl_p - pos.entry_price) * calc_q * pos.multiplier if pos.entry_price > 0 else (sl_p - cur_p_d) * calc_q * pos.multiplier
            hypo_r = (abs(base_p - sl_p) * calc_q * pos.multiplier / self.total_nav * 100) if self.total_nav > 0 else 0
            
            table = self.query_one("#portfolio-table")
            t_pfx = f"[{s_type[:1]}{'/S' if e_type == 'SCALE_IN' else ''}]"
            table.update_cell(self.current_conid, "col_ticker", f"[bold yellow]* {'[PROSPECT]' if str(self.current_conid).startswith('PROSPECT:') else t_pfx} {pos.ticker}")
            table.update_cell(self.current_conid, "col_base", f"{base_p:,.2f}")
            table.update_cell(self.current_conid, "col_atr", f"{f_atr:.2f}")
            table.update_cell(self.current_conid, "col_stop_p", f"{sl_p:,.2f}")
            table.update_cell(self.current_conid, "col_sl_pct", f"{(f_atr/base_p*100 if base_p>0 else 0):.1f}%")
            table.update_cell(self.current_conid, "col_pl_stop", f"[{'green' if risk_v >= 0 else 'red'}]{risk_v:,.0f}[/]")
            table.update_cell(self.current_conid, "col_cur_p", f"{cur_p_d:,.2f}")
            table.update_cell(self.current_conid, "col_nav_pct", f"{( (pos.qty if pos.qty > 0 else calc_q) * cur_p_d * pos.multiplier / self.total_nav * 100):.1f}% ({m_e:.1f}%)")
            table.update_cell(self.current_conid, "col_r", f"[{'red' if hypo_r>(m_r*1.5) else 'yellow' if hypo_r>m_r else 'white'}]{hypo_r:.1f}% ({m_r:.1f}%) [/]")
            self.refresh_risk_checklist(sl_p, f_atr, e_type, step, m_r, m_e)
            self.drafts[self.current_conid] = {'atr': f_atr, 'type': s_type, 'ticker': pos.ticker, 'entry_type': e_type, 'scale_step': step, 'max_r_pct': m_r, 'max_exp_pct': m_e}
        except Exception as e:
            logger.error(f"Modeling Error: {e}")

    def on_key(self, event) -> None:
        if event.key == "ctrl+j":
            if self.current_conid in self.drafts:
                d = self.drafts[self.current_conid]
                set_position_risk(self.current_conid, d['ticker'], d['atr'], d['type'], entry_type=d['entry_type'], scale_step=d.get('scale_step', 0.5), status=('WATCH' if str(self.current_conid).startswith("PROSPECT:") else 'ACTIVE'), max_r_pct=d.get('max_r_pct', 1.0), max_exp_pct=d.get('max_exp_pct', 5.0), reset_sl=True)
                self.notify(f"COMMITTED: {d['ticker']}")
                self.query_one("#atr-input").value = ""
                self.query_one("#discover-input").value = ""
                self.load_portfolio()
                self.query_one("#portfolio-table").focus()

    def action_save_all(self) -> None:
        if not self.drafts:
            return
        for cid, d in self.drafts.items():
            set_position_risk(cid, d['ticker'], d['atr'], d['type'], entry_type=d['entry_type'], scale_step=d.get('scale_step', 0.5), status=('WATCH' if str(cid).startswith("PROSPECT:") else 'ACTIVE'), max_r_pct=d.get('max_r_pct', 1.0), max_exp_pct=d.get('max_exp_pct', 5.0), reset_sl=True)
        self.notify(f"SUCCESS: Saved {len(self.drafts)} strategies.")
        self.drafts.clear()
        self.load_portfolio()
        self.query_one("#atr-input").value = ""

    def action_refresh(self) -> None:
        self.discovery_cache.clear()
        self.load_portfolio()

def run_risk_workspace():
    RiskWorkspace().run()

if __name__ == "__main__":
    run_risk_workspace()
