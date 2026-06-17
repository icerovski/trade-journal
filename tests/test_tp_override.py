"""Tests for the `TP:` target-override command resolver (ui.risk_workspace.resolve_tp_mult).

The resolver turns a user token into a multiple of the inception ATR. All four input forms
(R-multiple, % gain, absolute $, clear) plus the unresolvable cases are covered here. Tokens
arrive upper-cased from the input box, so suffixes are tested upper-case.
"""
import pytest

from ui.risk_workspace import resolve_tp_mult

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
