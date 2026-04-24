from textual.app import ComposeResult
from textual.widgets import Label, Static, TabbedContent, TabPane
from textual.containers import Vertical
from textual.binding import Binding
from textual.screen import ModalScreen

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
                    yield Static(
                        "[bold cyan]STOP TYPES[/]\n"
                        "• [bold]F — Fixed (Absolute Price):[/] You enter a specific price. The system uses it exactly\n"
                        "  and never moves it automatically — not for price action, not for new buys, not for trims.\n"
                        "  The ratchet prevents accidental regression: re-saving a lower price requires explicit intent.\n"
                        "  TP is calculated from Inception ATR (stored at first save). To raise the stop manually,\n"
                        "  simply type the new price and press Ctrl+Enter.\n"
                        "  [dim]Example: [bold]96.50 F[/] → stop locked at 96.50[/]\n\n"
                        "• [bold]T — Trailing (ATR Distance):[/] You enter the distance. Stop auto-follows the\n"
                        "  highest high since entry, ratcheted so it never retreats.\n"
                        "  Value is a % of the High by default; prefix [bold]$[/] for a dollar amount.\n"
                        "  [dim]Example: [bold]5% T[/] → stop = High − 5%  |  [bold]$8 T[/] → stop = High − $8[/]\n\n"
                        "[bold cyan]FULL SYNTAX[/]\n"
                        "  [bold cyan]VALUE [F/T] [P:S/B/L] [R:x] [E:x][/]\n\n"
                        "• [b][P:S/B/L]:[/] Position sizing preset (see table). Sets both R and E together.\n"
                        "• [b][R:x]:[/]  Override Risk limit only (e.g. R:0.5 = max 0.5% NAV at stop).\n"
                        "• [b][E:x]:[/]  Override Exposure limit only (e.g. E:4.0 = max 4% NAV in position).\n"
                        "Tokens can be combined in any order. Partial updates work: 'R:0.5' alone\n"
                        "changes only the risk limit and preserves the rest of the saved strategy.\n\n"
                        "[bold cyan]POSITION SIZING PRESETS[/]\n"
                        " Preset  │ E (% NAV) │ R (% NAV) │ Crossover stop │ Use case\n"
                        "─────────┼───────────┼───────────┼────────────────┼──────────────────────────\n"
                        " [bold cyan]P:S[/]     │   3.0%    │   0.50%   │     16.7%      │ Speculative / high-vol\n"
                        " [bold cyan]P:B[/]     │   4.0%    │   0.75%   │    18.75%      │ Standard single-name\n"
                        " [bold cyan]P:L[/]     │   5.0%    │   1.00%   │      20%       │ Large cap / broad index\n\n"
                        "[bold]Crossover stop[/] = R ÷ E: the ATR distance at which both limits bind simultaneously.\n"
                        "  • Stop tighter than crossover → R is binding, exposure stays below E limit.\n"
                        "  • Stop wider than crossover  → E is binding, actual R stays below R limit.\n\n"
                        "[bold cyan]R COMPLIANCE RESTORE[/]\n"
                        "When risk exceeds your R limit (YELLOW/RED), the execution desk shows two remediation paths:\n"
                        "  [bold]A) Raise stop → [price][/]  Minimum stop needed to restore compliance at current qty.\n"
                        "     For FIXED stops: type that price and Ctrl+Enter to lock it in.\n"
                        "  [bold]B) Trim [N] shares[/]       Shares to sell to restore compliance at the current stop.\n\n"
                        "[bold cyan]CONTROLS[/]\n"
                        "• [bold]ENTER:[/]       Model hypothetically — updates grid and execution desk without saving.\n"
                        "• [bold]CTRL+ENTER:[/]  Save permanently to database.\n"
                        "• [bold]S (key):[/]     Save All drafts at once.\n"
                    )
                with TabPane("Exit Strategy", id="tab-exit"):
                    yield Static(
                        "[bold cyan]── TREND REGIME ───────────────────────────────────────────────────────[/]\n\n"
                        " Regime  │ Q/W ATR Ratio  │ 200-DMA Signal  │ Trim M2 │ Trim TP\n"
                        "─────────┼────────────────┼─────────────────┼─────────┼─────────────\n"
                        " [green]TREND[/]   │ > 4.5          │ BUY (≥ 21d)     │ 15%     │ 20%\n"
                        " [white]NORMAL[/]  │ 3.0 – 4.5      │ BUY (≥ 21d)     │ 33%     │ 33% or close\n"
                        " [red]RANGING[/] │ < 3.0  OR      │ Not BUY         │ 50%     │ Close all\n\n"
                        "RANGING fires if EITHER condition fails. Both must be true for TREND or NORMAL.\n\n"

                        "[bold]What each regime means:[/]\n\n"
                        "  [bold green]TREND[/]\n"
                        "  Both signals are positive. Weekly moves are additive — each week pushes\n"
                        "  further in the same direction rather than giving back ground. The 200-DMA\n"
                        "  has been rising uninterrupted for at least a month. The position is in a\n"
                        "  genuine trend. Trim conservatively to preserve the runway.\n\n"
                        "  [bold white]NORMAL[/]\n"
                        "  The 200-DMA confirms the trend structure is intact, but the ATR ratio\n"
                        "  is in the neutral zone — weekly moves are neither strongly additive nor\n"
                        "  canceling. Standard profit-taking applies.\n\n"
                        "  [bold red]RANGING[/]\n"
                        "  At least one signal has failed. Either weekly moves are canceling each\n"
                        "  other (the quarterly bar ends up small relative to weekly noise), or the\n"
                        "  200-DMA has not confirmed a sustained direction. The position has less\n"
                        "  structural support. Protect gains more aggressively.\n\n"

                        "[bold]How each signal is calculated:[/]\n\n"
                        "  Signal 1 — Q/W ATR Ratio  (quarterly ATR ÷ weekly ATR)\n"
                        "  A quarter holds ~13 weekly bars. In a random walk, weekly moves partially\n"
                        "  cancel, so quarterly ATR ≈ √13 × weekly ATR ≈ 3.5×. When the ratio\n"
                        "  exceeds 4.5, weekly moves are additive — the structural signature of a\n"
                        "  trend. Both ATRs use Wilder's method over a 12-period window.\n\n"
                        "  Signal 2 — 200-DMA Direction\n"
                        "  The daily change in the 200-DMA = (today's close − close 200 days ago) ÷ 200.\n"
                        "  Because it averages 200 days, a single bad session barely moves it — the\n"
                        "  other 199 days offset it. The signal counts how many consecutive days the\n"
                        "  DMA has moved in the same direction without a single reversal. At 21+ days\n"
                        "  (≈ 1 month of uninterrupted movement) it fires BUY or SELL. Otherwise NEUTRAL.\n\n"

                        "[bold cyan]── EXIT STAGES ─────────────────────────────────────────────────────────[/]\n\n"
                        " Stage    │ Trigger                │ ATR used             │ Action\n"
                        "──────────┼────────────────────────┼──────────────────────┼────────────────────────\n"
                        " [dim]PRE-M1[/]  │ price < entry + 1×ATR  │ —                    │ Hold\n"
                        " [cyan]M1[/]      │ price ≥ entry + 1×ATR  │ Fixed: Inception ATR │ Raise stop to entry\n"
                        " [yellow]M2[/]      │ price ≥ entry + 2×ATR  │ Trailing: live width │ Partial trim by regime\n"
                        " [green]TP[/]      │ price ≥ stop + 3×ATR   │ (same as above)      │ Larger trim by regime\n\n"
                        "What each stage means:\n\n"
                        "  [dim]PRE-M1[/]  The position hasn't yet earned one full ATR of profit. Normal\n"
                        "          development. The stop is the only exit mechanism.\n\n"
                        "  [cyan]M1[/]      One ATR of profit gained. The cost of staying in the trade is\n"
                        "          now zero — raising the stop to entry makes this a free position.\n"
                        "          No trimming yet; just lock in the no-loss floor.\n\n"
                        "  [yellow]M2[/]      Two ATRs of profit. Enough cushion to take partial profits while\n"
                        "          keeping the majority of the position running. How much to take\n"
                        "          depends on the regime — in a strong trend, trim only 15% so the\n"
                        "          bulk stays on for the continuation.\n\n"
                        "  [green]TP[/]      The position has delivered its full 3×ATR target. In a ranging\n"
                        "          market, close it. In a trend, take 20% more off and extend the\n"
                        "          target to stop + 3×weekly ATR to capture the larger move.\n"
                        "          The trailing stop remains the ultimate exit in all cases.\n\n"

                        "[bold cyan]── EFFICIENCY FLOOR ────────────────────────────────────────────────────[/]\n"
                        "Overrides all stages. If RR (Efficiency) drops below 1.0 at any time,\n"
                        "exit all remaining shares. This fires when price reverses toward the stop\n"
                        "from the TP zone — the remaining reward no longer justifies the open risk.\n\n"

                        "[bold cyan]── DASHBOARD EXIT COLUMN ───────────────────────────────────────────────[/]\n"
                        "  [dim]blank[/]       PRE-M1 — no action\n"
                        "  [cyan]M1[/]         Raise stop to entry\n"
                        "  [yellow]M2·T/N/R[/]   Trim signal  T=15%  N=33%  R=50%\n"
                        "  [green]TP·T/N/R[/]   Target hit   T=20%  N=33%  R=close\n"
                        "Full breakdown with share counts is in the Risk Workspace PLAN section.\n"
                    )
                with TabPane("Technical Documentation", id="tab-tech"):
                    yield Static(tech_docs)
            yield Label("Press ESC or F1 to Close", id="close-hint")
