"""Phase 0 safety net — golden-master characterization tests.

These pin the CURRENT behavior of the core decision paths so the Entry/Stop
system work (see docs/ClaudeCode_Implementation_Instructions.md) can proceed
without silently changing what the app does today. Every later phase must leave
this snapshot byte-for-byte identical while the new features sit at their
default-off settings.

The paths captured:
  * the zone scanner            (core.zone_scan.scan_ticker)
  * the stop-source / regime    (scanner regime + classify_regime)
  * dual-constraint sizing       (core.sizing.compute_position_size)
  * the exit ladder / SL / TP    (core.stop_loss.calculate_position_risk,
                                  core.profit_taking.compute_exit_milestones)

Mechanism: each run recomputes `actual` from deterministic synthetic inputs
(no network, no DB writes). The first run bootstraps the golden file; every
later run asserts equality against it. If a change moves a number, this test
fails loudly — that is the intended tripwire ("STOP and flag it").
"""

import json
import numbers
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.zone_scan import scan_ticker
from core.sizing import compute_position_size
from core.profit_taking import classify_regime, compute_exit_milestones
from core import stop_loss
from core.stop_loss import calculate_position_risk
from models import Position, RiskProfile

GOLDEN = Path(__file__).parent / "snapshots" / "phase0_golden.json"

PRESETS = {
    "S": {"label": "Small", "max_r_pct": 0.30, "max_exp_pct": 1.5},
    "B": {"label": "Base", "max_r_pct": 0.60, "max_exp_pct": 3.0},
    "L": {"label": "Large", "max_r_pct": 1.00, "max_exp_pct": 5.0},
}


# --------------------------------------------------------------------------
# Deterministic fixtures (mirror the styles already used in the test suite)
# --------------------------------------------------------------------------
def _sine_ohlcv(n=300, center=100.0, amp=2.0, period=15.0):
    t = np.arange(n)
    close = center + amp * np.sin(t / period)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.full(n, 1000.0),
    })


def _momentum_ohlcv():
    ramp = np.linspace(50.0, 195.0, 270)
    pullback = np.linspace(195.0, 178.0, 30)
    close = np.concatenate([ramp, pullback])
    n = len(close)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.full(n, 1000.0),
    })


def _round(x):
    """Recursively coerce numbers to 6-dp floats for stable JSON comparison."""
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v) for v in x]
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, numbers.Number):
        return round(float(x), 6)
    return x


# --------------------------------------------------------------------------
# Case builders — each returns a JSON-serializable snapshot of current output
# --------------------------------------------------------------------------
def _scanner_cases():
    cases = {}

    # 1. NORMAL regime, flagged ZONE at the level cluster.
    cases["normal_zone"] = scan_ticker(
        _sine_ohlcv(n=300, center=100.0), nav=1_000_000, presets=PRESETS,
        ticker="NORM", current_price=100.0,
    )
    # 2. MOMENTUM regime, ZONE-MOMO micro stop-source.
    cases["momentum_zone"] = scan_ticker(
        _momentum_ohlcv(), nav=1_000_000, presets=PRESETS,
        ticker="MOMO", current_price=190.0, min_confluence=1,
    )
    # 3. No confluence — price far from every level.
    cases["no_confluence"] = scan_ticker(
        _sine_ohlcv(n=300, center=100.0), nav=1_000_000, presets=PRESETS,
        ticker="FAR", current_price=130.0,
    )
    return cases


def _sizing_cases():
    grid = [
        # (nav, entry, stop, mult, max_r_pct, max_exp_pct)
        (1_000_000, 100.0, 90.0, 1.0, 1.0, 5.0),
        (1_000_000, 100.0, 98.0, 1.0, 0.30, 1.5),   # tight stop -> exposure-capped
        (1_000_000, 100.0, 50.0, 1.0, 1.0, 5.0),     # wide stop -> risk-capped
        (500_000, 250.0, 240.0, 1.0, 0.60, 3.0),
        (1_000_000, 100.0, 95.0, 100.0, 1.0, 5.0),   # option-style multiplier
        (1_000_000, 1000.0, 900.0, 0.001, 1.0, 5.0),  # bond-style multiplier
    ]
    return {
        f"n{nav}_e{e}_s{s}_m{m}_r{r}_x{x}": compute_position_size(nav, e, s, m, r, x)
        for (nav, e, s, m, r, x) in grid
    }


