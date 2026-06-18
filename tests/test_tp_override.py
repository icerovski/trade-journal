"""Tests for the `TP:` target-override command resolver (ui.risk_workspace.resolve_tp_mult).

The resolver turns a user token into a multiple of the inception ATR. All four input forms
(R-multiple, % gain, absolute $, clear) plus the unresolvable cases are covered here. Tokens
arrive upper-cased from the input box, so suffixes are tested upper-case.
"""
import pytest

from ui.risk_workspace import resolve_tp_mult, resolve_tp_ratio

ENTRY = 100.0
INC_ATR = 5.0
QTY = 10.0


def test_resolve_plain_multiple():
    mult, clear, ok = resolve_tp_mult("4", ENTRY, INC_ATR, QTY)
    assert ok and not clear and mult == pytest.approx(4.0)


def test_resolve_r_suffix():
    mult, clear, ok = resolve_tp_mult("4R", ENTRY, INC_ATR, QTY)
    assert ok and not clear and mult == pytest.approx(4.0)


def test_resolve_percent():
    # +35% of entry 100 = 35 gain/sh; / inception 5 = 7.0
    for token in ("+35%", "35%"):
        mult, clear, ok = resolve_tp_mult(token, ENTRY, INC_ATR, QTY)
        assert ok and not clear and mult == pytest.approx(7.0)


def test_resolve_absolute_dollar():
    # $600 total / 10 sh = 60/sh; / 5 = 12.0
    mult, clear, ok = resolve_tp_mult("$600", ENTRY, INC_ATR, QTY)
    assert ok and mult == pytest.approx(12.0)


def test_resolve_dollar_k_suffix():
    # $6K = 6000 total / 10 sh = 600/sh; / 5 = 120.0
    mult, clear, ok = resolve_tp_mult("$6K", ENTRY, INC_ATR, QTY)
    assert ok and mult == pytest.approx(120.0)


def test_resolve_dollar_needs_qty():
    """A $ target is unresolvable without a share count."""
    mult, clear, ok = resolve_tp_mult("$600", ENTRY, INC_ATR, 0.0)
    assert not ok


def test_resolve_clear():
    mult, clear, ok = resolve_tp_mult("-", ENTRY, INC_ATR, QTY)
    assert ok and clear and mult is None


def test_resolve_needs_inception_atr():
    """No inception ATR → cannot translate a goal into a multiple."""
    mult, clear, ok = resolve_tp_mult("4", ENTRY, 0.0, QTY)
    assert not ok


def test_resolve_garbage_token():
    mult, clear, ok = resolve_tp_mult("XYZ", ENTRY, INC_ATR, QTY)
    assert not ok


# --- resolve_tp_ratio: N:1 forward reward:risk vs the modeled stop ------------------------

def test_ratio_basic_3to1():
    # price 130, stop 110 → risk/sh = 20; target = 130 + 3×20 = 190; (190−100)/5 = 18.0
    mult, ok = resolve_tp_ratio(3.0, ENTRY, INC_ATR, 130.0, 110.0)
    assert ok and mult == pytest.approx(18.0)


def test_ratio_voo_real_numbers():
    # VOO: entry 526.8087, inception ATR 47.43415, price 688.12, stop 655 → ~5.4956R
    mult, ok = resolve_tp_ratio(3.0, 526.8086739130435, 47.43415409335757, 688.12, 655.0)
    assert ok and mult == pytest.approx(5.4956, abs=1e-3)


def test_ratio_forward_rr_reads_back_as_n():
    # The stored multiple, turned back into a price, must pay exactly N:1 from price→stop.
    ratio, price, stop = 3.0, 130.0, 110.0
    mult, ok = resolve_tp_ratio(ratio, ENTRY, INC_ATR, price, stop)
    target = ENTRY + mult * INC_ATR
    assert (target - price) / (price - stop) == pytest.approx(ratio)


def test_ratio_price_at_or_below_stop_unresolvable():
    assert resolve_tp_ratio(3.0, ENTRY, INC_ATR, 110.0, 110.0)[1] is False
    assert resolve_tp_ratio(3.0, ENTRY, INC_ATR, 100.0, 110.0)[1] is False


def test_ratio_needs_inception_atr():
    assert resolve_tp_ratio(3.0, ENTRY, 0.0, 130.0, 110.0)[1] is False


def test_ratio_non_positive_ratio_unresolvable():
    assert resolve_tp_ratio(0.0, ENTRY, INC_ATR, 130.0, 110.0)[1] is False
