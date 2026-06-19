"""Tests for reopen-aware inception healing (PortfolioManager._heal_inception_dates).

When a position goes flat (reset-on-zero) and is reopened, its risk profile still carries the
CLOSED lot's ratchet (highest_sl) and frozen inception. Forcing that stale profile would backdate
the position and drag an old price peak into the high-water mark — fabricating a stop breach
(the AGQ/UGL case). The current ledger lot's date must win, and the stale profile reset.
"""
import pandas as pd
import pytest
from unittest.mock import patch

from core.portfolio_manager import PortfolioManager
from models import Position, RiskProfile


def _pos(date_entry):
    return Position(name="T", ticker="TST", conid="1", asset_class="STK", ccy="USD",
                    date_entry=date_entry, qty=10.0, entry_price=100.0)


def _profile(start_date):
    return RiskProfile(conid="1", ticker="TST", atr_value=90.0, stop_type="TRAILING",
                       highest_sl=104.6, inception_stop=30.0, inception_atr=8.97,
                       start_date=start_date)


def _heal(pos, profile):
    pm = PortfolioManager()
    with patch("core.portfolio_manager.reset_inception_on_reopen") as mock_reset:
        pm._heal_inception_dates([pos], {"1": profile})
    return mock_reset


def test_reopen_resets_stale_profile_and_keeps_ledger_date():
    # Profile dates from a CLOSED lot (older) than the current ledger lot → reopen.
    pos = _pos(pd.Timestamp("2026-06-15"))
    profile = _profile("2026-02-23")
    mock_reset = _heal(pos, profile)

    mock_reset.assert_called_once()                       # DB reset fired
    assert pos.date_entry == pd.Timestamp("2026-06-15")   # ledger date wins
    assert profile.highest_sl == 0.0                      # in-memory ratchet cleared
    assert profile.inception_stop is None
    assert profile.inception_atr is None
    assert profile.start_date == "2026-06-15"             # re-anchored to the new lot


def test_same_date_does_not_reset():
    pos = _pos(pd.Timestamp("2026-06-15"))
    profile = _profile("2026-06-15")
    mock_reset = _heal(pos, profile)
    mock_reset.assert_not_called()
    assert profile.highest_sl == 104.6                    # untouched
    assert pos.date_entry == pd.Timestamp("2026-06-15")


def test_profile_date_newer_than_ledger_wins_without_reset():
    # User-set inception slightly after the ledger entry: honour it, no reset.
    pos = _pos(pd.Timestamp("2026-04-01"))
    profile = _profile("2026-04-05")
    mock_reset = _heal(pos, profile)
    mock_reset.assert_not_called()
    assert pos.date_entry == pd.Timestamp("2026-04-05")
    assert profile.inception_atr == 8.97                  # untouched


def test_no_profile_start_date_is_noop():
    pos = _pos(pd.Timestamp("2026-06-15"))
    profile = _profile(None)
    mock_reset = _heal(pos, profile)
    mock_reset.assert_not_called()
    assert pos.date_entry == pd.Timestamp("2026-06-15")
