"""Phase 5 — expectancy analytics (read-only) tests.

Acceptance (docs/ClaudeCode_Implementation_Instructions.md Phase 5):
  * report runs off the log;
  * empty/short logs handled gracefully (no errors, sane zeros/None);
  * no effect on the trade flow (pure module — golden master untouched).
"""

import pytest

from core.trade_log import TradeLogEntry, STATUS_TAKEN, STATUS_SKIPPED
from core.expectancy import (
    compute_archetype_expectancy,
    compute_overall_expectancy,
    compute_source_stats,
    compute_base_currency_stats,
    build_expectancy_report,
    suggest_realized_r,
)
from constants import EXPECTANCY_MIN_SAMPLE, EXPECTANCY_THRESHOLD_R


def _taken(archetype="Value reclaim", realized_r=None, source="", **kw):
    return TradeLogEntry(status=STATUS_TAKEN, archetype=archetype, realized_r=realized_r,
                         source=source, **kw)


# --- §7 backfill suggestion (realized R from the ledger) --------------------
def test_suggest_realized_r_winner_and_loser():
    # entry 100, stop 90 -> R1 = 10. Exit 120 = +2R; exit 95 = -0.5R.
    assert suggest_realized_r(100.0, 90.0, 120.0) == pytest.approx(2.0)
    assert suggest_realized_r(100.0, 90.0, 95.0) == pytest.approx(-0.5)


def test_suggest_realized_r_never_fabricates():
    # Missing geometry or a non-positive R1 -> None (manual input), never a guess.
    assert suggest_realized_r(None, 90.0, 120.0) is None
    assert suggest_realized_r(100.0, None, 120.0) is None
    assert suggest_realized_r(100.0, 90.0, None) is None
    assert suggest_realized_r(100.0, 110.0, 120.0) is None   # stop above entry
    assert suggest_realized_r(100.0, 100.0, 120.0) is None   # zero risk


# --- Empty / short logs ----------------------------------------------------
def test_empty_log_is_graceful():
    report = build_expectancy_report([])
    assert report["n_entries"] == 0
    assert report["n_closed"] == 0
    assert report["archetypes"] == []
    assert report["overall"] is None
    assert report["sources"] == []
    assert report["base_ccy"].n == 0
    assert report["base_ccy"].avg_return_base is None


def test_open_trades_without_realized_r_are_not_closed():
    # A logged-but-open trade (no realized_r) contributes nothing to expectancy.
    report = build_expectancy_report([_taken(realized_r=None)])
    assert report["n_entries"] == 1 and report["n_closed"] == 0
    assert report["archetypes"] == []
    assert compute_overall_expectancy([_taken(realized_r=None)]) is None


# --- Expectancy math -------------------------------------------------------
def test_archetype_expectancy_formula():
    # 3 wins (+2R each), 1 loss (-1R): w=0.75, W̄=2, L̄=1 -> E = .75*2 - .25*1 = 1.25R.
    entries = [_taken(realized_r=2.0)] * 3 + [_taken(realized_r=-1.0)]
    stats = compute_archetype_expectancy(entries)
    assert len(stats) == 1
    s = stats[0]
    assert s.n == 4 and s.wins == 3 and s.losses == 1
    assert s.win_rate == pytest.approx(0.75)
    assert s.avg_win_r == pytest.approx(2.0)
    assert s.avg_loss_r == pytest.approx(1.0)
    assert s.expectancy_r == pytest.approx(1.25)
    # E[R] is reported at any n; the VERDICT is not. 4 trades is an anecdote.
    assert s.is_provisional is True
    assert s.above_threshold is False


def test_negative_expectancy_flagged_below_threshold():
    # 1 win (+1R), 3 losses (-1R): w=0.25 -> E = .25*1 - .75*1 = -0.5R.
    entries = [_taken(realized_r=1.0)] + [_taken(realized_r=-1.0)] * 3
    s = compute_archetype_expectancy(entries)[0]
    assert s.expectancy_r == pytest.approx(-0.5)
    assert s.above_threshold is False


# --- Sample-size gate on the verdict ---------------------------------------
def _sample(n, realized_r=2.0, archetype="Value reclaim"):
    return [_taken(archetype=archetype, realized_r=realized_r) for _ in range(n)]


def test_single_lucky_winner_is_never_proven():
    # The failure this gate exists to stop: n=1 at +3R reads E[R] = +3.00R, which
    # would license full size off one trade.
    s = compute_archetype_expectancy(_sample(1, realized_r=3.0))[0]
    assert s.expectancy_r == pytest.approx(3.0)
    assert s.is_provisional is True
    assert s.above_threshold is False
    assert s.n_min_sample == EXPECTANCY_MIN_SAMPLE


