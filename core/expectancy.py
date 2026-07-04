"""Expectancy analytics (Entry & Stop System §5, §7) — pure, read-only.

Turns the decision journal (`trade_log`) into the numbers that decide whether an
archetype is worth trading at all:

    E[R] = w · W̄  −  (1 − w) · L̄

where w = win rate, W̄ = average win in R, L̄ = average loss in R. It also answers
the funnel question (§0a): does a *source* beat its benchmark, and it aggregates
realized return in the book's base currency.

This module performs no I/O and does not touch the trade flow — callers pass a list
of `TradeLogEntry` (from `db.get_trade_log_entries()`). Empty/short logs are handled
gracefully: everything degrades to zero counts and `None` averages, never an error.

Convention: a winner is `realized_r > 0`; a loser is `realized_r <= 0` (a breakeven
counts, conservatively, as a zero-magnitude loss), so wins + losses always == n.
"""

from dataclasses import dataclass
from typing import Optional

from constants import EXPECTANCY_THRESHOLD_R
from core.trade_log import STATUS_TAKEN, STATUS_SKIPPED


@dataclass
class ArchetypeStats:
    archetype: str
    n: int              # closed trades (realized_r present)
    wins: int
    losses: int
    win_rate: float     # w
    avg_win_r: float    # W̄  (mean realized_r over winners; 0 if none)
    avg_loss_r: float   # L̄  (mean |realized_r| over losers; 0 if none)
    expectancy_r: float  # E[R]
    total_r: float
    above_threshold: bool  # E[R] > EXPECTANCY_THRESHOLD_R


@dataclass
class SourceStats:
    source: str
    n_taken: int
    n_skipped: int
    avg_realized_r: Optional[float]
    avg_vs_benchmark: Optional[float]   # mean result_vs_benchmark over taken trades
    avg_return_base: Optional[float]
    beats_benchmark: Optional[bool]     # avg_vs_benchmark > 0 (None when unknown)


@dataclass
class BaseCurrencyStats:
    n: int
    total_return_base: float
    avg_return_base: Optional[float]


def _mean(values) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def suggest_realized_r(entry: Optional[float], stop: Optional[float],
                       avg_exit: Optional[float]) -> Optional[float]:
    """Suggested realized R for a closed lot's §7 backfill:
    (avg_exit − entry) / R₁, with R₁ = entry − stop from the journal row.
    None when the geometry can't support it (missing entry/stop/exit, or a
    non-positive R₁) — the caller falls back to manual input, never fabricates."""
    if not entry or not stop or not avg_exit:
        return None
    r1 = entry - stop
    if r1 <= 0:
        return None
    return (avg_exit - entry) / r1


def _closed_taken(entries):
    """TAKEN trades with a realized R (i.e. closed and measurable)."""
    return [e for e in entries
            if (e.status or STATUS_TAKEN) == STATUS_TAKEN and e.realized_r is not None]


def _archetype_stats(archetype: str, rows) -> ArchetypeStats:
    realized = [e.realized_r for e in rows]
    winners = [r for r in realized if r > 0]
    losers = [r for r in realized if r <= 0]
    n = len(realized)
    w = (len(winners) / n) if n else 0.0
    avg_win = (sum(winners) / len(winners)) if winners else 0.0
    avg_loss = (sum(abs(r) for r in losers) / len(losers)) if losers else 0.0
    expectancy = w * avg_win - (1 - w) * avg_loss
    return ArchetypeStats(
        archetype=archetype or "(unspecified)",
        n=n, wins=len(winners), losses=len(losers),
        win_rate=w, avg_win_r=avg_win, avg_loss_r=avg_loss,
        expectancy_r=expectancy, total_r=sum(realized),
        above_threshold=expectancy > EXPECTANCY_THRESHOLD_R,
    )


def compute_archetype_expectancy(entries) -> list[ArchetypeStats]:
    """Per-archetype expectancy over closed TAKEN trades, sorted by E[R] desc."""
    groups: dict[str, list] = {}
    for e in _closed_taken(entries):
        groups.setdefault(e.archetype or "", []).append(e)
    stats = [_archetype_stats(arch, rows) for arch, rows in groups.items()]
    stats.sort(key=lambda s: s.expectancy_r, reverse=True)
    return stats


def compute_overall_expectancy(entries) -> Optional[ArchetypeStats]:
    """Single expectancy row across every closed TAKEN trade (archetype = ALL)."""
    rows = _closed_taken(entries)
    if not rows:
        return None
    return _archetype_stats("ALL", rows)


def compute_source_stats(entries) -> list[SourceStats]:
    """Per-source funnel stats — taken vs skipped counts, average realized R,
    average result-vs-benchmark, and average base-currency return."""
    sources: dict[str, list] = {}
    for e in entries:
        sources.setdefault(e.source or "", []).append(e)

    out = []
    for source, rows in sources.items():
        taken = [e for e in rows if (e.status or STATUS_TAKEN) == STATUS_TAKEN]
        skipped = [e for e in rows if e.status == STATUS_SKIPPED]
        avg_vs = _mean(e.result_vs_benchmark for e in taken)
        out.append(SourceStats(
            source=source or "(unspecified)",
            n_taken=len(taken),
            n_skipped=len(skipped),
            avg_realized_r=_mean(e.realized_r for e in taken),
            avg_vs_benchmark=avg_vs,
            avg_return_base=_mean(e.realized_return_base for e in taken),
            beats_benchmark=(avg_vs > 0) if avg_vs is not None else None,
        ))
    out.sort(key=lambda s: (s.avg_vs_benchmark if s.avg_vs_benchmark is not None else -1e9), reverse=True)
    return out


def compute_base_currency_stats(entries) -> BaseCurrencyStats:
    """Aggregate realized return in the book's base currency over TAKEN trades."""
    returns = [e.realized_return_base for e in entries
               if (e.status or STATUS_TAKEN) == STATUS_TAKEN and e.realized_return_base is not None]
    total = sum(returns)
    return BaseCurrencyStats(
        n=len(returns),
        total_return_base=total,
        avg_return_base=(total / len(returns)) if returns else None,
    )


def build_expectancy_report(entries) -> dict:
    """One call for the whole report. Safe on an empty list."""
    entries = list(entries or [])
    return {
        "n_entries": len(entries),
        "n_closed": len(_closed_taken(entries)),
        "n_skipped": sum(1 for e in entries if e.status == STATUS_SKIPPED),
        "archetypes": compute_archetype_expectancy(entries),
        "overall": compute_overall_expectancy(entries),
        "sources": compute_source_stats(entries),
        "base_ccy": compute_base_currency_stats(entries),
        "threshold_r": EXPECTANCY_THRESHOLD_R,
    }
