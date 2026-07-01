"""Phase 6 — gap-aware sizing (opt-in) tests.

Acceptance (docs/ClaudeCode_Implementation_Instructions.md Phase 6):
  * default fixed-fractional sizing unchanged;
  * the gap path is covered by tests.

Gap-aware sizing risks against the LARGER of R₁ and R_gap (= the lower of the
structural stop and the plausible gap price), so it can only shrink the size.
"""

import pytest

from core.sizing import (
    compute_position_size,
    compute_position_size_gap,
    gap_effective_stop,
)


# --- The opt-in switch reduces to the default when off ---------------------
def test_gap_none_matches_default_sizing():
    args = (1_000_000, 100.0, 90.0, 1.0, 1.0, 5.0)
    assert compute_position_size_gap(1_000_000, 100.0, 90.0, None, 1.0, 1.0, 5.0) \
        == compute_position_size(*args)


def test_gap_above_stop_does_not_change_size():
    # A gap price ABOVE the stop is not more conservative -> default distance kept.
    default = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 1.0, 5.0)
    gapped = compute_position_size_gap(1_000_000, 100.0, 90.0, 95.0, 1.0, 1.0, 5.0)
    assert gapped == default


def test_gap_effective_stop_picks_lower():
    assert gap_effective_stop(90.0, 85.0) == 85.0   # gap below stop -> use gap
    assert gap_effective_stop(90.0, 95.0) == 90.0   # gap above stop -> use stop
    assert gap_effective_stop(90.0, None) == 90.0   # off -> use stop


# --- Gap below the stop widens R and shrinks size --------------------------
def test_gap_below_stop_shrinks_size():
    # R₁ = 10, R_gap = 20 -> qty must roughly halve for the same risk. Exposure cap
    # set non-binding (100%) so the risk cap is what drives the size.
    default = compute_position_size(1_000_000, 100.0, 90.0, 1.0, 1.0, 100.0)
    gapped = compute_position_size_gap(1_000_000, 100.0, 90.0, 80.0, 1.0, 1.0, 100.0)
    assert gapped < default
    assert gapped == pytest.approx(default / 2, rel=0.02)


def test_gap_sizing_matches_manual_r_gap():
    # Explicit check against qty = risk_budget$ / R_gap under the risk cap.
    nav, entry, stop, gap = 1_000_000, 200.0, 190.0, 170.0
    max_r, max_exp = 0.5, 100.0  # exposure cap deliberately non-binding
    r_gap = entry - gap  # 30
    expected = int((nav * (max_r / 100.0)) / r_gap)
    assert compute_position_size_gap(nav, entry, stop, gap, 1.0, max_r, max_exp) == expected


def test_gap_still_respects_exposure_clamp():
    # Even with a huge R_gap, exposure cap can bind; sizing never exceeds it.
    nav, entry, stop, gap = 1_000_000, 100.0, 99.0, 10.0
    exp_capped = compute_position_size(nav, entry, 0.0, 1.0, 999.0, 2.0)  # exposure-only ref
    gapped = compute_position_size_gap(nav, entry, stop, gap, 1.0, 999.0, 2.0)
    assert gapped == exp_capped