def test_verdict_unlocks_exactly_at_the_minimum_sample():
    just_short = compute_archetype_expectancy(_sample(EXPECTANCY_MIN_SAMPLE - 1))[0]
    at_minimum = compute_archetype_expectancy(_sample(EXPECTANCY_MIN_SAMPLE))[0]
    assert just_short.is_provisional is True and just_short.above_threshold is False
    assert at_minimum.is_provisional is False and at_minimum.above_threshold is True


def test_large_sample_below_the_r_threshold_is_still_unproven():
    # Enough evidence, and the evidence says no — a different answer from
    # "not enough evidence", and it must not read as provisional.
    s = compute_archetype_expectancy(_sample(EXPECTANCY_MIN_SAMPLE, realized_r=0.10))[0]
    assert s.expectancy_r == pytest.approx(0.10)
    assert s.is_provisional is False
    assert s.above_threshold is False


def test_sample_size_counts_per_archetype_not_per_book():
    # Two half-sized archetypes do not add up to one proven archetype…
    entries = (_sample(EXPECTANCY_MIN_SAMPLE - 1, archetype="A")
               + _sample(EXPECTANCY_MIN_SAMPLE - 1, archetype="B"))
    assert all(s.is_provisional for s in compute_archetype_expectancy(entries))
    # …though the combined ALL row, which does have the trades, is judged.
    overall = compute_overall_expectancy(entries)
    assert overall.n == 2 * (EXPECTANCY_MIN_SAMPLE - 1)
    assert overall.is_provisional is False
    assert overall.above_threshold is True


def test_report_publishes_the_sample_requirement():
    assert build_expectancy_report([])["min_sample"] == EXPECTANCY_MIN_SAMPLE


def test_breakeven_counts_as_zero_loss():
    # One +2R win, one 0R breakeven (a loser of magnitude 0): w=0.5, W̄=2, L̄=0 -> E=1.0.
    s = compute_archetype_expectancy([_taken(realized_r=2.0), _taken(realized_r=0.0)])[0]
    assert s.wins == 1 and s.losses == 1
    assert s.avg_loss_r == pytest.approx(0.0)
    assert s.expectancy_r == pytest.approx(1.0)


def test_grouping_and_sorting_by_archetype():
    entries = [
        _taken(archetype="Breakout retest", realized_r=-1.0),
        _taken(archetype="Value reclaim", realized_r=3.0),
    ]
    stats = compute_archetype_expectancy(entries)
    # Sorted by E[R] desc -> Value reclaim first.
    assert [s.archetype for s in stats] == ["Value reclaim", "Breakout retest"]


def test_unspecified_archetype_labelled():
    s = compute_archetype_expectancy([_taken(archetype="", realized_r=1.0)])[0]
    assert s.archetype == "(unspecified)"


def test_overall_aggregates_across_archetypes():
    entries = [
        _taken(archetype="A", realized_r=2.0),
        _taken(archetype="B", realized_r=-1.0),
    ]
    o = compute_overall_expectancy(entries)
    assert o.archetype == "ALL" and o.n == 2 and o.total_r == pytest.approx(1.0)


# --- Source funnel ---------------------------------------------------------
def test_source_stats_taken_and_skipped_counts():
    entries = [
        _taken(source="Newsletter X", realized_r=1.5, result_vs_benchmark=0.5),
        _taken(source="Newsletter X", realized_r=-1.0, result_vs_benchmark=-0.2),
        TradeLogEntry(status=STATUS_SKIPPED, source="Newsletter X"),
    ]
    stats = compute_source_stats(entries)
    assert len(stats) == 1
    s = stats[0]
    assert s.source == "Newsletter X"
    assert s.n_taken == 2 and s.n_skipped == 1
    assert s.avg_realized_r == pytest.approx(0.25)
    assert s.avg_vs_benchmark == pytest.approx(0.15)
    assert s.beats_benchmark is True


def test_source_beats_benchmark_none_when_unknown():
    s = compute_source_stats([_taken(source="Tip", realized_r=1.0)])[0]
    assert s.avg_vs_benchmark is None and s.beats_benchmark is None


# --- Base currency ---------------------------------------------------------
def test_base_currency_totals():
    entries = [
        _taken(realized_r=1.0, realized_return_base=1200.0),
        _taken(realized_r=-1.0, realized_return_base=-400.0),
        _taken(realized_r=None, realized_return_base=None),
    ]
    b = compute_base_currency_stats(entries)
    assert b.n == 2
    assert b.total_return_base == pytest.approx(800.0)
    assert b.avg_return_base == pytest.approx(400.0)


def test_threshold_constant_wired():
    # The report exposes the same threshold the archetype flag uses.
    assert build_expectancy_report([])["threshold_r"] == EXPECTANCY_THRESHOLD_R