def _regime_cases():
    out = {}
    for direction in ("UP", "DOWN"):
        for dma_days in (0, 2, 3, 9, 10, 20, 21, 43):
            for above in (True, False):
                key = f"{direction}_{dma_days}d_above={above}"
                out[key] = classify_regime(direction, dma_days, above)
    return out


def _make_position(**over):
    base = dict(
        name="Test", ticker="TST", conid="111", asset_class="STK", ccy="USD",
        date_entry=pd.Timestamp("2025-01-01"), qty=100.0, entry_price=100.0,
    )
    base.update(over)
    p = Position(**base)
    p.current_price = over.get("current_price", 110.0)
    p.mark_price = over.get("mark_price", 108.0)
    p.max_since_entry = over.get("max_since_entry", 115.0)
    return p


def _exit_ladder_cases(monkeypatch):
    # Never touch the DB from a snapshot test.
    monkeypatch.setattr(stop_loss, "update_high_water_mark", lambda *a, **k: None)

    out = {}
    fields = [
        "sl_price", "tp_price", "m1_price", "m2_price", "exit_stage",
        "rr_ratio", "risk_val", "reward_val", "up_pct", "down_pct",
        "tp_atr_mult", "tp_is_override", "risk_val_live", "sl_pct_base",
    ]

    def snap(p):
        return {f: getattr(p, f) for f in fields}

    # FIXED stop: atr_value stores the absolute stop price (post-redesign).
    fixed_profile = RiskProfile(
        conid="111", ticker="TST", atr_value=90.0, stop_type="FIXED",
        highest_sl=0.0, inception_stop=90.0, inception_atr=10.0,
        max_r_pct=1.0, max_exp_pct=5.0,
    )
    p = _make_position(current_price=110.0)
    calculate_position_risk(p, {"111": fixed_profile})
    out["fixed_stage_M1"] = snap(p)

    # TRAILING stop: atr_value stores the ATR distance.
    trail_profile = RiskProfile(
        conid="111", ticker="TST", atr_value=10.0, stop_type="TRAILING",
        highest_sl=0.0, inception_stop=90.0, inception_atr=10.0,
        max_r_pct=1.0, max_exp_pct=5.0,
    )
    p = _make_position(current_price=110.0, max_since_entry=115.0)
    calculate_position_risk(p, {"111": trail_profile})
    out["trailing_stage_M1"] = snap(p)

    # TP override lifts only the top rung.
    ov_profile = RiskProfile(
        conid="111", ticker="TST", atr_value=90.0, stop_type="FIXED",
        highest_sl=0.0, inception_stop=90.0, inception_atr=10.0,
        max_r_pct=1.0, max_exp_pct=5.0, tp_atr_mult=5.0,
    )
    p = _make_position(current_price=135.0)
    calculate_position_risk(p, {"111": ov_profile})
    out["fixed_tp_override_5R"] = snap(p)

    # Direct milestone ladder across the stages.
    ladder = {}
    for cur in (95.0, 108.0, 118.0, 135.0):
        p = _make_position(current_price=cur)
        p.tp_price = 130.0
        compute_exit_milestones(p, atr_dist=10.0)
        ladder[f"cur_{cur}"] = {
            "m1_price": p.m1_price, "m2_price": p.m2_price, "exit_stage": p.exit_stage,
        }
    out["milestone_stages"] = ladder
    return out


# --------------------------------------------------------------------------
# The single golden-master assertion
# --------------------------------------------------------------------------
def test_phase0_golden_master(monkeypatch):
    actual = _round({
        "scanner": _scanner_cases(),
        "sizing": _sizing_cases(),
        "regime": _regime_cases(),
        "exit_ladder": _exit_ladder_cases(monkeypatch),
    })

    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2, sort_keys=True), encoding="utf-8")

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    # Round-trip `actual` through JSON so int/float typing matches `expected`.
    actual = json.loads(json.dumps(actual, sort_keys=True))
    assert actual == expected, (
        "Phase-0 golden master changed. A core path moved with defaults unchanged — "
        "STOP and flag it before proceeding."
    )
