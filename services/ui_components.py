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
                            "• [b][bold red]⚠[/][/]: [bold red]LIMIT EXCEEDED.[/] Risk or Exposure above your Max limit.\n"
                            "• [b][reverse red] STALE [/][/]: [bold red]DEAD MONEY.[/] Held ≥180d but annual return below the 8% hurdle.\n"
                            "    [dim]e.g. 'Return: +1.7% total · +1%/yr · 637d  STALE' → review or redeploy.[/]\n"
                            "• [b][reverse magenta] MODELING [/][/]: a what-if scenario in the PLAN section (nothing saved).\n"
                            "    [dim]e.g. type 'BE' → 'MODELING: ADD 26 SHARES (P/L@Stop → 0) @ 696.05'.[/]\n\n"
                            "[bold cyan]COLOR METRICS[/]\n"
                            "• [b]Risk (% NAV):[/] [green]< Max R[/] | [yellow]Max R - 1.5x Max R[/] | [red]> 1.5x Max R[/]\n"
                            "    [dim]e.g. limit 1.0%: 0.6% green, 1.2% yellow, 1.8% red.[/]\n"
                            "• [b]RR (Efficiency):[/] [green]> 3.0[/] | [yellow]1.0 - 3.0[/] | [red]< 1.0[/]\n"
                            "    [dim]e.g. RR 0.75 (red) = more downside to stop than upside to target.[/]\n"
                        )
                with TabPane("Metrics & Audit", id="tab-metrics"):
                    with ScrollableContainer(classes="help-scroll"):
                        yield Static(
                            "[bold cyan]RISK DEFINITIONS[/]\n"
                            "• [b]Inception Stop:[/] The 'Point of Origin'. Historical stop set at your first entry using the volatility (ATR) of that date. Immutable anchor for R-Multiplier auditing.\n"
                            "• [b]Pilot Stop:[/] The 'Roadmap Destination'. The stop price for the [b]entire aggregate position[/] if you were to add shares at current prices.\n"
                            "• [b]Stop Base:[/] Reference point (Avg Cost for Fixed | Max High for Trailing).\n"
                            "• [b]Stop P:[/] Active exit price. Fixed: the literal price you set. Trailing: High − ATR.\n"
                            "    [dim]e.g. Trailing: High 700 − ATR 88 = Stop 612.[/]\n"
                            "• [b]SL %:[/] Fixed: entry→stop distance as % of entry. Trailing: ATR as % of High.\n"
                            "• [b]R (% NAV):[/] Risk at Stop. Total potential loss as a % of your portfolio. Negative when the stop is above entry (a stop-out is profitable).\n"
                            "    [dim]e.g. VOO stop above entry → R = −0.13% (cannot lose at this stop).[/]\n"
                            "• [b]RR (Efficiency):[/] (TP − Price) / (Price − Stop), where TP = entry + 3×R and R is the inception ATR. RR < 1.0 trips the efficiency floor [b]on FIXED stops only[/] — a trailing stop's exit is the stop itself, not a fixed target.\n"
                            "    [dim]e.g. (532 − 478) / (478 − 406) = 0.75 → upside < downside.[/]\n\n"
                            "[bold cyan]RETURN & CAPITAL EFFICIENCY[/]\n"
                            "• [b]Return (total):[/] Unrealised gain since the true first entry, price-only.\n"
                            "    [dim]e.g. VOO entry 520 → 696 = +33.8% total.[/]\n"
                            "• [b]AAGR (per yr):[/] The return annualised. Tagged 'prelim' and dimmed under 180 days held — too short a window to annualise meaningfully.\n"
                            "    [dim]e.g. +34% over 56d annualises to a meaningless '+533%/yr prelim'.[/]\n"
                            "• [b][reverse red] STALE [/][/]: Held ≥ 180 days yet AAGR < 8% hurdle — capital not clearing its opportunity cost. Bonds/bills are exempt (price-only ignores their coupon).\n"
                            "    [dim]e.g. a name flat for 2 years: 'Return: +1.7% · +1%/yr · 637d  STALE'.[/]\n\n"
                            "[bold cyan]DUAL-CONSTRAINT AUDIT[/]\n"
                            "• [b]Risk Limit (Default 1.0%):[/] Potential Loss from Entry to Stop.\n"
                            "• [b]Exposure Limit (Default 5.0%):[/] Total Position Value limit.\n"
                            "    [dim]e.g. the tighter of the two binds — VOO is capped by Exposure (4.94% of 5.0%), so only ~3 more shares are allowed.[/]\n"
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
                        "  [bold cyan]VALUE [F/T]  [P:S/B/L]  [R:x]  [E:x]  [TP:n]  [+N/-N]  [BE][/]\n\n"
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
                        "  TP is anchored to [bold]entry + 3×ATR[/] (same uniform ladder as Fixed).\n\n"
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

                        "[bold cyan]─── TAKE-PROFIT TARGET (TP:n) ───────────────────────────────────────[/]\n\n"
                        "By default the target is [bold]entry + 3×ATR[/] (3R), anchored to the ATR stored\n"
                        "at first save (the Inception ATR). Once a winner runs past 3R the ladder is\n"
                        "maxed out — [bold]TP:n[/] lets you extend the target to a higher multiple of that\n"
                        "SAME frozen ATR, so it stays reachable and does NOT drift when you later tighten\n"
                        "the stop. The M1/M2 milestones always stay at +1R / +2R for reference.\n\n"
                        "Four ways to set it — all resolve to a multiple of the Inception ATR:\n\n"
                        "  [bold]1. R-multiple (most direct):[/]\n"
                        "  [dim]  TP:4           → target = entry + 4×Inception ATR\n"
                        "  TP:4R          → same (the R is optional)[/]\n\n"
                        "  [bold]2. Percent gain from entry:[/]\n"
                        "  [dim]  TP:+35%        → target = entry +35%; multiple = (entry×35%)/ATR[/]\n\n"
                        "  [bold]3. Absolute profit (needs a share count):[/]\n"
                        "  [dim]  TP:$60K        → target where total open profit = $60,000\n"
                        "  TP:$60000      → same (K = thousands)[/]\n\n"
                        "  [bold]4. Clear — revert to the default 3R:[/]\n"
                        "  [dim]  TP:-           → removes the override[/]\n\n"
                        "[bold]The 3:1 guardrail.[/] When an override is in force the panel shows a\n"
                        "[bold]TARGET[/] line with the FORWARD reward:risk — (target − price)/(price − stop) —\n"
                        "i.e. what you are paid to keep holding [bold]from here[/]. It flags [bold red]⚠ below 3:1[/]\n"
                        "if that ratio drops under 3.0, so you can size the target deliberately. Note a\n"
                        "run-up winner whose stop already sits above entry will naturally read low — the\n"
                        "forward ratio is the honest measure once entry risk is gone.\n\n"
                        "  [dim]  TP:5R          → e.g. VOO: TARGET 5.0R → 763.98, fwd RR flagged vs 3.0[/]\n\n"

                        "[bold cyan]─── QUANTITY MODELING (what-if, nothing saved) ──────────────────────[/]\n\n"
                        "These let you test buying/selling at the [bold]current market price[/] and watch\n"
                        "the sizing table update P/L@Stop, R%, Exp%, HCM and the new average cost.\n\n"
                        "[bold]+N / -N — model adding / trimming N shares[/]\n"
                        "  [dim]  +26            → model buying 26 more shares at the live price\n"
                        "  -50            → model selling 50 shares[/]\n\n"
                        "[bold]BE — goal-seek: how many shares to buy so P/L@Stop = 0[/]\n"
                        "  Solves the buy that pulls your average cost onto the stop, so a stop-out\n"
                        "  would break even. The sizing table shows the effect — watch Exp%: it may\n"
                        "  turn red if the required size breaches your exposure limit. If break-even\n"
                        "  can't be reached by buying (avg already past the stop), it says so.\n"
                        "  [dim]  BE             → e.g. VOO: 'ADD 26 SHARES (P/L@Stop → 0)'[/]\n\n"

                        "[bold cyan]─── COMBINED EXAMPLES ───────────────────────────────────────────────[/]\n\n"
                        "  [dim]20.31 T P:B     → trailing $20.31, standard preset\n"
                        "  @156 T P:L      → trailing floor at 156, large-cap preset\n"
                        "  5% T R:0.5      → trailing 5%, custom risk limit of 0.5%\n"
                        "  156 F           → fixed stop at 156, no preset change\n"
                        "  18.13 T TP:4R   → tighten trailing stop AND extend the target to 4R\n"
                        "  TP:+35%         → set only the target to +35% from entry\n"
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
                        "[bold cyan]── THE STRATEGY IN ONE PAGE ─────────────────────────────────────────────[/]\n\n"
                        "Two independent questions govern every open position:\n\n"
                        "  1. [bold]Should I take profit?[/]  Driven by the EXIT LADDER (how much profit,\n"
                        "     in ATR units) crossed with the TREND REGIME (is there structural support\n"
                        "     to keep riding). This decides whether to hold, trim, or close.\n\n"
                        "  2. [bold]Is this capital working?[/]  Driven by CAPITAL EFFICIENCY — annualised\n"
                        "     unrealised return versus an opportunity-cost hurdle. This is orthogonal\n"
                        "     to the ladder: a position can be perfectly placed on the ladder yet still\n"
                        "     be dead money tying up the book.\n\n"
                        "The stop loss is always the ultimate backstop. The ladder and regime only\n"
                        "decide how much you bank on the way up; they never widen your risk.\n\n"

                        "[bold cyan]── TREND REGIME ───────────────────────────────────────────────────────[/]\n\n"
                        "The regime controls how aggressively you take profits. TREND requires BOTH:\n"
                        "  1. The 200-DMA rising for ≥ 21 consecutive days, and\n"
                        "  2. Current price above the 200-DMA (not a pullback below the key level).\n\n"
                        " Regime  │ 200-DMA Rising Days │ Price vs DMA  │ Trim M2 │ Trim TP\n"
                        "─────────┼─────────────────────┼───────────────┼─────────┼──────────────\n"
                        " [green]TREND[/]   │ ≥ 21                │ Above         │ [bold]Hold[/]    │ 20% + raise TP\n"
                        " [white]NORMAL[/]  │ 10–20, or ≥21 below │ Below (pull)  │ 33%     │ 33% or close\n"
                        " [red]RANGING[/] │ < 10 or declining   │ —             │ 50%     │ Close all\n\n"

                        "[bold]What each regime means for your action:[/]\n\n"
                        "  [bold green]TREND[/] — Structural support confirmed. [bold]Do not trim at M2[/]: trimming a\n"
                        "  confirmed compounder cuts the winner. Let the trailing stop run the position\n"
                        "  and bank profit at the full target (TP). At TP, take a 20% slice and raise\n"
                        "  the TP to pursue the larger structural move.\n\n"
                        "  [bold white]NORMAL[/] — The trend is developing, or the position has pulled back below\n"
                        "  the 200-DMA despite a long-rising DMA. Standard profit-taking: take a third\n"
                        "  at each milestone and re-evaluate.\n\n"
                        "  [bold red]RANGING[/] — No structural support. The DMA is flat or falling. Protect\n"
                        "  gains aggressively: take half at M2 and close everything at TP.\n\n"

                        "[bold]How the 200-DMA signal is counted (and reversal hysteresis):[/]\n\n"
                        "  DMA direction = sign of (today's DMA − yesterday's DMA). Because the DMA\n"
                        "  averages 200 sessions, one bad day barely moves it. The system counts\n"
                        "  consecutive days the DMA has moved the same way without reversal.\n\n"
                        "  That count [bold]resets to ~1 on any reversal[/], so a single counter-trend day\n"
                        "  would otherwise crash a long TREND straight to RANGING. To dampen that\n"
                        "  whipsaw, a fresh reversal (down-run shorter than 3 days) is treated as\n"
                        "  [bold]unconfirmed[/] and the regime is held one notch up at NORMAL. Only once the\n"
                        "  reversal persists ≥ 3 days does the regime demote to RANGING. The PLAN\n"
                        "  panel labels this case 'DMA reversed Nd (< 3, unconfirmed) → held at NORMAL'.\n\n"

                        "[bold cyan]── EXIT STAGES ─────────────────────────────────────────────────────────[/]\n\n"
                        "Milestones form a uniform ladder anchored to entry for BOTH stop types:\n"
                        "M1 = entry + 1×R, M2 = entry + 2×R, TP = entry + 3×R, where R is the\n"
                        "[bold]Inception ATR[/] — the original risk you took at entry. Profit is therefore\n"
                        "measured in R-multiples. For a trailing stop the live ATR only sets where the\n"
                        "STOP sits; it does not move the reward ladder (which would otherwise drift\n"
                        "away as volatility expands and mislabel a healthy winner).\n\n"
                        " Stage    │ Trigger                  │ Action\n"
                        "──────────┼──────────────────────────┼──────────────────────────────────\n"
                        " [dim]PRE-M1[/]  │ price < entry + 1×ATR    │ Hold — stop is the only exit\n"
                        " [cyan]M1[/]      │ price ≥ entry + 1×ATR    │ Move stop to entry (risk-free)\n"
                        " [yellow]M2[/]      │ price ≥ entry + 2×ATR    │ Trim by regime (TREND = hold)\n"
                        " [green]TP[/]      │ price ≥ entry + 3×ATR    │ Larger trim by regime\n\n"

                        "[bold]What to do at each stage:[/]\n\n"
                        "  [dim]PRE-M1[/]  Not yet earned one full ATR of profit. Normal early development.\n"
                        "          Do nothing — the stop is the only exit mechanism.\n\n"
                        "  [cyan]M1[/]      One ATR banked. Move the stop to entry. Do not sell. This makes\n"
                        "          the position risk-free — you exit at break-even at worst. House money.\n\n"
                        "  [yellow]M2[/]      Two ATRs banked. Action depends on regime: [bold]TREND = hold (no trim)[/],\n"
                        "          NORMAL = trim ~33%, RANGING = trim ~50%. Share counts are shown in\n"
                        "          the PLAN section. The stop and TP still govern the rest.\n\n"
                        "  [green]TP[/]      Three ATRs from entry — the initial target is hit.\n"
                        "          RANGING: close everything — no structural reason to hold.\n"
                        "          TREND: take a 20% slice and raise the TP to chase the larger move.\n"
                        "          NORMAL: close ~33%; keep a runner only if RR is still > 1.0.\n"
                        "          In all cases, the trailing stop remains the ultimate exit.\n\n"

                        "[bold cyan]── EFFICIENCY FLOOR (RR < 1.0, FIXED stops only) ──────────────────────[/]\n\n"
                        "RR = (TP − current price) ÷ (current price − stop). Below 1.0, the upside\n"
                        "left to the target is smaller than the downside to the stop — you are risking\n"
                        "more than you stand to gain. Applies at M2/TP only (a sub-1.0 RR at M1 is the\n"
                        "expected result of raising the stop to entry, not a sell signal).\n\n"
                        "  [bold red]RANGING[/] — Exit all shares. With no structural support, tightening the\n"
                        "  stop to manufacture RR ≥ 1.0 just invites a whipsaw exit at a worse price.\n\n"
                        "  [bold]TREND / NORMAL[/] — Two defensible paths: exit all shares, OR raise the stop\n"
                        "  to restore RR ≥ 1.0 (the panel prints the exact level, 2·P − TP). If the stop\n"
                        "  is already above entry, a stop-out is still profitable.\n\n"
                        "  [bold]TRAILING stops are exempt.[/] A trailing stop has no real target — its exit\n"
                        "  IS the stop, and the +3R level is only a checkpoint. A low RR there is an\n"
                        "  artifact of a fixed target vs a stop trailing on the (wider) live ATR, so it\n"
                        "  never forces an exit. You manage a trailing position by the stop; the ladder\n"
                        "  and regime trims are the profit-taking overlay.\n\n"

                        "[bold cyan]── CAPITAL EFFICIENCY (DEAD MONEY) ─────────────────────────────────────[/]\n\n"
                        "Independent of the ladder. It asks whether the capital is earning its keep.\n"
                        "A position is flagged [bold reverse red] STALE [/] when BOTH hold:\n"
                        "  • Held ≥ 180 days (below this, annualised return is too noisy to judge), and\n"
                        "  • Annualised unrealised return (AAGR) < 8% (the opportunity-cost hurdle).\n\n"
                        "It is [bold]not[/] an automatic exit — it is a prompt to review the thesis or redeploy\n"
                        "the capital into something working harder. The PLAN panel always shows the\n"
                        "'Capital: ±x% AAGR over Nd' metric, and adds a '⏳ STALE … review or redeploy'\n"
                        "nudge when triggered (suppressed on a stop breach, where exit already dominates).\n\n"
                        "Bonds and bills are excluded: AAGR is price-only and would understate a\n"
                        "coupon-earning hold. (Thresholds live in constants.py.)\n\n"

                        "[bold cyan]── DASHBOARD EXIT COLUMN ───────────────────────────────────────────────[/]\n"
                        "  [dim]blank[/]       PRE-M1 — no action required\n"
                        "  [cyan]M1[/]         Move stop to entry price — no trimming\n"
                        "  [yellow]M2·T/N/R[/]   Trim due  T=hold  N=33%  R=50%\n"
                        "  [green]TP·T/N/R[/]   Full target hit   T=20%+raise TP  N=33%  R=close all\n"
                        "  [red]⚠ RR<1.0[/]  Efficiency floor — exit (RANGING) or exit/tighten (TREND/NORMAL)\n"
                        "  Regime: T=Trend  N=Normal  R=Ranging\n"
                        "Full breakdown with share counts is in the Risk Workspace PLAN section.\n"
                    )
                with TabPane("Technical Documentation", id="tab-tech"):
                    with ScrollableContainer(classes="help-scroll"):
                        yield Static(tech_docs)
            yield Label("Press ESC or F1 to Close", id="close-hint")
