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
                        "• [b]Stop P:[/] The active absolute exit price (Base - ATR).\n"
                        "• [b]SL %:[/] Percentage decrease from BASE needed to hit stop.\n"
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
                        "Format: [bold cyan]VALUE [F/T] [S] [Step] [P:S/B/L] [R:MaxR] [E:MaxExp][/]\n\n"
                        "• [b]VALUE:[/] Width of your stop. Numbers are treated as % by default (e.g., '15' = 15%).\n"
                        "• [b][F/T]:[/] Stop Type. 'F' = Fixed. 'T' = Trailing.\n"
                        "• [b][S]:[/] (Optional) Scale-In Flag. Activates the 3-Stage Pilot roadmap.\n"
                        "• [b][Step]:[/] (Optional) Scale-In Multiplier (e.g., 0.5 or 1.0).\n"
                        "• [b][P:S/B/L]:[/] (Optional) Position Sizing Preset (see table below).\n"
                        "• [b][R:MaxR]:[/] (Optional) Override Risk Limit only (e.g., 'R:0.5').\n"
                        "• [b][E:MaxExp]:[/] (Optional) Override Exposure Limit only (e.g., 'E:4.0').\n\n"
                        "[bold yellow]POSITION SIZING PRESETS[/]\n"
                        "Preset sets both E and R as upper limits. Explicit R: or E: after the preset overrides that value only.\n\n"
                        " Preset  │ E (% NAV) │ R (% NAV) │ Crossover stop │ Use case\n"
                        "─────────┼───────────┼───────────┼────────────────┼──────────────────────────\n"
                        " [bold cyan]P:S[/]     │   2.5%    │   0.25%   │      10%       │ Speculative / high-vol\n"
                        " [bold cyan]P:B[/]     │   4.0%    │   0.50%   │     12.5%      │ Standard single-name\n"
                        " [bold cyan]P:L[/]     │   5.0%    │   1.00%   │      20%       │ Large cap / broad index\n\n"
                        "Both R and E are % of total portfolio NAV. The system always uses your actual ATR stop.\n"
                        "[bold]Crossover stop[/] = R ÷ E: the stop distance at which both limits bind simultaneously.\n"
                        "  • ATR stop [bold]tighter[/] than crossover → R is binding, actual exposure < E limit\n"
                        "  • ATR stop [bold]wider[/] than crossover → E is binding, actual R < R limit\n\n"
                        "[bold yellow]PARTIAL UPDATES[/]\n"
                        "You can update metrics individually (e.g., type 'R:0.5' to only change the risk limit).\n\n"
                        "[bold yellow]CONTROLS[/]\n"
                        "• [bold]ENTER:[/] Model hypothetically in the Lab and Grid.\n"
                        "• [bold]CTRL+ENTER:[/] Save permanently to Database.\n"
                    )
                with TabPane("Technical Documentation", id="tab-tech"):
                    yield Static(tech_docs)
            yield Label("Press ESC or F1 to Close", id="close-hint")
