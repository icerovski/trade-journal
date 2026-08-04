"""Expectancy Report (menu option 9) — the decision journal's front door.

Renders per-archetype expectancy, source-vs-benchmark funnel stats, and base-currency
totals from `trade_log`, then offers the §7 capture loop: backfill realized R on
closed lots (ledger-suggested, user-confirmed) and log skipped source picks. These
are the only journal writes here — the report itself stays a pure read. Mirrors the
rich-console style of ui/portfolio_risk.py.
"""

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

from datetime import date

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from db import (
    get_trade_log_entries,
    update_trade_log_entry,
    add_trade_log_entry,
    avg_sell_price_since,
)
from core.expectancy import build_expectancy_report, suggest_realized_r
from core.trade_log import TradeLogEntry, STATUS_TAKEN, STATUS_SKIPPED

console = Console()


def _r_str(value, suffix="R", none="---"):
    return f"{value:+.2f}{suffix}" if value is not None else none


def _closed_lots_awaiting_backfill():
    """Open journal rows (TAKEN, realized_r NULL) whose position is no longer
    open — the lot closed, the decision's outcome is measurable."""
    pending = [e for e in get_trade_log_entries(status=STATUS_TAKEN)
               if e.realized_r is None and e.conid]
    if not pending:
        return []
    from core.portfolio_manager import PortfolioManager
    try:
        open_conids = {str(p.conid) for p in PortfolioManager().get_open_positions_hybrid()}
    except Exception as e:
        console.print(f"[red]Could not load open positions ({e}) — backfill unavailable.[/red]")
        return []
    return [e for e in pending if str(e.conid) not in open_conids]


def _backfill_closed_lots():
    """§7 realized-R backfill: suggest (avg ledger SELL − entry) / R₁ per closed
    lot; the user confirms, overrides, or skips. Never writes unconfirmed."""
    lots = _closed_lots_awaiting_backfill()
    if not lots:
        console.print("[dim]No closed lots awaiting backfill.[/dim]")
        return
    for e in lots:
        avg_exit = avg_sell_price_since(e.conid, e.date)
        sug = suggest_realized_r(e.entry, e.stop, avg_exit)
        geo = f"entry {e.entry:,.2f} / stop {e.stop:,.2f}" if e.entry and e.stop else "geometry incomplete"
        if sug is not None:
            console.print(f"\n[bold]{e.ticker}[/] ({e.date}, {geo}) — avg exit {avg_exit:,.2f} "
                          f"→ suggested realized R [bold]{sug:+.2f}[/]")
        else:
            console.print(f"\n[bold]{e.ticker}[/] ({e.date}, {geo}) — no ledger suggestion; enter manually.")
        raw = input("  realized R [Enter=accept suggestion / value / s=skip]: ").strip().lower()
        if raw == "s" or (raw == "" and sug is None):
            continue
        try:
            val = sug if raw == "" else float(raw)
        except ValueError:
            console.print("  [red]Not a number — skipped.[/red]")
            continue
        update_trade_log_entry(e.id, realized_r=round(val, 4))
        console.print(f"  [green]Saved: {e.ticker} realized R {val:+.2f}[/green]")


def _log_skipped_pick():
    """§0a: log a source pick that was NOT taken, so the funnel itself can be
    benchmarked. Entry price auto-resolved when Yahoo cooperates."""
    ticker = input("  Ticker: ").strip().upper()
    if not ticker:
        console.print("  [yellow]No ticker — cancelled.[/yellow]")
        return
    source = input("  Source [Stansberry]: ").strip() or "Stansberry"
    note = input("  Note (optional): ").strip()
    price = None
    try:
        from core.portfolio_manager import PortfolioManager
        from services.market_data_service import silence_yfinance
        import yfinance as yf
        yf_t = PortfolioManager().mapper.resolve_yf_ticker(ticker)
        with silence_yfinance():
            price = float(yf.Ticker(yf_t).fast_info["last_price"])
    except Exception:
        price = None
    add_trade_log_entry(TradeLogEntry(
        date=date.today().isoformat(), ticker=ticker, status=STATUS_SKIPPED,
        source=source, entry=price, notes=note,
    ))
    px = f"@ {price:,.2f}" if price else "(no price resolved)"
    console.print(f"  [green]Logged skipped pick: {ticker} from {source} {px}[/green]")


def _journal_actions(n_pending: int):
    """§7 capture loop — the only journal writes in this view."""
    while True:
        hint = f"  [yellow][B] backfill {n_pending} closed lot(s)[/yellow]" if n_pending else "  [dim][B] backfill closed lots[/dim]"
        console.print(f"\n{hint}  [dim][K] log skipped pick   [Enter] back to menu[/dim]")
        choice = input("Choice: ").strip().lower()
        if choice == "b":
            _backfill_closed_lots()
            n_pending = len(_closed_lots_awaiting_backfill())
        elif choice == "k":
            _log_skipped_pick()
        else:
            return


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
            "\n[yellow]The trade log is empty.[/yellow] Tag commits with C: in the Risk "
            "Workspace, and log skipped picks here ([K] below) to build expectancy — see §7."
        )
        _journal_actions(0)
        return

    threshold = report["threshold_r"]

    # ── Per-archetype expectancy ──────────────────────────────────────────────
    min_sample = report.get("min_sample", 0)
    console.print(
        f"\n[bold]EXPECTANCY BY ARCHETYPE[/bold]  "
        f"[dim](proven = E[R] > {threshold:+.2f}R over at least {min_sample} closed trades)[/dim]"
    )
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
            # Three states, not two: too few trades to judge is a different answer
            # from judged and found wanting, and must not be coloured like a verdict.
            if s.is_provisional:
                e_color = "dim"
                verdict = f"[dim]provisional — {s.n}/{s.n_min_sample} trades[/]"
            elif s.above_threshold:
                e_color = "green"
                verdict = "[green]proven[/]"
            else:
                e_color = "yellow" if s.expectancy_r > 0 else "red"
                verdict = "[yellow]unproven — starter size[/]"
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

    _journal_actions(len(_closed_lots_awaiting_backfill()))
