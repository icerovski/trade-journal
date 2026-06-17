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
from core.profit_taking import TRIM_MATRIX
from core.stop_loss import audit_position_risk, calculate_position_risk, get_atr_discovery_data
from core.ui_utils import UIUtils
from .chart_utils import launch_price_chart
from services.ui_components import HelpScreen
from db import set_position_risk, get_presets, save_preset, update_preset_profiles, get_setting, save_setting
from logger import logger, suppress_console_logging
from constants import RISK_RED_MULTIPLIER, EXPOSURE_RED_MULTIPLIER, TP_ATR_MULTIPLE, RR_SETUP_FLOOR, CAPITAL_HURDLE_PCT, STALE_MIN_AGE_DAYS, REGIME_REVERSAL_CONFIRM_DAYS

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

_STAGE_C  = {'PRE-M1': 'dim', 'M1': 'cyan', 'M2': 'yellow', 'TP': 'green'}
_REGIME_C = {'TREND': 'green', 'NORMAL': 'white', 'RANGING': 'red'}
_STAGE_DESC = {
    'PRE-M1': "Position has not yet earned one ATR of profit. Hold — the stop is the only exit mechanism.",
    'M1':     "One ATR of profit secured. Time to make the position risk-free at no cost.",
    'M2':     "Two ATRs of profit banked. Time for partial profit-taking sized to the trend regime.",
    'TP':     "Full 3×ATR target reached. Larger trim or full exit, sized to the trend regime.",
}

def _stage_desc(stage: str, regime: str) -> str:
    """Stage description, regime-aware for M2/TP so the blurb matches the action directive
    below it (e.g. M2 in a confirmed TREND is hold, not trim)."""
    if stage == 'M2':
        return {
            'TREND':   "Two ATRs of profit banked. In a confirmed trend, hold — let the trailing stop run the winner and bank at the target.",
            'NORMAL':  "Two ATRs of profit banked. Take partial profits (about a third) and let the remainder run.",
            'RANGING': "Two ATRs of profit banked. No structural support — protect gains by trimming about half.",
        }.get(regime, _STAGE_DESC['M2'])
    if stage == 'TP':
        return {
            'TREND':   "Full 3R target reached in a confirmed trend. Take a modest slice and let the rest run on its stop.",
            'NORMAL':  "Full 3R target reached. Take meaningful profits (about a third); keep a runner only while RR stays above 1.0.",
            'RANGING': "Full 3R target reached with no structural support. Close the position in full.",
        }.get(regime, _STAGE_DESC['TP'])
    return _STAGE_DESC.get(stage, '')

def solve_breakeven_add(qty: float, entry: float, stop: float, price: float) -> Optional[float]:
    """Shares to BUY at `price` so the aggregate average cost equals `stop` (P/L @ Stop = 0).
    Derivation: solve the WAC blend (entry·qty + price·add)/(qty + add) = stop  →
    add = qty·(entry − stop)/(stop − price). Returns None when no purchase achieves it —
    price == stop, no current quantity, or the math yields a non-positive add (trimming
    can't move a weighted-average cost, so break-even is only reachable by buying)."""
    denom = stop - price
    if denom == 0 or qty <= 0:
        return None
    add = qty * (entry - stop) / denom
    return round(add) if add > 0 else None


def resolve_tp_mult(token: str, entry: float, inception_atr: float, qty: float):
    """Resolve a `TP:` token into a multiple of the inception ATR.

    Returns (mult, clear, ok):
      • clear=True  → user typed `TP:-` (revert to the default 3R), mult is None.
      • ok=False    → token could not be resolved (missing inception ATR, or a $ target
                      with no quantity); caller should warn and ignore.
    Accepted forms (token already upper-cased, `TP:` stripped):
      4 | 4R           → explicit multiple of inception ATR
      +35% | 35%       → gain as % of entry, divided by inception ATR
      $60K | $60000 | 60K → absolute profit, per-share / inception ATR (needs qty)
    """
    token = (token or "").strip()
    if token == '-':
        return None, True, True
    if not inception_atr or inception_atr <= 0 or not entry or entry <= 0:
        return None, False, False
    try:
        if token.endswith('R'):
            return float(token[:-1]), False, True
        if token.endswith('%'):
            pct = float(token.rstrip('%').lstrip('+'))
            return (entry * pct / 100.0) / inception_atr, False, True
        if token.startswith('$') or token.endswith('K'):
            amt = token.lstrip('$')
            scale = 1000.0 if amt.endswith('K') else 1.0
            amt = float(amt.rstrip('K')) * scale
            if qty <= 0:
                return None, False, False  # $ target needs a share count
            return (amt / qty) / inception_atr, False, True
        return float(token), False, True  # plain number → multiple
    except ValueError:
        return None, False, False


def _trim_shares(qty: float, pct: float) -> float:
    """Whole-share lots: round to nearest, never exceed holdings, never round a genuine
    trim down to zero. Fractional lots (bonds/options) keep the fractional figure."""
    raw = qty * pct
    return min(int(qty), max(1, round(raw))) if qty >= 1 else round(raw, 4)


