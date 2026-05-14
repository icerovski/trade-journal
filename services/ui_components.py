from textual.app import ComposeResult
from textual.widgets import Label, Static, TabbedContent, TabPane
from textual.containers import Vertical, ScrollableContainer
from textual.binding import Binding
from textual.screen import ModalScreen

class HelpScreen(ModalScreen):
    """An overlay screen providing definitions and shortcuts."""
    BINDINGS = [Binding("escape,f1", "dismiss", "Close")]

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-modal {
        width: 90%;
        height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        height: 1fr;
        padding: 0;
    }
    .help-scroll {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    """

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
                    with ScrollableContainer(classes="help-scroll"):
                        yield Static(
                            "[bold cyan]TABLE ICONS[/]\n"
                            "• [b][T/F/-][/]: Stop type (Trailing, Fixed, None)\n"
                            "• [b][bold yellow]*[/][/]: Unsaved draft in the Sandbox\n\n"
                            "[bold cyan]ACTION TRIGGERS[/]\n"
                            "• [b][on red] Price [/][/]: [bold red]EMERGENCY.[/] Stop breached. Exit position.\n"
                            "• [b][bold cyan]★[/][/]: [bold cyan]TAKE PROFIT HIT.[/] Price reached 3x ATR target.\n"
                            "• [b][bold red]⚠[/][/]: [bold red]LIMIT EXCEEDED.[/] Risk or Exposure above your Max limit.\n\n"
                            "[bold cyan]COLOR METRICS[/]\n"
                            "• [b]Risk (% NAV):[/] [green]< Max R[/] | [yellow]Max R - 1.5x Max R[/] | [red]> 1.5x Max R[/]\n"
                            "• [b]RR (Efficiency):[/] [green]> 3.0[/] | [yellow]1.0 - 3.0[/] | [red]< 1.0[/]\n"
                        )
                with TabPane("Metrics & Audit", id="tab-metrics"):
                    with ScrollableContainer(classes="help-scroll"):
                        yield Static(
                            "[bold cyan]RISK DEFINITIONS[/]\n"
                            "• [b]Inception Stop:[/] The 'Point of Origin'. Historical stop set at your first entry using the volatility (ATR) of that date. Immutable anchor for R-Multiplier auditing.\n"
                            "• [b]Pilot Stop:[/] The 'Roadmap Destination'. The stop price for the [b]entire aggregate position[/] if you were to add shares at current prices.\n"
                            "• [b]Stop Base:[/] Reference point (Avg Cost for Fixed | Max High for Trailing).\n"
                            "• [b]Stop P:[/] Active exit price. Fixed: the literal price you set. Trailing: High − ATR.\n"
                            "• [b]SL %:[/] Fixed: entry→stop distance as % of entry. Trailing: ATR as % of High.\n"
                            "• [b]R (% NAV):[/] Risk at Stop. Total potential loss as a % of your portfolio.\n"
                            "• [b]RR (Efficiency):[/] Reward-to-Risk Ratio. (TP - Price) / (Price - Stop).\n\n"
                            "[bold cyan]DUAL-CONSTRAINT AUDIT[/]\n"
                            "• [b]Risk Limit (Default 1.0%):[/] Potential Loss from Entry to Stop.\n"
                            "• [b]Exposure Limit (Default 5.0%):[/] Total Position Value limit.\n"
                        )
                with TabPane("Watch List & Entry", id="tab-watchlist"):
                    with ScrollableContainer(classes="help-scroll"):
                        yield Static(
                            "[bold yellow]THE WATCH LIST LIFECYCLE[/]\n"
                            "1. [b]Drafting:[/] Type a ticker in the 'Discover' input to research its ATR volatility.\n"
                            "2. [b]Commit to Watch:[/] Press [bold cyan]Ctrl+Enter[/] to save the strategy to the Watch List.\n"
                            "3. [b]Monitoring:[/] The ticker stays on watch (marked [PROSPECT]) until you buy it or delete it.\n"
                            "4. [b]Auto-Promotion:[/] When a real trade is ingested via IBKR sync, the system detects it and promotes the [WATCH] profile to [ACTIVE] status automatically.\n\n"
                            "[bold yellow]ENTRY TIMING DECISIONS[/]\n"
                            "• Watch List items show current price relative to your modeled stops.\n"
                            "• Look for [bold green]RR > 3.0[/] and favorable [bold]Buffer%[/] to determine entry quality.\n"
                        )
                with TabPane("Strategy Lab", id="tab-syntax"):
                    with ScrollableContainer(classes="help-scroll"):
                        yield Static(
                        "[bold cyan]═══ HOW TO ENTER A STOP LOSS ════════════════════════════════════════[/]\n\n"

                        "The input box accepts a command in this form:\n"
                        "  [bold cyan]VALUE [F/T]  [P:S/B/L]  [R:x]  [E:x][/]\n\n"
                        "The tokens can appear in any order. Only the parts you want to change\n"
                        "are required — everything else is preserved from the saved profile.\n\n"

                        "[bold cyan]─── STOP TYPE ───────────────────────────────────────────────────────[/]\n\n"

                        "[bold]F — Fixed stop (absolute price)[/]\n"
                        "  You type the exact price where the stop sits. The system never moves\n"
                        "  it automatically. To raise it later, type the new price and Ctrl+Enter.\n"
                        "  The ratchet prevents accidental lowering: re-saving a lower stop price\n"
                        "  than the current one is ignored unless you explicitly intend it.\n"
                        "  TP is anchored to [bold]entry + 3×ATR[/] (ATR stored at first save — Inception ATR).\n\n"
                        "  [dim]  156 F          → stop locked at 156.00\n"
                        "  96.50 F        → stop locked at 96.50[/]\n\n"

                        "[bold]T — Trailing stop (distance from the high)[/]\n"
                        "  You type the gap between the high-water mark (HIGH P) and the stop.\n"
                        "  The stop auto-follows the highest price since entry; it never retreats.\n"
                        "  TP is anchored to [bold]ratcheted stop + 3×ATR[/] so it rises with the position.\n\n"
                        "  Three ways to express the distance:\n\n"
                        "  [bold]1. Dollar amount (default)[/] — the most direct:\n"
                        "  [dim]  20.31 T        → stop = HIGH P − 20.31[/]\n"
                        "  [dim]  $8 T           → stop = HIGH P − 8.00  ($ prefix is optional)[/]\n\n"
                        "  [bold]2. Percentage of HIGH P:[/]\n"
                        "  [dim]  5% T           → stop = HIGH P − 5% of HIGH P[/]\n\n"
                        "  [bold]3. Target price (@ prefix) — let the system calculate the gap:[/]\n"
                        "  You know where you want the stop floor; you don't want to do the maths.\n"
                        "  Type [bold]@PRICE T[/] and the system sets ATR distance = HIGH P − PRICE.\n"
                        "  HIGH P is shown in the grid (column after CUR P).\n"
                        "  [dim]  @156 T         → if HIGH P = 187.83, sets ATR distance = 31.83[/]\n"
                        "  [dim]  @150 T         → if HIGH P = 187.83, sets ATR distance = 37.83[/]\n\n"
                        "  Note: all three forms of T honour the ratchet — if the resulting stop is\n"
                        "  lower than the already-saved stop, the ratchet keeps the higher one.\n\n"

                        "[bold cyan]─── POSITION SIZING OVERRIDES ───────────────────────────────────────[/]\n\n"
                        "[bold]P:S / P:B / P:L — Presets (set R and E together)[/]\n"
                        " Preset │ Exposure (E) │ Risk (R) │ Crossover stop │ Use case\n"
                        "────────┼──────────────┼──────────┼────────────────┼──────────────────────\n"
                        " [bold cyan]P:S[/]    │     3.0% NAV │  0.50%   │     16.7%      │ Speculative / high-vol\n"
                        " [bold cyan]P:B[/]    │     4.0% NAV │  0.75%   │    18.75%      │ Standard single-name\n"
                        " [bold cyan]P:L[/]    │     5.0% NAV │  1.00%   │      20%       │ Large cap / broad index\n\n"
                        "[bold]Crossover stop[/] = R ÷ E. At that ATR distance both limits bind simultaneously.\n"
                        "  Tighter stop → R is the binding constraint, exposure stays under E.\n"
                        "  Wider stop  → E is the binding constraint, actual R stays under R limit.\n\n"
                        "[bold]R:x — Override risk limit only[/]\n"
                        "  [dim]  R:0.5          → max 0.5% of NAV at risk (keeps current E)[/]\n\n"
                        "[bold]E:x — Override exposure limit only[/]\n"
                        "  [dim]  E:4.0          → max 4% of NAV in the position (keeps current R)[/]\n\n"

                        "[bold cyan]─── COMBINED EXAMPLES ───────────────────────────────────────────────[/]\n\n"
                        "  [dim]20.31 T P:B     → trailing $20.31, standard preset\n"
                        "  @156 T P:L      → trailing floor at 156, large-cap preset\n"
                        "  5% T R:0.5      → trailing 5%, custom risk limit of 0.5%\n"
                        "  156 F           → fixed stop at 156, no preset change\n"
                        "  R:0.5           → change only the risk limit, keep everything else[/]\n\n"

                        "[bold cyan]─── R COMPLIANCE RESTORE ────────────────────────────────────────────[/]\n\n"
                        "When risk is YELLOW or RED the execution desk shows two paths:\n"
                        "  [bold]A) Raise stop → [price][/]\n"
                        "     The minimum stop needed to restore compliance at the current qty.\n"
                        "     For FIXED: type that price and Ctrl+Enter.\n"
                        "     For TRAILING: type [bold]@[price] T[/] and Ctrl+Enter.\n"
                        "  [bold]B) Trim [N] shares[/]\n"
                        "     Shares to sell so the risk at the current stop falls within R limit.\n\n"

                        "[bold cyan]─── CONTROLS ────────────────────────────────────────────────────────[/]\n\n"
                        "  [bold]ENTER[/]        Model hypothetically — updates grid without saving.\n"
                        "  [bold]CTRL+ENTER[/]   Commit permanently to the database.\n"
                        "  [bold]S[/]            Save all pending drafts at once.\n"
                    )
                with TabPane("Exit Strategy", id="tab-exit"):
                    with ScrollableContainer(classes="help-scroll"):
                        yield Static(
                        "[bold cyan]── TREND REGIME ───────────────────────────────────────────────────────[/]\n\n"
                        "The regime controls how aggressively you take profits. It is determined by\n"
                        "two conditions that must both be true to qualify as TREND:\n"
                        "  1. The 200-DMA has been rising for a minimum number of consecutive days.\n"
                        "  2. The current price is above the 200-DMA (confirms the position is\n"
                        "     still inside the trend, not in a pullback below the key level).\n\n"
                        " Regime  │ 200-DMA Rising Days │ Price vs DMA  │ Trim M2 │ Trim TP\n"
                        "─────────┼─────────────────────┼───────────────┼─────────┼──────────────\n"
                        " [green]TREND[/]   │ ≥ 21                │ Above         │ 15%     │ 20% + raise TP\n"
                        " [white]NORMAL[/]  │ 10 – 20, or ≥ 21    │ Below (any)   │ 33%     │ 33% or close\n"
                        "         │   but below DMA     │               │         │\n"
                        " [red]RANGING[/] │ < 10 or declining   │ —             │ 50%     │ Close all\n\n"

                        "[bold]What each regime means for your action:[/]\n\n"
                        "  [bold green]TREND[/] — Structural support confirmed. Trim only a small slice at each\n"
                        "  milestone to reduce exposure lightly. The bulk of the position should stay\n"
                        "  on to capture the continuation of the structural move.\n\n"
                        "  [bold white]NORMAL[/] — The trend is developing or the position has pulled back below\n"
                        "  the 200-DMA despite a long-rising DMA. Standard profit-taking applies:\n"
                        "  take a meaningful third at each milestone and re-evaluate.\n\n"
                        "  [bold red]RANGING[/] — No structural support. The DMA is flat or falling. Protect\n"
                        "  gains aggressively: take half at M2 and close everything at TP.\n\n"

                        "[bold]How the 200-DMA signal is counted:[/]\n\n"
                        "  The DMA direction = sign of (today's DMA − yesterday's DMA). Because the\n"
                        "  DMA is an average of 200 sessions, a single bad day barely moves it —\n"
                        "  the other 199 days offset it. The system counts consecutive days where\n"
                        "  the DMA has moved in the same direction without reversal. At ≥ 21 days\n"
                        "  (approximately one calendar month of uninterrupted movement) AND price\n"
                        "  above the DMA, the regime qualifies as TREND.\n\n"

                        "[bold cyan]── EXIT STAGES ─────────────────────────────────────────────────────────[/]\n\n"
                        " Stage    │ Trigger                     │ ATR anchor             │ Action\n"
                        "──────────┼─────────────────────────────┼────────────────────────┼──────────────────────\n"
                        " [dim]PRE-M1[/]  │ price < entry + 1×ATR       │ —                      │ Hold\n"
                        " [cyan]M1[/]      │ price ≥ entry + 1×ATR       │ Fixed: Inception ATR   │ Move stop to entry\n"
                        " [yellow]M2[/]      │ price ≥ entry + 2×ATR       │ Trailing: live distance│ Partial trim by regime\n"
                        " [green]TP[/]      │ price ≥ entry + 3×ATR       │ (same as above)        │ Larger trim by regime\n\n"

                        "[bold]What to do at each stage:[/]\n\n"
                        "  [dim]PRE-M1[/]  The position has not yet earned one full ATR of profit from entry.\n"
                        "          This is normal early development. Do nothing — the stop is the\n"
                        "          only exit mechanism. Let the position work.\n\n"
                        "  [cyan]M1[/]      One ATR of profit is in the bank. Move your stop loss to the entry\n"
                        "          price. Do not sell any shares. This single action makes the\n"
                        "          position risk-free: no matter what happens next, you exit at\n"
                        "          break-even at worst. You are now playing with house money.\n\n"
                        "  [yellow]M2[/]      Two ATRs of profit banked. Take partial profits — the exact\n"
                        "          percentage depends on the regime (see table above). The share\n"
                        "          count is shown in the sidebar and the EXIT MILESTONES panel.\n"
                        "          Keep the remainder running; the stop and TP still govern the exit.\n\n"
                        "  [green]TP[/]      Three ATRs of profit from entry. The full initial target is hit.\n"
                        "          In RANGING: close everything — there is no structural reason to hold.\n"
                        "          In TREND: take a further 20% slice and raise the TP to\n"
                        "          stop + 3×weekly ATR to pursue the larger structural move.\n"
                        "          In NORMAL: close 33%; keep a runner only if RR is still > 1.0.\n"
                        "          In all cases, the trailing stop remains the ultimate exit.\n\n"

                        "[bold cyan]── EFFICIENCY FLOOR (RR < 1.0) ─────────────────────────────────────────[/]\n\n"
                        "This rule overrides all stages and regime guidance. If the RR ratio (Reward\n"
                        "to Risk) drops below 1.0 at any point after M1, exit all remaining shares\n"
                        "immediately.\n\n"
                        "RR = (TP − current price) ÷ (current price − stop)\n\n"
                        "When RR falls below 1.0, it means the distance remaining to your target is\n"
                        "smaller than the distance to your stop. You are risking more than you can\n"
                        "gain. This typically fires when price reverses sharply from the TP zone back\n"
                        "toward the stop. There is no regime exception — exit in full.\n\n"

                        "[bold cyan]── DASHBOARD EXIT COLUMN ───────────────────────────────────────────────[/]\n"
                        "  [dim]blank[/]       PRE-M1 — no action required\n"
                        "  [cyan]M1[/]         Move stop to entry price — no trimming\n"
                        "  [yellow]M2·T/N/R[/]   Partial trim due  T=15%  N=33%  R=50%\n"
                        "  [green]TP·T/N/R[/]   Full target hit   T=20%+raise TP  N=33%  R=close all\n"
                        "  [red]⚠ RR<1.0[/]  Efficiency floor — exit all shares now\n"
                        "  Regime: T=Trend  N=Normal  R=Ranging\n"
                        "Full breakdown with share counts is in the Risk Workspace PLAN section.\n"
                    )
                with TabPane("Technical Documentation", id="tab-tech"):
                    with ScrollableContainer(classes="help-scroll"):
                        yield Static(tech_docs)
            yield Label("Press ESC or F1 to Close", id="close-hint")
