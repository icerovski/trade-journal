"""Phase 8 — horizon calibration profile tests.

Acceptance (docs/ClaudeCode_Implementation_Instructions.md Phase 8):
  * default profile → scan output identical to passing no calibration (Phase-0 behaviour);
  * selecting position_3to6mo changes parameters as specified (incl. the MOMENTUM override);
  * both covered by tests; the profile adds NO time stop (lens only).
"""

from dataclasses import fields

import numpy as np
import pandas as pd
import pytest

import db
from core.zone_scan import scan_ticker
from core.calibration import (
    get_calibration,
    DEFAULT_CALIBRATION,
    POSITION_3TO6MO,
    CalibrationProfile,
)

PRESETS = {
    "S": {"label": "Small", "max_r_pct": 0.30, "max_exp_pct": 1.5},
    "B": {"label": "Base", "max_r_pct": 0.60, "max_exp_pct": 3.0},
    "L": {"label": "Large", "max_r_pct": 1.00, "max_exp_pct": 5.0},
}


def _sine_ohlcv(n=300, center=100.0, amp=2.0, period=15.0):
    t = np.arange(n)
    close = center + amp * np.sin(t / period)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": np.full(n, 1000.0),
    })


def _momentum_ohlcv():
    ramp = np.linspace(50.0, 195.0, 270)
    pullback = np.linspace(195.0, 178.0, 30)
    close = np.concatenate([ramp, pullback])
    n = len(close)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": np.full(n, 1000.0),
    })


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------
def test_get_calibration_resolves_names():
    assert get_calibration("default") is DEFAULT_CALIBRATION
    assert get_calibration("position_3to6mo") is POSITION_3TO6MO
    assert get_calibration("POSITION_3TO6MO") is POSITION_3TO6MO


def test_get_calibration_unknown_falls_back_to_default():
    assert get_calibration("bogus") is DEFAULT_CALIBRATION
    assert get_calibration("") is DEFAULT_CALIBRATION
    assert get_calibration(None) is DEFAULT_CALIBRATION


# --------------------------------------------------------------------------
# Default profile is behaviourally a no-op
# --------------------------------------------------------------------------
def test_default_calibration_matches_no_calibration_normal():
    df = _sine_ohlcv(center=100.0)
    a = scan_ticker(df, 1_000_000, PRESETS, ticker="X", current_price=100.0)
    b = scan_ticker(df, 1_000_000, PRESETS, ticker="X", current_price=100.0,
                    calibration=DEFAULT_CALIBRATION)
    assert a == b


def test_default_calibration_matches_no_calibration_momentum():
    df = _momentum_ohlcv()
    a = scan_ticker(df, 1_000_000, PRESETS, ticker="M", current_price=190.0, min_confluence=1)
    b = scan_ticker(df, 1_000_000, PRESETS, ticker="M", current_price=190.0, min_confluence=1,
                    calibration=DEFAULT_CALIBRATION)
    assert a == b
    assert a["stop_source"].endswith("14d")  # default keeps the tight micro stop


# --------------------------------------------------------------------------
# The 3–6mo profile changes parameters as specified
# --------------------------------------------------------------------------
def test_profile_field_values():
    p = POSITION_3TO6MO
    assert p.timeframe == "weekly"
    assert p.ma_anchor == "30-week MA"
    assert p.use_micro_momentum_stop is False           # MOMENTUM override
    assert p.atr_window > DEFAULT_CALIBRATION.atr_window  # longer-horizon vol
    assert p.micro_buffer_atr == 0.5
    assert p.confluence_pct == 0.05
    assert p.stop_buffer_pct_band == (0.03, 0.07)
    assert p.stop_width_pct_band == (0.10, 0.18)


def test_momentum_override_uses_weekly_anchor_not_micro():
    df = _momentum_ohlcv()
    default = scan_ticker(df, 1_000_000, PRESETS, ticker="M", current_price=190.0, min_confluence=1)
    pos36 = scan_ticker(df, 1_000_000, PRESETS, ticker="M", current_price=190.0, min_confluence=1,
                        calibration=POSITION_3TO6MO)
    assert default["stop_source"].endswith("14d")        # tight micro stop
    # 3–6mo: momentum flag falls back to a weekly value anchor (VAL_*/AVWAP), not micro.
    assert not pos36["stop_source"].endswith("14d")
    assert pos36["stop_source"].startswith(("VAL", "AVWAP"))
    # And the weekly-structure stop is wider (further below price) than the micro stop.
    assert pos36["stop"] < default["stop"]


# --------------------------------------------------------------------------
# No time stop — the profile is a lens, not a clock
# --------------------------------------------------------------------------
def test_profile_has_no_time_stop_field():
    names = {f.name for f in fields(CalibrationProfile)}
    assert not any(k in n for n in names for k in ("time_stop", "max_hold", "hold_days", "max_age"))


# --------------------------------------------------------------------------
# Selectable via setting, default is 'default'
# --------------------------------------------------------------------------
def test_calibration_setting_default(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    assert db.get_setting("calibration_profile", "default") == "default"