def _exit_recommendation(stage, regime, qty, entry, sl, tp, cur_p, rr, stop_type) -> Optional[dict]:
    """Single source of truth for the profit-taking directive at an exit stage.

    Returns a dict {verb, color, headline, shares, pct, restore_sl, urgent, reason} or
    None when the position carries no exit stage. Pure — drives BOTH the one-line verdict
    (panel header + table ACTION column) and the detailed exit-guidance prose, so the
    headline action and the justification below it can never diverge.

    Precedence within the exit axis mirrors the trading logic: M1 makes the position
    risk-free (never sells); a sub-1.0 RR efficiency floor on a FIXED M2/TP stop forces an
    exit; otherwise the TRIM_MATRIX maps (stage, regime) → trim fraction (0.0 == let it run).
    """
    if not stage:
        return None
    sl = sl or 0.0
    tp = tp or 0.0

    # M1: make the position risk-free — never sell here.
    if stage == 'M1':
        if sl > entry:
            return {'verb': 'HOLD', 'color': 'cyan', 'shares': 0, 'pct': 0.0,
                    'restore_sl': None, 'urgent': False,
                    'headline': 'HOLD — stop already locks in profit',
                    'reason': f'Stop {sl:,.2f} locks +{sl - entry:.2f}/sh. Risk-free; monitor for M2.'}
        return {'verb': 'STOP→ENTRY', 'color': 'cyan', 'shares': 0, 'pct': 0.0,
                'restore_sl': entry, 'urgent': False,
                'headline': f'RAISE STOP to entry ({entry:,.2f}) — do not sell',
                'reason': 'Makes the position risk-free; hold the full position.'}

    # RR efficiency floor (FIXED M2/TP only): remaining upside has shrunk below downside.
    if stop_type == 'FIXED' and stage in ('M2', 'TP') and 0 < rr < 1.0:
        if regime == 'RANGING':
            return {'verb': 'EXIT', 'color': 'red', 'shares': int(qty), 'pct': 1.0,
                    'restore_sl': None, 'urgent': True,
                    'headline': f'EXIT all — RR {rr:.2f}, no support',
                    'reason': 'Remaining upside < downside and no trend to justify the hold.'}
        restore_sl = (2 * cur_p - tp) if (tp > 0 and cur_p > 0) else 0.0
        return {'verb': 'EXIT', 'color': 'red', 'shares': int(qty), 'pct': 1.0,
                'restore_sl': restore_sl, 'urgent': True,
                'headline': f'EXIT all, or raise stop to {restore_sl:,.2f} — RR {rr:.2f}',
                'reason': 'Remaining upside is smaller than remaining downside.'}

    # TRIM_MATRIX: (stage, regime) → (fraction, rationale). 0.0 == hold / let it run.
    key = (stage, regime)
    if key in TRIM_MATRIX:
        pct, desc = TRIM_MATRIX[key]
        if pct <= 0:
            return {'verb': 'HOLD', 'color': 'green', 'shares': 0, 'pct': 0.0,
                    'restore_sl': None, 'urgent': False,
                    'headline': 'HOLD — let it run', 'reason': desc}
        shares = _trim_shares(qty, pct)
        return {'verb': 'TRIM', 'color': 'yellow', 'shares': shares, 'pct': pct,
                'restore_sl': None, 'urgent': False,
                'headline': f'TRIM ~{shares} sh ({int(pct * 100)}%)', 'reason': desc}
    return None


def _ladder_str(stage, m1, m2, tp) -> str:
    """One-line M1/M2/TP milestone ladder with the current stage marked (◄) and passed
    milestones checked (✓)."""
    sc = _STAGE_C.get(stage, 'white')
    order = ('PRE-M1', 'M1', 'M2', 'TP')
    cur_idx = order.index(stage) if stage in order else 0

    def _ms(label, price, idx):
        if price <= 0:
            return f"[dim]{label}: ---[/]"
        if idx < cur_idx:
            return f"[green]{label}: {price:,.2f} ✓[/]"
        if idx == cur_idx:
            return f"[{sc}][bold]{label}: {price:,.2f} ◄[/][/]"
        return f"[dim]{label}: {price:,.2f}[/]"

    return f"  {_ms('M1', m1, 1)}   {_ms('M2', m2, 2)}   {_ms('TP', tp, 3)}"


