import pandas as pd
import threading
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
from db import get_all_risk_settings, set_position_risk
from logger import logger

# =============================================================================
# 1. HELP OVERLAY (The "F1" Pop-up)
# =============================================================================
class HelpScreen(ModalScreen):
    """An overlay screen providing definitions and shortcuts."""
    BINDINGS = [Binding("escape,f1", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
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
                        "• [b][bold cyan]★[/][/]: [bold cyan]TAKE PROFIT HIT.[/] Price reached 3x ATR target. Trim/Exit.\n"
                        "• [b][bold green]⬆[/][/]: [bold green]SCALE-IN TRIGGERED.[/] Add shares to reach next stage.\n\n"
                        "[bold cyan]ROADMAP STATUS[/]\n"
                        "• [b][dim green]✓[/][/]: Stage is filled (shares acquired).\n"
                        "• [b][bold yellow]![/][/]: Stage target hit, waiting for you to buy shares.\n\n"
                        "[bold cyan]COLOR METRICS[/]\n"
                        "• [b]Risk (% NAV):[/] [green]< 1.0%[/] | [yellow]1.0% - 1.5%[/] | [red]> 1.5%[/]\n"
                        "• [b]RR (Efficiency):[/] [green]> 3.0[/] | [yellow]1.0 - 3.0[/] | [red]< 1.0[/]\n"
                    )
                with TabPane("Metrics & Audit", id="tab-metrics"):
                    yield Static(
                        "[bold cyan]RISK DEFINITIONS[/]\n"
                        "• [b]Stop Base:[/] Reference point (Avg Cost for Fixed | Max High for Trailing).\n"
                        "• [b]Stop P:[/] The absolute exit price (Base - ATR).\n"
                        "• [b]SL %:[/] Percentage decrease from BASE needed to hit stop.\n"
                        "• [b]R (% NAV):[/] Risk at Stop. Total potential loss as a % of your portfolio.\n"
                        "• [b]RR (Efficiency):[/] Reward-to-Risk Ratio. (Target - Price) / (Price - Stop).\n\n"
                        "[bold cyan]DUAL-CONSTRAINT AUDIT[/]\n"
                        "• [b]Risk Limit (1.0%):[/] Evaluates if Potential Loss from Entry to Stop exceeds 1.0% of NAV.\n"
                        "• [b]Exposure Limit (5.0%):[/] Evaluates if Current Position Value exceeds 5.0% of NAV.\n"
                    )
                with TabPane("Scale-In Guide", id="tab-scale"):
                    yield Static(
                        "[bold cyan]THE PILOT ENTRY STRATEGY[/]\n"
                        "• [b]Stage 1 (Pilot):[/] Entry with 1/3rd Risk (0.33%) and ATR Stop.\n"
                        "• [b]Stage 2 (Confirm):[/] Add 1/3rd when Price moves +0.5 ATR.\n"
                        "• [b]Stage 3 (Full):[/] Add final 1/3rd when Price moves +1.0 ATR. Total risk = 1.0%.\n\n"
                        "[bold cyan]HOW IT WORKS[/]\n"
                        "The system calculates the 'Full Target' size by taking the minimum of the 1% Risk Limit "
                        "and the 5% Exposure Limit. It then breaks that target into 3 tranches.\n\n"
                        "Your original Trade Date anchors the Trailing Stop to ensure High-Water Marks remain accurate.\n"
                    )
                with TabPane("Strategy Lab", id="tab-syntax"):
                    yield Static(
                        "Format: [bold cyan]VALUE [F/T] [S] [Step][/]\n\n"
                        "• [b]VALUE:[/] Width of your stop. Numbers are treated as % by default (e.g., '15' = 15%).\n"
                        "  - To use a dollar amount, prefix with '$' (e.g., '$45.2').\n"
                        "• [b][F/T]:[/] Stop Type. 'F' = Fixed. 'T' = Trailing.\n"
                        "• [b][S]:[/] (Optional) Scale-In Flag. Activates the 3-Stage Pilot roadmap.\n"
                        "• [b][Step]:[/] (Optional) The [bold green]scaling unit[/]. Multiplier applied to the standard 14d ATR.\n"
                        "  - [i]Example:[/] '15 T S 1.0' = 15% stop, add shares every 1.0x daily volatility.\n\n"
                        "[bold yellow]SMART DEFAULTS (If Step is omitted)[/]\n"
                        "• [b]Macro Stops (>15%):[/] Defaults to 0.5x step (fast build-up for long-term trends).\n"
                        "• [b]Micro Stops (<=15%):[/] Defaults to 1.0x step (prevents whipsaws on tactical trades).\n\n"
                        "[bold yellow]CONTROLS[/]\n"
                        "• [bold]ENTER:[/] Model hypothetically in the Lab and Grid.\n"
                        "• [bold]CTRL+ENTER:[/] Save permanently to Database.\n"
                    )
                with TabPane("Conviction Tiers", id="tab-tiers"):
                    yield Static(
                        "[bold cyan]THE ATR DISCOVERY FRAMEWORK[/]\n"
                        "Use the ATR Discovery tool to find the right 'heartbeat' for your position:\n\n"
                        "• [b]14d (Tactical):[/] Market Noise. Use for short-term trades or tight management.\n"
                        "• [b]12w (Quarterly):[/] Earnings Cycle. Captures the rolling quarterly average volatility.\n"
                        "• [b]12m (Annual):[/] Business Cycle. One year of secular trend (Annualized Volatility).\n"
                        "• [b]12q (Macro):[/] Market Cycle. 3-year lookback covering standard PE value creation cycles.\n"
                        "• [b]20q (Strategic):[/] Structural Trend. 5-year 'Strategic Volatility' for core legacy assets.\n\n"
                        "[bold yellow]IMPLEMENTATION GUIDE[/]\n"
                        "Assign wider ATRs (12q/20q) to your [b]Tier 1 High-Conviction Holdings[/b] to ensure you aren't "
                        "shaken out by standard market cycles. Use Tactical (14d) for speculative or momentum plays."
                    )
            yield Label("Press ESC or F1 to Close", id="close-hint")

# =============================================================================
# 2. MAIN WORKSPACE APPLICATION
# =============================================================================
class RiskWorkspace(App):
    """High-Speed Risk Command Center with Risk Audit Checklist."""
    TITLE = "RISK ASSIGNMENT WORKSPACE"
    SUB_TITLE = "Portfolio Audit & Strategy Lab | [F1] Help"
    
    CSS = """
    Screen { background: $surface; }

    /* The Main Split (60/40) */
    #main-layout { layout: horizontal; height: 1fr; }
    #left-pane { width: 60%; height: 1fr; border-right: tall $primary; padding-right: 1; }
    #right-pane { width: 40%; height: 1fr; padding-left: 1; }

    #portfolio-table { height: 1fr; }

    /* Right Pane Modelling Sections */
    #discovery-layout { layout: vertical; height: 1fr; }
    .discovery-sub-pane { height: 1fr; border-bottom: solid $secondary; padding: 0 1; }
    .base-price-label { background: $surface-lighten-1; color: $accent; text-align: center; text-style: bold; height: 1; }
    
    /* Headers & Text Blocks */
    .panel-header { text-style: bold; color: $accent; text-align: center; background: $surface-darken-1; height: 1; }
    #position-context { 
        background: $surface-darken-2; 
        border: solid $secondary; 
        padding: 1 2; 
        margin-bottom: 1; 
        height: auto; 
        color: $text; 
    }

    /* --- THE STRATEGY LAB --- */
    #strategy-lab {
        border-top: solid $secondary;
        background: $surface-lighten-1;
        height: 6;
        padding: 0 1;
    }
    #lab-inputs { height: 3; margin-top: 0; }
    #atr-input { width: 1fr; }

    /* Help Modal Styling */
    #help-modal {
        background: $surface-darken-3;
        border: tall $accent;
        width: 1fr; 
        height: auto;
        padding: 2 4;
        align: center middle;
        margin: 5 10;
    }
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
        self.enriched_data = pd.DataFrame() # Store metrics for Checklist lookup
        self.drafts: Dict[str, Dict] = {} 
        self.current_conid: Optional[str] = None
        self.discovery_cache: Dict[str, dict] = {}
        self.total_nav = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-layout"):
            
            # --- LEFT PANE: Audit & Action ---
            with Vertical(id="left-pane"):
                yield Label("PORTFOLIO RISK STATUS", classes="panel-header")
                yield DataTable(id="portfolio-table")
                
                # The Strategy Lab (Bottom of Left Pane)
                with Vertical(id="strategy-lab"):
                    yield Label("ASSIGN RISK STRATEGY (Sandbox)", classes="panel-header")
                    with Horizontal(id="lab-inputs"):
                        yield Input(placeholder="[SL %] [F/T] [S] [Step: 14d ATR Mult] (Enter: Model | Ctrl+Enter: Save)", id="atr-input")
            
            # --- RIGHT PANE: Discovery Sidebar ---
            with Vertical(id="right-pane"):
                yield Label("ASSET CONTEXT & RISK AUDIT", classes="panel-header")
                yield Static("Select a position...", id="position-context")
                
                with Container(id="discovery-layout"):
                    with Vertical(id="fixed-pane", classes="discovery-sub-pane"):
                        yield Label("FIXED STOP (Protection)", classes="panel-header")
                        yield Label("Base: ---", id="fixed-base", classes="base-price-label")
                        dt_fixed = DataTable(id="fixed-table"); dt_fixed.can_focus = False
                        yield dt_fixed
                    with Vertical(id="trailing-pane", classes="discovery-sub-pane"):
                        yield Label("TRAILING STOP (Profit Harvest)", classes="panel-header")
                        yield Label("Base: ---", id="trailing-base", classes="base-price-label")
                        dt_trail = DataTable(id="trailing-table"); dt_trail.can_focus = False
                        yield dt_trail
        yield Footer()

    def on_mount(self) -> None:
        """Initialize Grid with explicit keys."""
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
        self.positions = self.pm.get_open_positions_hybrid(asset_class_filter='STK')
        
        self.enriched_data = self.pm.get_dashboard_df(asset_class_filter='STK', total_nav=self.total_nav, silent=True)
        if self.enriched_data.empty: return
        
        table = self.query_one("#portfolio-table")
        table.clear()
        for _, row in self.enriched_data.sort_values("Ticker").iterrows():
            conid_str = str(row['conid'])
            has_risk = pd.notnull(row['ATR']) and row['ATR'] > 0
            
            # 1. Ticker Prefix [T/F/-]
            stop_type_char = row['StopType'][:1] if has_risk else "-"
            entry_suffix = "/S" if row.get('EntryType') == 'SCALE_IN' else ""
            ticker_display = f"[{stop_type_char}{entry_suffix}] {row['Ticker']}"
            
            if conid_str in self.drafts:
                d_type = self.drafts[conid_str]['type'][:1]
                d_entry = "/S" if self.drafts[conid_str]['entry_type'] == 'SCALE_IN' else ""
                ticker_display = f"[bold yellow]* [{d_type}{d_entry}] {row['Ticker']}"

            # 2. Breach Signal & Upside Targets
            cur_p_val = row['Price']
            sl_price_val = row['SL_Price']
            tp_price_val = row.get('TP_Price', None)
            cur_p_display = f"{cur_p_val:,.2f}"
            
            if has_risk and pd.notnull(sl_price_val) and cur_p_val <= sl_price_val:
                cur_p_display = f"[on red][bold white] {cur_p_display} [/][/]"
            else:
                upside_hit = False
                # Check Take Profit
                if has_risk and pd.notnull(tp_price_val) and cur_p_val >= tp_price_val:
                    ticker_display += " [bold cyan]★[/]"
                    upside_hit = True
                
                # Check Scale-In Targets if Take Profit wasn't hit
                if not upside_hit and has_risk and row.get('EntryType') == 'SCALE_IN':
                    inception_p = row.get('Inception', row['Entry'])
                    
                    # Get daily ATR for the step logic
                    daily_atr = row['ATR'] # Fallback
                    disc_data = self.discovery_cache.get(conid_str)
                    if disc_data and 'rows' in disc_data and disc_data['rows']:
                        daily_atr = next((r.atr_wilder for r in disc_data['rows'] if r.label == '14d'), row['ATR'])
                    
                    scale_step = row.get('ScaleStep', 0.5)
                    pilot = RiskEngine.calculate_pilot_entry(cur_p_val, row['ATR'], self.total_nav, row.get('Multiplier', 1.0), 
                                                             inception_p, daily_atr, scale_step)
                    current_qty = row['Qty']
                    target_full = pilot['full_target_qty']
                    
                    # Check if we are due for an add
                    if current_qty < target_full:
                        if current_qty <= (target_full * 0.4) and cur_p_val >= pilot['stage2_price']:
                            ticker_display += " [bold green]⬆[/]"
                        elif current_qty <= (target_full * 0.75) and current_qty > (target_full * 0.4) and cur_p_val >= pilot['stage3_price']:
                            ticker_display += " [bold green]⬆[/]"

            # 3. Risk & Exposure Format
            r_val = f"{row['risk_pct_nav']:.1f}%"
            r_color = "red" if row['risk_pct_nav'] > 1.5 else ("yellow" if row['risk_pct_nav'] > 1.0 else "white")
            pl_color = "green" if row['Risk_Val'] >= 0 else "red"
            pl_display = f"[{pl_color}]{row['Risk_Val']:,.0f}[/]" if has_risk else "---"
            
            # 4. RR Format
            rr_val = row['RR_Ratio']
            rr_display = f"{rr_val:.2f}" if has_risk else "---"
            rr_color = "green" if rr_val > 3.0 else ("yellow" if rr_val > 1.0 else "red")

            table.add_row(
                ticker_display,
                f"{(row['MaxSinceEntry'] if row['StopType'] == 'TRAILING' else row['Entry']):,.2f}",
                f"{row['ATR']:.2f}" if has_risk else "---",
                f"{row['SL_Price']:,.2f}" if has_risk else "---",
                f"{row['sl_pct_base']:.1f}%" if has_risk else "---",
                pl_display,
                cur_p_display,
                f"{row['NavPct']:.1f}%",
                f"[{r_color}]{r_val}[/]",
                f"[{rr_color}]{rr_display}[/]",
                key=conid_str
            )

    @on(DataTable.RowHighlighted, "#portfolio-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        conid = event.row_key.value
        self.current_conid = conid
        self.refresh_risk_checklist() # Immediate update of the checklist
        
        if conid in self.discovery_cache:
            self.update_discovery_ui(self.discovery_cache[conid])
        else:
            self.query_one("#fixed-table").clear(); self.query_one("#trailing-table").clear()
            self.fetch_atr_data(conid)

    def refresh_risk_checklist(self, hypo_stop: Optional[float] = None) -> None:
        """Updates the Asset Context with a 2-point Risk Audit Checklist."""
        if not self.current_conid: return
        
        # 1. Get position and current enriched metrics
        pos = next((p for p in self.positions if str(p.conid) == self.current_conid), None)
        if not pos: return
        
        row_metrics = self.enriched_data[self.enriched_data['conid'].astype(str) == self.current_conid]
        if row_metrics.empty: return
        metrics = row_metrics.iloc[0]
        
        # 2. Dual-Constraint Audit (Risk & Exposure)
        stop_p = hypo_stop if hypo_stop is not None else metrics['SL_Price']
        cur_p = metrics['Price']
        tp_p = metrics['TP_Price']
        
        audit_content = "[dim]Waiting for Strategy...[/]"
        integ_content = "---"
        pilot_content = ""
        
        if pd.notnull(stop_p):
            # Integrity Check
            is_safe = cur_p > stop_p
            integ_color = "green" if is_safe else "red"
            integ_status = "[SAFE]" if is_safe else "[BREACHED]"
            buffer = ((cur_p - stop_p) / cur_p * 100) if cur_p > 0 else 0
            integ_content = f"[bold {integ_color}]Price {' > ' if is_safe else ' <= '} Stop[/] | {integ_status} [dim]({buffer:.1f}% Buffer)[/]"

            # Dual-constraint evaluation
            res = RiskEngine.audit_position_risk(cur_p, stop_p, pos.entry_price, pos.qty, pos.multiplier, self.total_nav)
            r_color = res['status_color'].lower()
            
            r_pct = res['current_risk_pct']
            e_pct = res['current_exposure_pct']
            r_budget = res['risk_budget_rem']
            e_budget = res['exposure_budget_rem']
            
            # RR Efficiency
            dist_to_stop = (cur_p - stop_p)
            dist_to_tp = (tp_p - cur_p)
            rr_val = (dist_to_tp / dist_to_stop) if dist_to_stop > 0 else 0
            rr_color = "green" if rr_val > 3.0 else ("yellow" if rr_val > 1.0 else "red")
            
            if res['is_breached']:
                action_text = "[bold red]STOP BREACHED. EXIT POSITION.[/]"
            else:
                # Calculate shares available based on the most restrictive budget
                # For Risk: budget / (entry - stop)
                # For Exposure: budget / current_price
                risk_shares = r_budget / (abs(pos.entry_price - stop_p) * pos.multiplier) if abs(pos.entry_price - stop_p) > 0 else 0
                exp_shares = e_budget / (cur_p * pos.multiplier) if cur_p > 0 else 0
                adj = int(min(risk_shares, exp_shares))
                
                if adj > 0:
                    action_text = f"Room for [bold]+{adj}[/] shares"
                elif adj < 0:
                    action_text = f"Over limit by [bold]{abs(adj)}[/] shares"
                else:
                    action_text = "[bold]Max limit reached[/]"
                
            audit_content = (
                f"STATUS: [bold {r_color}]{res['status_color']}[/]\n"
                f"  - Risk Budget: {pos.ccy} {r_budget:,.0f} [dim]({r_pct:.2f}% of NAV)[/]\n"
                f"  - Exp. Budget: {pos.ccy} {e_budget:,.0f} [dim]({e_pct:.2f}% of NAV)[/]\n"
                f"  - Efficiency: [bold {rr_color}]{rr_val:.2f} RR[/]\n"
                f"  - Action: {action_text}"
            )
            
            # Scale-In Recommendation (Pilot)
            atr_val = metrics['ATR']
            if atr_val > 0:
                # Get daily ATR for the step logic
                daily_atr = atr_val # Fallback
                disc_data = self.discovery_cache.get(self.current_conid)
                if disc_data and 'rows' in disc_data and disc_data['rows']:
                    daily_atr = next((r.atr_wilder for r in disc_data['rows'] if r.label == '14d'), atr_val)

                # Use Inception Price for fixed milestones
                inception_p = metrics.get('Inception', metrics['Entry'])
                scale_step = metrics.get('ScaleStep', 0.5)
                
                pilot = RiskEngine.calculate_pilot_entry(
                    cur_p, atr_val, self.total_nav, pos.multiplier, 
                    inception_p, daily_atr, scale_step
                )
                
                # Define current_qty first
                current_qty = pos.qty
                current_outlay = current_qty * pos.entry_price * pos.multiplier
                stage_text = ""
                
                if metrics.get('EntryType') == 'SCALE_IN':
                    target_full = pilot['full_target_qty']
                    s2_target_qty = int(target_full * (2.0/3.0))
                    s3_target_qty = int(target_full)
                    
                    s2_hit = cur_p >= pilot['stage2_price']
                    s3_hit = cur_p >= pilot['stage3_price']
                    
                    # CUMULATIVE ROADMAP LOGIC:
                    # Stage 2 filled?
                    s2_filled = current_qty >= (s2_target_qty * 0.95)
                    s3_filled = current_qty >= (s3_target_qty * 0.95)
                    
                    # Required adds to catch up to current price level
                    if s3_hit:
                        current_stage = 3
                        needed = max(0, s3_target_qty - int(current_qty))
                        s2_display = f"[dim green]✓ Stage 2 @:  {pilot['stage2_price']:,.2f} (Skipped/Passed)[/]"
                        s3_display = f"[bold yellow]! Stage 3 @:  {pilot['stage3_price']:,.2f} (Add +{needed} sh)[/]" if not s3_filled else f"[dim green]✓ Stage 3 @:  {pilot['stage3_price']:,.2f} (Filled)[/]"
                    elif s2_hit:
                        current_stage = 2
                        needed = max(0, s2_target_qty - int(current_qty))
                        s2_display = f"[bold yellow]! Stage 2 @:  {pilot['stage2_price']:,.2f} (Add +{needed} sh)[/]" if not s2_filled else f"[dim green]✓ Stage 2 @:  {pilot['stage2_price']:,.2f} (Filled)[/]"
                        s3_display = f"[b]Stage 3 @:  {pilot['stage3_price']:,.2f}[/] (Target: {s3_target_qty} sh)"
                    else:
                        current_stage = 1
                        s2_display = f"[b]Stage 2 @:  {pilot['stage2_price']:,.2f}[/] (Target: {s2_target_qty} sh)"
                        s3_display = f"[b]Stage 3 @:  {pilot['stage3_price']:,.2f}[/] (Target: {s3_target_qty} sh)"

                    stage_text = f" [bold yellow](STAGE {current_stage}/3 ACTIVE)[/]"
                    
                    # Remaining capital to reach FULL target
                    remaining = max(0, s3_target_qty - int(current_qty)) * cur_p * pos.multiplier

                    roadmap_content = (
                        f"  - Current:   {int(current_qty)} sh (@ {pos.entry_price:,.2f})\n"
                        f"  - {s2_display}\n"
                        f"  - {s3_display}\n"
                        f"  - [cyan]Full Target Outlay: {pilot['scale_in_outlay']:,.0f} {pos.ccy}[/]\n"
                        f"  - [yellow]Capital to Full: {remaining:,.0f} {pos.ccy}[/]"
                    )
                else:
                    target_outlay = pilot['single_outlay']
                    target_full = pilot['full_target_qty']
                    current_qty = pos.qty
                    
                    # Quantity-driven remaining capital
                    if current_qty < target_full:
                        remaining = (target_full - current_qty) * cur_p * pos.multiplier
                    else:
                        remaining = 0
                        
                    roadmap_content = (
                        f"  - Current:   {int(current_qty)} sh (@ {pos.entry_price:,.2f})\n"
                        f"  - Target:    {target_full} sh (Full 1% Unit)\n"
                        f"  - [cyan]Target Outlay: {target_outlay:,.0f} {pos.ccy}[/]\n"
                        f"  - [yellow]Remaining Cap: {remaining:,.0f} {pos.ccy}[/]"
                    )

                step_val = metrics.get('ScaleStep', 0.5)
                pilot_content = (
                    f"--------------------------------------\n"
                    f"POSITION ROADMAP:{stage_text}\n"
                    f"{roadmap_content}\n"
                    f"  - Pilot Stop: [bold]{pilot['stop']:,.2f}[/] (assigned ATR)\n"
                    f"  - Scale Step: [bold]{step_val}x ATR[/]"
                )
        else:
            # Standalone exposure check if no stop exists yet
            nav_pct = metrics['NavPct']
            exp_color = "green" if nav_pct <= 5.0 else "red"
            exp_status = "[PASS]" if nav_pct <= 5.0 else "[OVER LIMIT]"
            audit_content = f"1. EXPOSURE: [bold {exp_color}]{nav_pct:.1f}%[/] of NAV | {exp_status} [dim](Limit: <= 5%)[/]\n[dim]Waiting for Strategy to calculate Risk...[/]"

        # 3. Build Output
        audit_text = (
            f"[bold yellow]{pos.ticker}[/] ({pos.name})\n"
            f"--------------------------------------\n"
            f"INTEGRITY: {integ_content}\n"
            f"--------------------------------------\n"
            f"DUAL-AUDIT:\n{audit_content}"
            f"{pilot_content}"
        )
        self.query_one("#position-context").update(audit_text)

    @work(exclusive=True, thread=True)
    def fetch_atr_data(self, conid: str) -> None:
        pos = next((p for p in self.positions if str(p.conid) == conid), None)
        if not pos: return
        data = get_atr_discovery_data(pos.ticker, pos.date_entry.strftime("%Y-%m-%d"), pos.entry_price, 
                                      conid=pos.conid, qty=pos.qty, inst_multiplier=pos.multiplier, total_nav=self.total_nav)
        if data:
            self.discovery_cache[conid] = data
            self.post_message(self.DiscoveryDataLoaded(conid, data))

    @on(DiscoveryDataLoaded)
    def on_discovery_loaded(self, message: DiscoveryDataLoaded) -> None:
        if message.conid == self.current_conid: self.update_discovery_ui(message.data)

    def update_discovery_ui(self, data: dict) -> None:
        self.query_one("#fixed-base").update(f"Base: {data['entry_price']:,.2f}")
        self.query_one("#trailing-base").update(f"Base: {data['max_price']:,.2f}")
        fixed_table, trail_table = self.query_one("#fixed-table"), self.query_one("#trailing-table")
        fixed_table.clear(); trail_table.clear()
        for row in data['rows']:
            r_color = "red" if row.pl_pct_nav > 1.5 else ("yellow" if row.pl_pct_nav > 1.0 else "white")
            pl_color = "green" if row.pl_at_stop >= 0 else "red"
            atr_display = f"{row.atr_wilder:.2f} [dim]({row.atr_sma:.2f})[/]"
            
            # Calculate SMA-based SL %
            base_p = data['max_price'] if row.stop_type == 'TRAILING' else data['entry_price']
            sma_pct = (row.atr_sma / base_p * 100) if base_p > 0 else 0
            sl_pct_display = f"{row.atr_base_pct:.1f}% [dim]({sma_pct:.1f}%)[/]"
            
            row_vals = (row.label, atr_display, f"{row.stop_price:,.2f}", sl_pct_display, 
                        f"[{pl_color}]{row.pl_at_stop:,.0f}[/]", f"[{r_color}]{row.pl_pct_nav:.1f}%[/]", f"{row.buffer_pct:.1f}%")
            if row.stop_type == "FIXED": fixed_table.add_row(*row_vals)
            else: trail_table.add_row(*row_vals)

    def action_toggle_help(self) -> None: self.push_screen(HelpScreen())

    @on(Input.Changed, "#atr-input")
    def on_strategy_change(self) -> None:
        """Instant Modeling Sandbox: updates Grid row AND Audit Checklist."""
        if not self.current_conid: return
        raw_text = self.query_one("#atr-input").value.strip().upper()
        if not raw_text: 
            self.refresh_risk_checklist() # Reset checklist to saved state
            return

        try:
            # Pattern: [Value/%] [F/T] [S] [Step]
            match = re.match(r"([0-9\.%]+)\s*([FT]?)\s*([S]?)\s*([0-9\.]*)", raw_text)
            if not match: return
            val_part, type_char, scale_in_char, step_char = match.groups()
            stop_type = "FIXED" if type_char == 'F' else "TRAILING"
            entry_type = "SCALE_IN" if scale_in_char == 'S' else "SINGLE"
            
            pos_obj = next((p for p in self.positions if str(p.conid) == self.current_conid), None)
            disc_data = self.discovery_cache.get(self.current_conid)
            if not pos_obj: return

            # Calculate Model
            final_atr = 0.0
            daily_atr = 0.0
            if disc_data and 'rows' in disc_data and disc_data['rows']:
                daily_atr = next((r.atr_wilder for r in disc_data['rows'] if r.label == '14d'), disc_data['rows'][0].atr_wilder)

            # --- SMART DEFAULT: PERCENTAGE (%) ---
            # Treat all numeric inputs as percentages unless they specifically start with '$'
            is_dollar = val_part.startswith('$')
            clean_val = val_part[1:] if is_dollar else (val_part[:-1] if val_part.endswith('%') else val_part)
            
            try:
                num_val = float(clean_val)
                if is_dollar:
                    final_atr = num_val
                else:
                    # Default to percentage behavior
                    pct = num_val / 100
                    base_p = disc_data['max_price'] if disc_data and stop_type == 'TRAILING' else pos_obj.entry_price
                    final_atr = base_p * pct
            except ValueError:
                return

            if final_atr <= 0: return

            # Default scale step logic based on input value
            scale_step = 0.5
            if step_char:
                try: scale_step = float(step_char)
                except: pass
            else:
                # Auto-detect if no step provided: <= 1.2x 14d window -> 1.0x step, else 0.5x step
                if daily_atr > 0:
                    scale_step = 1.0 if final_atr <= (1.2 * daily_atr) else 0.5
                else:
                    scale_step = 0.5

            base_p = disc_data['max_price'] if disc_data and stop_type == 'TRAILING' else pos_obj.entry_price
            sl_price = base_p - final_atr
            
            # RR Efficiency calculation
            tp_price = sl_price + (3 * final_atr)
            cur_p = pos_obj.current_price or pos_obj.mark_price
            dist_to_stop = (cur_p - sl_price)
            dist_to_tp = (tp_price - cur_p)
            hypo_rr = (dist_to_tp / dist_to_stop) if dist_to_stop > 0 else 0
            rr_color = "green" if hypo_rr > 3.0 else ("yellow" if hypo_rr > 1.0 else "red")

            risk_val = (sl_price - pos_obj.entry_price) * pos_obj.qty * pos_obj.multiplier
            hypo_r = (abs(pos_obj.entry_price - sl_price) * pos_obj.qty * pos_obj.multiplier / self.total_nav * 100) if self.total_nav > 0 else 0
            sl_pct_base = (final_atr / base_p * 100) if base_p > 0 else 0
            
            pl_color = "green" if risk_val >= 0 else "red"
            r_color = "red" if hypo_r > 1.5 else ("yellow" if hypo_r > 1.0 else "white")
            
            # Breach Signal for What-If
            cur_p_val = pos_obj.current_price or pos_obj.mark_price
            cur_p_display = f"{cur_p_val:,.2f}"
            if cur_p_val <= sl_price:
                cur_p_display = f"[on red][bold white] {cur_p_display} [/][/]"

            # 1. Update Table Row (What-If)
            table = self.query_one("#portfolio-table")
            ticker_prefix = f"[{stop_type[:1]}{'/S' if entry_type == 'SCALE_IN' else ''}]"
            table.update_cell(self.current_conid, "col_ticker", f"[bold yellow]* {ticker_prefix} {pos_obj.ticker}")
            table.update_cell(self.current_conid, "col_base", f"{base_p:,.2f}")
            table.update_cell(self.current_conid, "col_atr", f"{final_atr:.2f}")
            table.update_cell(self.current_conid, "col_stop_p", f"{sl_price:,.2f}")
            table.update_cell(self.current_conid, "col_sl_pct", f"{sl_pct_base:.1f}%")
            table.update_cell(self.current_conid, "col_pl_stop", f"[{pl_color}]{risk_val:,.0f}[/]")
            table.update_cell(self.current_conid, "col_cur_p", cur_p_display)
            table.update_cell(self.current_conid, "col_r", f"[{r_color}]{hypo_r:.1f}%[/]")
            table.update_cell(self.current_conid, "col_rr", f"[{rr_color}]{hypo_rr:.2f}[/]")

            # 2. Update Risk Audit Checklist with hypothetical stop
            self.refresh_risk_checklist(hypo_stop=sl_price)

            self.drafts[self.current_conid] = {'atr': final_atr, 'type': stop_type, 'ticker': pos_obj.ticker, 'entry_type': entry_type, 'scale_step': scale_step}
        except: pass

    def on_key(self, event) -> None:
        """CTRL+ENTER commits the current draft."""
        if event.key == "ctrl+j":
            if self.current_conid in self.drafts:
                d = self.drafts[self.current_conid]
                set_position_risk(self.current_conid, d['ticker'], d['atr'], d['type'], entry_type=d['entry_type'], scale_step=d.get('scale_step', 0.5))
                self.notify(f"COMMITTED: {d['ticker']} @ {d['atr']:.2f} ({d['entry_type']})")
                self.query_one("#atr-input").value = ""; self.load_portfolio()
                self.query_one("#portfolio-table").focus()

    def action_save_all(self) -> None:
        if not self.drafts: return
        for conid, draft in self.drafts.items(): 
            set_position_risk(conid, draft['ticker'], draft['atr'], draft['type'], entry_type=draft['entry_type'], scale_step=draft.get('scale_step', 0.5))
        self.notify(f"SUCCESS: Saved {len(self.drafts)} strategies.")
        self.drafts.clear(); self.load_portfolio(); self.query_one("#atr-input").value = ""

    def action_refresh(self) -> None: self.discovery_cache.clear(); self.load_portfolio()

def run_risk_workspace():
    """Entry point for main.py"""
    RiskWorkspace().run()

if __name__ == "__main__":
    run_risk_workspace()
