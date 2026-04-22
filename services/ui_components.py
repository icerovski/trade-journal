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
                        "• [b]\\[/S][/]: Scale-In Strategy is active\n"
                        "• [b][bold yellow]*[/][/]: Unsaved draft in the Sandbox\n\n"
                        "[bold cyan]ACTION TRIGGERS[/]\n"
                        "• [b][on red] Price [/][/]: [bold red]EMERGENCY.[/] Stop breached. Exit position.\n"
                        "• [b][bold cyan]★[/][/]: [bold cyan]TAKE PROFIT HIT.[/] Price reached 3x ATR target.\n"
                        "• [b][bold green]⬆[/][/]: [bold green]SCALE-IN TRIGGERED.[/] Add shares to reach next stage.\n"
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
                        "  [bold cyan]VALUE [F/T] [S/S0] [Step] [P:S/B/L] [R:x] [E:x][/]\n\n"
                        "• [b][S]:[/]    Scale-In flag. Activates the 3-stage Pilot Entry roadmap.\n"
                        "• [b][S0]:[/]   Disable Scale-In — revert to single Standard entry.\n"
                        "• [b][Step]:[/] Scale-In step multiplier (e.g. 0.5 or 1.0 × ATR between stages).\n"
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
                with TabPane("Technical Documentation", id="tab-tech"):
                    yield Static(tech_docs)
            yield Label("Press ESC or F1 to Close", id="close-hint")
