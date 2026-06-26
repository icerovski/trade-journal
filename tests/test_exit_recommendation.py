"""Tests for `_exit_recommendation` — the single source of truth for the profit-taking
directive. It drives BOTH the one-line verdict (panel header + table ACTION column) and the
detailed exit-guidance prose, so these cases guard against the two ever diverging.
"""
import pytest

from ui.risk_workspace import _exit_recommendation, _trim_shares


def _rec(stage, regime, rr=2.0, stop_type='FIXED', qty=100.0, entry=100.0, sl=95.0,
         tp=115.0, cur_p=112.0):
    return _exit_recommendation(stage, regime, qty, entry, sl, tp, cur_p, rr, stop_type)


def test_no_stage_returns_none():
    assert _rec('', 'NORMAL') is None
    assert _rec('PRE-M1', 'NORMAL') is None  # PRE-M1 has no matrix entry → no directive


def test_m1_risk_free_when_stop_above_entry():
    rec = _rec('M1', 'NORMAL', sl=105.0)   # stop already above entry (100)
    assert rec['verb'] == 'HOLD'
    assert rec['shares'] == 0


def test_m1_move_stop_to_entry_when_stop_below():
    rec = _rec('M1', 'NORMAL', sl=92.0)
    assert rec['verb'] == 'STOP→ENTRY'
    assert rec['restore_sl'] == 100.0       # raise stop to entry
    assert rec['shares'] == 0


def test_m1_exempt_from_rr_floor():
    """A sub-1.0 RR at M1 is the expected result of raising the stop to entry, not an exit."""
    rec = _rec('M1', 'NORMAL', rr=0.4, sl=92.0)
    assert rec['verb'] == 'STOP→ENTRY'      # not EXIT


def test_m2_trend_is_hold():
    rec = _rec('M2', 'TREND')
    assert rec['verb'] == 'HOLD'
    assert rec['pct'] == 0.0


def test_m2_normal_trims_a_third():
    rec = _rec('M2', 'NORMAL', qty=100.0)
    assert rec['verb'] == 'TRIM'
    assert rec['pct'] == pytest.approx(0.33)
    assert rec['shares'] == 33


def test_tp_ranging_full_exit_via_matrix():
    rec = _rec('TP', 'RANGING', qty=50.0)   # rr healthy → matrix, not RR floor
    assert rec['verb'] == 'TRIM'
    assert rec['pct'] == 1.0
    assert rec['shares'] == 50


def test_low_rr_does_not_force_exit_fixed_tp_normal():
    """RR < 1.0 no longer forces an exit: the directive follows the TRIM_MATRIX. RR is
    informational only (shown in the PLAN panel), never a trigger."""
    rec = _rec('TP', 'NORMAL', rr=0.5, cur_p=112.0, tp=115.0)
    assert rec['verb'] == 'TRIM'
    assert rec['pct'] == pytest.approx(0.33)
    assert rec['urgent'] is False


def test_low_rr_ranging_tp_is_matrix_full_exit():
    """TP in RANGING is a full exit via the matrix (verb TRIM, pct 1.0), independent of RR."""
    rec = _rec('TP', 'RANGING', rr=0.5, qty=50.0)
    assert rec['verb'] == 'TRIM'
    assert rec['pct'] == 1.0
    assert rec['shares'] == 50


def test_low_rr_identical_for_fixed_and_trailing():
    """Stop type no longer changes the directive — RR is not a trigger for either."""
    fixed = _rec('TP', 'NORMAL', rr=0.5, stop_type='FIXED')
    trailing = _rec('TP', 'NORMAL', rr=0.5, stop_type='TRAILING')
    assert fixed['verb'] == trailing['verb'] == 'TRIM'
    assert fixed['pct'] == trailing['pct'] == pytest.approx(0.33)


def test_trim_shares_never_rounds_a_real_trim_to_zero():
    assert _trim_shares(3, 0.20) == 1       # round(0.6)=1, not 0
    assert _trim_shares(100, 0.50) == 50
    assert _trim_shares(100, 1.0) == 100    # never exceeds holdings