def _exit_guidance_str(pos, cur_p: float) -> str:
    stage      = getattr(pos, 'exit_stage', '')
    regime     = getattr(pos, 'trend_regime', 'NORMAL')
    dma_signal = getattr(pos, 'regime_dma_signal', 'NEUTRAL')
    dma_days   = getattr(pos, 'regime_dma_days', 0)
    direction  = getattr(pos, 'regime_dma_direction', 'UP')
    dma200     = getattr(pos, 'regime_dma200', 0.0)
    m1         = getattr(pos, 'm1_price', 0.0)
    m2         = getattr(pos, 'm2_price', 0.0)
    tp         = getattr(pos, 'tp_price', 0.0) or 0.0

    if not stage:
        return ""

    sc = _STAGE_C.get(stage, 'white')
    rc = _REGIME_C.get(regime, 'white')

    # ── Regime calculation breakdown ─────────────────────────────────────────
    dma_c = 'green' if dma_signal == 'BUY' else ('red' if dma_signal == 'SELL' else 'yellow')
    price_above_dma = cur_p >= dma200 if (dma200 > 0 and cur_p > 0) else True

    if dma200 > 0 and cur_p > 0:
        diff = cur_p - dma200
        diff_c = 'green' if diff >= 0 else 'red'
        dma200_str = f"{dma200:,.2f}  (price [{diff_c}]{'+' if diff>=0 else ''}{diff:,.2f}[/] vs DMA)"
    else:
        dma200_str = "---"

    if regime == 'TREND':
        verdict = f"[green]Rising {dma_days}d (≥ 21) → TREND[/]"
    elif regime == 'NORMAL' and direction == 'DOWN':
        verdict = f"[yellow]DMA reversed {dma_days}d (< {REGIME_REVERSAL_CONFIRM_DAYS}, unconfirmed) → held at NORMAL[/]"
    elif regime == 'NORMAL' and dma_days >= 21 and not price_above_dma:
        verdict = f"[yellow]Rising {dma_days}d (≥ 21) but price below 200-DMA → NORMAL[/]"
    elif regime == 'NORMAL':
        verdict = f"[white]Rising {dma_days}d (10–20) → NORMAL[/]"
    elif direction == 'DOWN':
        verdict = f"[red]Declining {dma_days}d (≥ {REGIME_REVERSAL_CONFIRM_DAYS}, confirmed) → RANGING[/]"
    else:
        verdict = f"[red]Rising only {dma_days}d (< 10) → RANGING[/]"

    calc = (
        f"\n  REGIME CALCULATION:\n"
        f"  200-DMA:    {dma200_str}\n"
        f"  DMA signal: [{dma_c}]{dma_signal} ({dma_days}d)[/]  →  {verdict}\n"
    )

    # ── Action ── single-sourced from _exit_recommendation so this detailed prose and
    # the one-line verdict in the panel header can never disagree. The efficiency-floor
    # (sub-1.0 RR) exit is a FIXED-stop concept handled inside the recommendation: a
    # TRAILING stop has no real target so its sub-1.0 RR is an artifact, and M1 is exempt
    # because raising the stop to entry is expected to produce a sub-1.0 RR.
    sl = getattr(pos, 'sl_price', None) or 0.0
    entry = pos.entry_price
    rr = getattr(pos, 'rr_ratio', 0.0)
    rec = _exit_recommendation(stage, regime, pos.qty, entry, sl, tp, cur_p, rr,
                               getattr(pos, 'stop_type', 'FIXED'))
    if rec is None:
        action = ""
    elif rec['verb'] == 'STOP→ENTRY':
        action = (
            f"\n  [bold cyan]→ Move stop to entry ({entry:,.2f}) — do not sell any shares.[/]\n"
            f"  [dim]The position is now risk-free. The stop at entry means you exit at break-even\n"
            f"  at worst, regardless of what happens next. Hold the full position.[/]\n"
        )
    elif rec['verb'] == 'HOLD' and stage == 'M1':
        action = (
            f"\n  [bold cyan]→ Stop already above entry — position is risk-free.[/]\n"
            f"  [dim]Your stop at {sl:,.2f} locks in a minimum profit of +{sl - entry:.2f}/sh.\n"
            f"  No action needed at this stage. Hold and monitor for M2.[/]\n"
        )
    elif rec['verb'] == 'HOLD':
        action = (
            f"\n  [bold green]→ Hold — no trim.[/]\n"
            f"  [dim]{rec['reason']}[/]\n"
        )
    elif rec['verb'] == 'TRIM':
        action = (
            f"\n  [bold]→ Sell ~{rec['shares']} sh ({int(rec['pct'] * 100)}%)[/]\n"
            f"  [dim]{rec['reason']}[/]\n"
        )
    else:  # EXIT — RR efficiency floor
        dist_to_tp   = (tp - cur_p) if (tp > 0 and cur_p > 0) else 0.0
        dist_to_stop = (cur_p - sl) if (cur_p > 0 and sl > 0) else 0.0
        profitable_stop = sl > entry
        if rec['restore_sl'] is None:  # RANGING — no structural support; tighten-and-hold not offered
            stop_note = (
                f"  [dim]The stop ({sl:,.2f}) is above entry, so a stop-out is still profitable — "
                f"but with no trend there is nothing to justify holding for the thin upside.[/]\n"
            ) if profitable_stop else ""
            action = (
                f"\n  [bold red]⚠ RR {rr:.2f} — Efficiency floor triggered (RANGING, no support).[/]\n"
                f"  [dim]From current price: +{dist_to_tp:,.2f} to TP vs −{dist_to_stop:,.2f} to stop.\n"
                f"  Remaining upside is smaller than remaining downside.[/]\n"
                f"{stop_note}"
                f"  [bold red]→ Exit all shares.[/]\n"
            )
        else:
            profit_note = (
                f"  [dim]Note: stop ({sl:,.2f}) is above entry — a stop-out would still be profitable.[/]\n"
            ) if profitable_stop else ""
            action = (
                f"\n  [bold red]⚠ RR {rr:.2f} — Efficiency floor triggered.[/]\n"
                f"  [dim]From current price: +{dist_to_tp:,.2f} to TP vs −{dist_to_stop:,.2f} to stop.\n"
                f"  Remaining upside is smaller than remaining downside.[/]\n"
                f"{profit_note}"
                f"  [bold red]→ Exit all shares, or raise stop to [bold]{rec['restore_sl']:,.2f}[/] (restores RR ≥ 1.0).[/]\n"
            )

    stage_desc = _stage_desc(stage, regime)
    return (
        f"\n──────────────────────────────────────────\n"
        f"EXIT STAGE: [{sc}][bold]{stage}[/][/]   "
        f"Regime: [{rc}][bold]{regime}[/][/]\n"
        f"  [dim]{stage_desc}[/]\n"
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
                            placeholder="F: price  |  T: %/$  |  [P:S/B/L] [R:x] [E:x] [TP:n]",
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
        table.add_column("CUR P", key="col_cur_p")
        table.add_column("STOP P", key="col_stop_p")
        table.add_column("SL %", key="col_sl_pct")
        table.add_column("R", key="col_r")
        table.add_column("% NAV", key="col_nav_pct")
        table.add_column("P/L STOP", key="col_pl_stop")
        table.add_column("STOP BASE", key="col_base")
        table.add_column("ATR", key="col_atr")
        table.add_column("HIGH P", key="col_high_p")
        table.add_column("AVG COST", key="col_avg_cost")
        table.add_column("MKT VAL", key="col_mkt_val")
        table.add_column("COST", key="col_cost")
        
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
                    # Reconcile sizing against the exit ladder so the ACTION column agrees with
                    # the panel verdict: a position at a profit-taking stage shows the ladder
                    # directive, never a raw +X% ADD. The exposure headroom is real but is not
                    # licence to add to a winner that has reached its target.
                    exit_rec = _exit_recommendation(
                        row.get('ExitStage', ''), row.get('TrendRegime', 'NORMAL'), qty,
                        effective_entry, sl_p, tp_p, cur_p_val,
                        row.get('RR_Ratio', 0.0), row.get('StopType', 'FIXED'),
                    )
                    adj_pct = (adj / qty) * 100
                    add_threshold = max(1, int(qty * ACTION_THRESHOLD_PCT / 100.0))
                    trim_threshold = add_threshold

                    if res['is_breached'] or (exit_rec and exit_rec['urgent']):
                        action_display = "[bold red]EXIT[/]"
                    elif exit_rec and exit_rec['verb'] == 'TRIM':
                        action_display = f"[bold yellow]TRIM {int(exit_rec['pct'] * 100)}%[/]"
                    elif exit_rec and exit_rec['verb'] == 'STOP→ENTRY':
                        action_display = "[bold cyan]STOP→E[/]"
                    elif exit_rec:  # HOLD — M1 risk-free or let-it-run
                        action_display = "[bold green]HOLD[/]"
                    elif adj > add_threshold:
                        action_display = f"[bold green]+{adj_pct:.1f}%[/]"
                    elif adj < -trim_threshold:
                        action_display = f"[bold red]{adj_pct:.1f}%[/]"

            r_val = f"{row['risk_pct_nav']:.1f}% ({max_r_pct:.1f}%)"
            nav_val = f"{row['NavPct']:.1f}% ({max_exp_pct:.1f}%)"
            cur_p_display = f"{cur_p_val:,.2f}"
            if has_risk and pd.notnull(sl_p) and cur_p_val <= sl_p:
                cur_p_display = f"[on red][bold white] {cur_p_display} [/][/]"
                ticker_display += " [bold white on red] BREACH [/]"
            else:
                if has_risk and pd.notnull(tp_p) and cur_p_val >= tp_p:
                    ticker_display += " [bold cyan]★[/]"
            r_color = "red" if row['risk_pct_nav'] > (max_r_pct * RISK_RED_MULTIPLIER) else ("yellow" if row['risk_pct_nav'] > max_r_pct else "white")
            exp_color = "red" if row['NavPct'] > (max_exp_pct * EXPOSURE_RED_MULTIPLIER) else ("yellow" if row['NavPct'] > max_exp_pct else "white")
            
            if not has_risk:
                pl_display = "---"
            else:
                planned_pl = row['Risk_Val']
                live_pl = row.get('Risk_Val_Live', planned_pl)
                breached = pd.notnull(sl_p) and cur_p_val > 0 and cur_p_val <= sl_p
                if breached:
                    # Below the stop: realisable exit has degraded past the planned stop-out.
                    # Show the live figure with the original P/L-at-stop in parens to compare.
                    live_color = "green" if live_pl >= 0 else "red"
                    pl_display = f"[{live_color}]{live_pl:,.0f}[/] [dim]({planned_pl:,.0f})[/]"
                else:
                    pl_display = UIUtils.color_fmt(planned_pl)
            mkt_val  = row['MarketValue']
            cost_val = row['CostBasis']
            mkt_color   = "green" if mkt_val >= cost_val else "red"
            mkt_display  = f"[{mkt_color}]{mkt_val:,.0f}[/]" if row['Qty'] > 0 else "---"
            cost_display = f"{cost_val:,.0f}" if cost_val > 0 else "---"
            # ATR column: for FIXED, show signed stop-to-entry distance.
            # Positive (green) means stop is above entry — profit locked in.
            # Negative cases are impossible after max(0,...) but shown as absolute for safety.
            if has_risk:
                if row['StopType'] == 'FIXED' and row['Entry'] > 0 and pd.notnull(row['SL_Price']):
                    dist = row['SL_Price'] - row['Entry']
                    if dist >= 0:
                        atr_display = f"[green]+{dist:.2f}[/]"
                    else:
                        atr_display = f"{abs(dist):.2f}"
                else:
                    atr_display = f"{row['ATR']:.2f}"
            else:
                atr_display = "---"

            table.add_row(
                ticker_display,
                action_display,
                cur_p_display,
                f"{row['SL_Price']:,.2f}" if has_risk else "---",
                f"{row['sl_pct_base']:.1f}%" if has_risk else "---",
                f"[{r_color}]{r_val}[/]",
                f"[{exp_color}]{nav_val}[/]",
                pl_display,
                f"{(row['MaxSinceEntry'] if row['StopType'] == 'TRAILING' else row['Entry']):,.2f}",
                atr_display,
                f"{row['MaxSinceEntry']:,.2f}" if row['MaxSinceEntry'] > 0 else "---",
                f"{row['Entry']:,.2f}" if row['Entry'] > 0 else "---",
                mkt_display,
                cost_display,
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

    def refresh_risk_checklist(self, hypo_stop: Optional[float] = None, hypo_atr: Optional[float] = None, hypo_max_r: Optional[float] = None, hypo_max_exp: Optional[float] = None, hypo_qty: Optional[float] = None, hypo_entry: Optional[float] = None, hypo_add: Optional[float] = None, goal_seek: Optional[str] = None, hypo_tp_mult: float = -1.0) -> None:
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

        # Quantity modeling (+N / -N / BE goal-seek) transacts at the LIVE market price, not
        # the modeled entry that stop-analysis anchors to — so an add reflects what you would
        # actually pay now. active_entry still holds the real average cost for the WAC blend.
        if hypo_add is not None or goal_seek:
            market_p = pos.current_price or pos.mark_price
            if market_p and market_p > 0:
                cur_p = market_p

        active_max_r = hypo_max_r if hypo_max_r is not None else pos.max_r_pct
        active_max_exp = hypo_max_exp if hypo_max_exp is not None else pos.max_exp_pct
        active_qty = hypo_qty if hypo_qty is not None else pos.qty
        active_entry = hypo_entry if hypo_entry is not None else (pos.entry_price if pos.entry_price > 0 else cur_p)
        stop_p = hypo_stop if hypo_stop is not None else pos.sl_price
        
        audit_content = "[dim]Enter ATR/Stop in Lab to calculate risk...[/]"
        exit_stage = getattr(pos, 'exit_stage', '')
        regime = getattr(pos, 'trend_regime', 'NORMAL')

        is_modeling = self.current_conid in self.drafts
        
        # Determine effective stop for audit logic (Default to entry if none set)
        effective_stop = stop_p if pd.notnull(stop_p) else active_entry
        
        if pd.notnull(effective_stop) and cur_p > 0:
            is_safe = cur_p > effective_stop
            buffer = ((cur_p - effective_stop) / cur_p * 100) if cur_p > 0 else 0
            res = audit_position_risk(cur_p, effective_stop, active_entry, active_qty, pos.multiplier, self.total_nav, max_r_pct=active_max_r, max_exp_pct=active_max_exp, fx_rate=pos.fx_rate)
            
            # For FIXED stop: pos.atr holds the stop price, not an ATR distance.
            # Resolve a proper ATR from inception_atr or discovery for efficiency/pilot calcs.
            if pos.stop_type == 'FIXED' and hypo_atr is None:
                disc_atr = next((r.atr_wilder for r in disc['rows'] if r.label == '14d'), None) if (disc and disc.get('rows')) else None
                effective_atr = disc_atr or (pos.inception_atr if (pos.inception_atr and pos.inception_atr > 0) else max(0.0, (active_entry or 0) - (stop_p or active_entry or 0)))
            else:
                effective_atr = hypo_atr if hypo_atr is not None else pos.atr

            atr_width = effective_atr
            # TP is anchored to entry + TP_ATR_MULTIPLE × R, where R is the ORIGINAL risk
            # unit (inception ATR) — same as pos.tp_price and the M1/M2/TP ladder — so the
            # audit-panel RR and the exit-stage efficiency floor never diverge. The live
            # trailing ATR (atr_width) governs the stop, not the reward target. Falls back
            # to entry-stop distance, and stays modeling-aware via active_entry/effective_stop.
            r_unit = pos.inception_atr if (pos.inception_atr and pos.inception_atr > 0) \
                     else max(0.0, (active_entry or 0) - (effective_stop or active_entry or 0))
            # Effective TP multiple: a modeled override (hypo_tp_mult ≠ -1, where None→default)
            # takes precedence; otherwise the saved override; otherwise the default 3R.
            if hypo_tp_mult != -1.0:
                tp_mult_eff = hypo_tp_mult if (hypo_tp_mult and hypo_tp_mult > 0) else TP_ATR_MULTIPLE
            else:
                tp_mult_eff = pos.tp_atr_mult if (getattr(pos, 'tp_is_override', False) and pos.tp_atr_mult) else TP_ATR_MULTIPLE
            tp_target = active_entry + (tp_mult_eff * r_unit)
            efficiency = ((tp_target - cur_p) / (cur_p - effective_stop) if cur_p > effective_stop else 0)

            # User-driven scenario: an explicit +/- quantity or a goal-seek overrides the
            # system's recommended adjustment so the sizing table reflects YOUR what-if.
            modeled_add = None
            if goal_seek == 'BE':
                modeled_add = solve_breakeven_add(active_qty, active_entry, effective_stop, cur_p)
            elif hypo_add is not None:
                modeled_add = int(hypo_add)

            # 2. Reconciled verdict — ONE directive across the three axes, by precedence:
            #    breach → urgent RR-exit → exit-stage ladder → sizing add/trim → hold.
            #    The fundamental that resolves the add-vs-trim conflict: exposure headroom
            #    sizes a new/early position; it is never licence to add to a winner that has
            #    reached a profit-taking stage. So at an exit stage the ladder governs and the
            #    headroom is reported but muted (mirrors the table ACTION column outward).
            exit_rec = _exit_recommendation(exit_stage, regime, active_qty, active_entry,
                                            effective_stop, pos.tp_price, cur_p, efficiency,
                                            pos.stop_type)
            room = int(res['adjustment'])
            if res['is_breached']:
                v_color, v_label = 'red', 'EXIT NOW — stop breached'
                v_sub = f"Sell all {int(active_qty)} sh @ {cur_p:,.2f}."
                target_qty = 0
            elif modeled_add is not None:
                target_qty = int(active_qty + modeled_add)
                verb = "ADD" if modeled_add >= 0 else "TRIM"
                tag = " (P/L@Stop → 0)" if goal_seek == 'BE' else ""
                v_color, v_label = 'magenta', f"MODELING: {verb} {abs(int(modeled_add))} sh{tag}"
                v_sub = f"@ {cur_p:,.2f} → {target_qty} sh"
            elif goal_seek == 'BE':
                target_qty = int(active_qty)
                v_color, v_label = 'magenta', "GOAL-SEEK: P/L@Stop = 0 not reachable by buying"
                v_sub = f"Would require trimming at {cur_p:,.2f}, which can't move average cost."
            elif exit_rec and exit_rec['urgent']:
                target_qty = 0
                v_color, v_label, v_sub = exit_rec['color'], exit_rec['headline'], exit_rec['reason']
            elif exit_rec:
                target_qty = int(active_qty)   # never add at a profit-taking stage
                v_color, v_label, v_sub = exit_rec['color'], exit_rec['headline'], exit_rec['reason']
                if room > 0:
                    headroom = active_max_exp - res['current_exposure_pct']
                    v_sub += f"  [dim]({headroom:.1f}% exposure room exists, but no adds at target.)[/]"
            elif room > 0:
                target_qty = int(active_qty + room)
                v_color, v_label = 'green', f"ADD +{room} sh"
                v_sub = f"@ {cur_p:,.2f} → {target_qty} sh — room to the {active_max_exp:.1f}% exposure limit."
            elif room < 0:
                target_qty = int(active_qty + room)
                v_color, v_label = 'yellow', f"TRIM {abs(room)} sh"
                v_sub = f"Over the {active_max_exp:.1f}% exposure limit @ {cur_p:,.2f}."
            else:
                target_qty = int(active_qty)
                v_color, v_label = 'white', "HOLD — at max size"
                v_sub = "Within all limits; no adjustment needed."

            # Capital-efficiency nudge (orthogonal to the ATR ladder). Suppressed on a breach,
            # where the exit directive already dominates. Reflects the live position's AAGR/age.
            stale_line = ""
            if getattr(pos, 'is_stale', False) and not res['is_breached']:
                stale_line = (
                    f"  [bold red]⏳ STALE: {pos.aagr:+.1f}% AAGR over {pos.age_days}d — "
                    f"below {CAPITAL_HURDLE_PCT:.0f}% hurdle. Review thesis or redeploy capital.[/]\n"
                )

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

            # Capital-efficiency metric. Total return is always meaningful; the annualised
            # figure (AAGR) is only decision-useful past the hurdle horizon — below that it
            # is wild extrapolation (a 2-month winner annualises to absurd %), so it is
            # dimmed and tagged 'prelim'. STALE badge mirrors pos.is_stale.
            if pos.qty > 0 and pos.entry_price > 0:
                ret_c = "green" if pos.pl_pct >= 0 else "red"
                if pos.age_days >= STALE_MIN_AGE_DAYS:
                    ann_c = "green" if pos.aagr >= CAPITAL_HURDLE_PCT else ("yellow" if pos.aagr >= 0 else "red")
                    ann_str = f"[{ann_c}]{pos.aagr:+.0f}%/yr[/]"
                elif pos.age_days > 0:
                    ann_str = f"[dim]{pos.aagr:+.0f}%/yr prelim[/]"
                else:
                    ann_str = "[dim]—[/]"
                stale_badge = " [bold reverse red] STALE [/]" if getattr(pos, 'is_stale', False) else ""
                capital_str = (
                    f"  - Return: [bold {ret_c}]{pos.pl_pct:+.1f}%[/] total · {ann_str} · {pos.age_days}d "
                    f"[dim](hurdle {CAPITAL_HURDLE_PCT:.0f}%/yr ≥{STALE_MIN_AGE_DAYS}d)[/]{stale_badge}\n"
                )
            else:
                capital_str = ""

            # Compact metric strip: the three audit axes + stop integrity on one line.
            r_pct, e_pct = res['current_risk_pct'], res['current_exposure_pct']
            r_c = 'red' if r_pct > active_max_r * 1.5 else ('yellow' if r_pct > active_max_r else 'green')
            e_c = 'red' if e_pct > active_max_exp * 1.1 else ('yellow' if e_pct >= active_max_exp else 'green')
            eff_c = 'green' if efficiency >= 2.0 else ('yellow' if efficiency >= 1.0 else 'red')
            buf_c = 'green' if is_safe else 'red'
            strip = (
                f"  R [bold {r_c}]{r_pct:.2f}%[/][dim]/{active_max_r}[/]   "
                f"Exp [bold {e_c}]{e_pct:.2f}%[/][dim]/{active_max_exp}[/]   "
                f"RR [bold {eff_c}]{efficiency:.2f}[/]   "
                f"[{buf_c}]{'SAFE' if is_safe else 'BREACH'} {buffer:.0f}% buf[/]\n"
            )
            ladder = (_ladder_str(exit_stage, pos.m1_price, pos.m2_price, pos.tp_price) + "\n") if exit_stage else ""

            # Target line: shown whenever a TP override is in force (saved or being modeled).
            # Flags the FORWARD reward:risk — (target − price)/(price − stop) — against the 3:1
            # setup floor so an extended target that no longer pays 3:1 from here is visible.
            if tp_mult_eff != TP_ATR_MULTIPLE and tp_target > 0:
                trr_c = 'green' if efficiency >= RR_SETUP_FLOOR else ('yellow' if efficiency >= 1.0 else 'red')
                trr_flag = '' if efficiency >= RR_SETUP_FLOOR else f"  [bold red]⚠ below {RR_SETUP_FLOOR:.0f}:1[/]"
                tp_line = (f"  [bold]TARGET[/] {tp_mult_eff:.1f}R → [bold]{tp_target:,.2f}[/]  ·  "
                           f"fwd RR [bold {trr_c}]{efficiency:.2f}[/][dim] vs {RR_SETUP_FLOOR:.0f}[/]{trr_flag}\n")
            else:
                tp_line = ""

            # DETAILS — the supporting calculations, demoted below the verdict.
            details = (
                f"--------------------------------------\n[dim]DETAILS[/]\n"
                f"{capital_str}"
                f"INCEPTION STOP: [bold]{incep_stop_str}[/]{trailed_str}\n"
                f"INCEPTION ATR:  [bold]{incep_atr_str}[/]{vol_delta_str}\n"
                f"{remediation_str}"
                f"{_exit_guidance_str(pos, cur_p)}"
            )

            # Verdict-led layout: the single reconciled directive first, then the metric
            # strip + ladder, then the kept sizing-impact table, then the demoted details.
            audit_content = (
                f"▶ [bold {v_color}]{v_label}[/]\n"
                f"  [dim]{v_sub}[/]\n"
                f"{stale_line}"
                f"--------------------------------------\n"
                f"{strip}"
                f"{tp_line}"
                f"{ladder}"
                f"{sizing_table}"
                f"{details}"
            )

        incep_str = pos.date_entry.strftime("%Y-%m-%d") if pd.notnull(pos.date_entry) else "Unknown"
        stage_tag = f"  ·  [{_STAGE_C.get(exit_stage, 'white')}]{exit_stage}[/] · [{_REGIME_C.get(regime, 'white')}]{regime}[/]" if exit_stage else ""
        audit_header = f"[bold yellow]{pos.ticker}[/] ({pos.name})  ·  INCEPTION [cyan]{incep_str}[/]{stage_tag}"
        if is_modeling:
            audit_header = "[bold reverse yellow] MODELING STRATEGY [/]\n" + audit_header

        audit_text = f"{audit_header}\n--------------------------------------\n{audit_content}"
        self.query_one("#position-context", Static).update(audit_text)

    @work(exclusive=True, thread=True)
    def fetch_atr_data(self, conid: Optional[str], ticker: Optional[str] = None) -> None:
        if conid and not str(conid).startswith("PROSPECT:"):
            pos = next((p for p in self.positions if str(p.conid) == conid), None)
            if not pos:
                return
            t_sym, entry_p, entry_d, m, q = pos.ticker, pos.entry_price, pos.date_entry.strftime("%Y-%m-%d"), pos.multiplier, pos.qty
            max_r, max_exp = pos.max_r_pct, pos.max_exp_pct
            hwm = pos.max_since_entry
        else:
            t_sym = ticker or str(conid).split(":")[-1]
            entry_p, entry_d, m, q = 0.0, pd.Timestamp.now().strftime("%Y-%m-%d"), 1.0, 0.0
            max_r, max_exp = 1.0, 5.0
            hwm = 0.0

        with suppress_console_logging():
            data = get_atr_discovery_data(t_sym, entry_d, entry_p, conid=(conid if conid and not str(conid).startswith("PROSPECT:") else None), qty=q, inst_multiplier=m, total_nav=self.total_nav, max_r_pct=max_r, max_exp_pct=max_exp, mapper=self.pm.mapper, max_since_entry=hwm)
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
            table.add_row(f"[PROSPECT] {ticker}", "---", "---", "---", "---", "---", "---", "---", "---", "---", "---", "---", "---", "---", key=self.current_conid)
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

            # TP override: TP:4 / TP:4R / TP:+35% / TP:$60K / TP:- (clear). A multiple of the
            # frozen inception ATR — stays put when the stop ATR changes. Parsed BEFORE the
            # +N/-N quantity regex so "TP:+35%" isn't misread as a share quantity.
            existing_tp = pos.tp_atr_mult if getattr(pos, 'tp_is_override', False) else None
            tp_final = existing_tp
            tp_m = re.search(r"TP:(\-|\+?\$?\d+(?:\.\d+)?[%KR]?)", raw)
            if tp_m:
                raw = raw.replace(tp_m.group(0), "").strip()
                inc_atr = pos.inception_atr if (pos.inception_atr and pos.inception_atr > 0) else pos.atr
                mult, clear, ok = resolve_tp_mult(tp_m.group(1), pos.entry_price, inc_atr, pos.qty)
                if not ok:
                    self.notify("TP target needs an inception ATR (and a share count for $ targets).", severity="warning")
                elif clear:
                    tp_final = None
                else:
                    tp_final = mult

            # Quantity modeling: +N / -N shares at the live price, or BE = solve P/L@Stop → 0.
            # Parsed before the stop-value regex so the digits in "+26" aren't read as a stop.
            hypo_add = None
            goal_seek = None
            if re.search(r"\bBE\b", raw):
                goal_seek = 'BE'
                raw = re.sub(r"\bBE\b", "", raw).strip()
            add_m = re.search(r"([+\-]\d+(?:\.\d+)?)", raw)
            if add_m:
                hypo_add = float(add_m.group(1))
                raw = raw.replace(add_m.group(1), "").strip()

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
            
            val_m = re.search(r"([@\$0-9\.%]+)", raw)
            if val_m:
                v = val_m.group(1)
                is_at = v.startswith('@')   # @PRICE T → trailing anchored to exact price
                is_d = v.startswith('$')
                num = float(v[1:] if (is_at or is_d) else (v[:-1] if v.endswith('%') else v))
                if s_type == 'FIXED':
                    f_atr = num  # for FIXED: the value IS the literal stop price
                elif is_at:
                    f_atr = base_p - num    # convert price floor → ATR distance from HWM
                elif v.endswith('%'):
                    f_atr = base_p * (num / 100.0)
                else:
                    f_atr = num  # dollar amount (default; $ prefix is cosmetic)

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

            self.drafts[self.current_conid] = {'atr': f_atr, 'type': s_type, 'ticker': pos.ticker, 'max_r_pct': m_r, 'max_exp_pct': m_e, 'hypo_stop': sl_p, 'inception_atr': save_incep_atr, 'profile': active_preset if active_preset else None, 'tp_atr_mult': tp_final}
            self.query_one("#preset-legend", Label).update(_preset_legend(active_preset))
            self.refresh_risk_checklist(sl_p, f_atr, m_r, m_e, hypo_qty=calc_q, hypo_entry=hypo_entry, hypo_add=hypo_add, goal_seek=goal_seek, hypo_tp_mult=tp_final)
            
        except Exception as e:
            logger.error(f"Modeling Error: {e}")

    def on_key(self, event) -> None:
        if event.key == "ctrl+j":
            if self.current_conid in self.drafts:
                d = self.drafts[self.current_conid]
                set_position_risk(self.current_conid, d['ticker'], d['atr'], d['type'], entry_type='SINGLE', scale_step=0.5, status=('WATCH' if str(self.current_conid).startswith("PROSPECT:") else 'ACTIVE'), max_r_pct=d.get('max_r_pct', 1.0), max_exp_pct=d.get('max_exp_pct', 5.0), reset_sl=True, inception_stop=d.get('hypo_stop'), inception_atr=d.get('inception_atr'), profile=d.get('profile'), tp_atr_mult=d.get('tp_atr_mult'))
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
            set_position_risk(cid, d['ticker'], d['atr'], d['type'], entry_type='SINGLE', scale_step=0.5, status=('WATCH' if str(cid).startswith("PROSPECT:") else 'ACTIVE'), max_r_pct=d.get('max_r_pct', 1.0), max_exp_pct=d.get('max_exp_pct', 5.0), reset_sl=True, inception_stop=d.get('hypo_stop'), inception_atr=d.get('inception_atr'), profile=d.get('profile'), tp_atr_mult=d.get('tp_atr_mult'))
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
