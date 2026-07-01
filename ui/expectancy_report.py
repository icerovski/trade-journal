"""Expectancy Report (menu option 9) — read-only view over the decision journal.

Renders per-archetype expectancy, source-vs-benchmark funnel stats, and base-currency
totals from `trade_log`. Display-only: it never writes and never touches the trade
flow. Mirrors the rich-console style of ui/portfolio_risk.py.
"""

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from db import get_trade_log_entries
from core.expectancy import build_expectancy_report

console = Console()


def _r_str(value, suffix="R", none="---"):
    return f"{value:+.2f}{suffix}" if value is not None else none


def run_expectancy_report():
    entries = get_trade_log_entries()
    report = build_expectancy_report(entries)

    header = (
        f"{report['n_entries']} journal rows  │  "
        f"{report['n_closed']} closed trades  │  "
        f"{report['n_skipped']} skipped picks"
    )
    console.print(Panel(header, title="[bold]EXPECTANCY REPORT[/bold]", border_style="blue"))

    if report["n_entries"] == 0:
        console.print(
            "\n[yellow]The trade log is empty.[/yellow] Log trades (and skipped picks) "
            "from the Risk Workspace to build expectancy — see §7."
        )
        input("\nPress Enter to return to menu...")
        return

    threshold = report["threshold_r"]

    # ── Per-archetype expectancy ──────────────────────────────────────────────
    console.print(f"\n[bold]EXPECTANCY BY ARCHETYPE[/bold]  [dim](threshold E[R] > {threshold:+.2f}R)[/dim]")
    if not report["archetypes"]:
        console.print("[dim]No closed trades yet (need realized R).[/dim]")
    else:
        t = Table(box=box.SIMPLE_HEAD)
        t.add_column("Archetype", style="cyan", min_width=16)
        t.add_column("N", justify="right")
        t.add_column("Win%", justify="right")
        t.add_column("Avg Win", justify="right")
        t.add_column("Avg Loss", justify="right")
        t.add_column("E[R]", justify="right")
        t.add_column("", justify="left")
        for s in report["archetypes"]:
            e_color = "green" if s.above_threshold else ("yellow" if s.expectancy_r > 0 else "red")
            verdict = "[green]proven[/]" if s.above_threshold else "[yellow]unproven — starter size[/]"
            t.add_row(
                s.archetype, str(s.n), f"{s.win_rate*100:.0f}%",
                f"+{s.avg_win_r:.2f}R", f"-{s.avg_loss_r:.2f}R",
                f"[{e_color}]{s.expectancy_r:+.2f}R[/]", verdict,
            )
        if report["overall"]:
            o = report["overall"]
            t.add_row(
                "[bold]ALL[/]", f"[bold]{o.n}[/]", f"[bold]{o.win_rate*100:.0f}%[/]",
                f"+{o.avg_win_r:.2f}R", f"-{o.avg_loss_r:.2f}R",
                f"[bold]{o.expectancy_r:+.2f}R[/]", "",
            )
        console.print(t)

    # ── Source funnel (§0a) ───────────────────────────────────────────────────
    console.print("\n[bold]SOURCE vs BENCHMARK[/bold]  [dim](is the funnel adding edge?)[/dim]")
    if not report["sources"]:
        console.print("[dim]No sourced picks logged.[/dim]")
    else:
        st = Table(box=box.SIMPLE_HEAD)
        st.add_column("Source", style="cyan", min_width=16)
        st.add_column("Taken", justify="right")
        st.add_column("Skipped", justify="right")
        st.add_column("Avg R", justify="right")
        st.add_column("vs Bench", justify="right")
        st.add_column("Avg Ret (base)", justify="right")
        for s in report["sources"]:
            if s.beats_benchmark is True:
                vb = f"[green]{_r_str(s.avg_vs_benchmark)}[/]"
            elif s.beats_benchmark is False:
                vb = f"[red]{_r_str(s.avg_vs_benchmark)}[/]"
            else:
                vb = "---"
            st.add_row(
                s.source, str(s.n_taken), str(s.n_skipped),
                _r_str(s.avg_realized_r),
                vb,
                f"{s.avg_return_base:,.0f}" if s.avg_return_base is not None else "---",
            )
        console.print(st)

    # ── Base currency ─────────────────────────────────────────────────────────
    b = report["base_ccy"]
    if b.n:
        avg = f"{b.avg_return_base:,.0f}" if b.avg_return_base is not None else "---"
        console.print(
            f"\n[bold]BASE-CURRENCY RETURN[/bold]  "
            f"total [bold]{b.total_return_base:,.0f}[/] over {b.n} closed  (avg {avg})"
        )

    input("\nPress Enter to return to menu...")
