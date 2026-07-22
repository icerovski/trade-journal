"""Phase 4 — entry gates G1–G8 unit tests.

Acceptance (docs/ClaudeCode_Implementation_Instructions.md Phase 4):
  * each gate has unit tests for pass/fail;
  * NA when inputs are absent (never blocks);
  * with gates_mode `off`, behaviour is unchanged (default is off — see below and
    the untouched golden master).

The gates are pure, so they are tested directly with no DB or Textual.
"""

import pytest

from core.gates import (
    ProposedTrade,
    evaluate_gates,
    gates_summary,
    g1_stop_width,
    g2_basis_quality,
    g3_fallback_artifact,
    g4_event,
    g5_extension,
    g6_liquidity,
    g7_portfolio_heat,
    g8_currency,
    PASS,
    FAIL,
    NA,
)
import db


# --- G1 stop-width ---------------------------------------------------------
def test_g1_pass_within_bounds():
    # R₁ = 3 on entry 100 -> 3% and (atr 4) 0.75×ATR — inside 8% / 1.5×.
    t = ProposedTrade(entry=100.0, stop=97.0, atr=4.0)
    assert g1_stop_width(t).status == PASS


def test_g1_fail_too_wide_in_atr():
    t = ProposedTrade(entry=100.0, stop=93.0, atr=4.0)  # 1.75×ATR > 1.5×
    r = g1_stop_width(t)
    assert r.status == FAIL and "ATR" in r.reason


def test_g1_fail_too_wide_in_pct():
    t = ProposedTrade(entry=100.0, stop=90.0, atr=20.0)  # 10% > 8% (but only 0.5×ATR)
    assert g1_stop_width(t).status == FAIL


def test_g1_na_without_atr():
    assert g1_stop_width(ProposedTrade(entry=100.0, stop=97.0, atr=0.0)).status == NA


def test_g1_lens_overrides_widen_caps():
    """3–6mo lens (Horizon_Calibration §4): wider weekly-structure stops are
    correct there — the overrides must widen exactly the arm they target."""
    # 15% stop, 1.25×ATR: fails the daily 8% cap, passes the lens 18% cap.
    t = ProposedTrade(entry=100.0, stop=85.0, atr=12.0)
    assert g1_stop_width(t).status == FAIL
    t2 = ProposedTrade(entry=100.0, stop=85.0, atr=12.0, g1_max_stop_pct=0.18)
    assert g1_stop_width(t2).status == PASS
    # The ×ATR arm still binds independently (1.875× > 1.5×)…
    t3 = ProposedTrade(entry=100.0, stop=85.0, atr=8.0, g1_max_stop_pct=0.18)
    assert g1_stop_width(t3).status == FAIL
    # …unless its own override widens it too.
    t4 = ProposedTrade(entry=100.0, stop=85.0, atr=8.0,
                       g1_max_stop_pct=0.18, g1_max_stop_atr=2.0)
    assert g1_stop_width(t4).status == PASS


# --- G2 basis quality ------------------------------------------------------
def test_g2_pass_tight_source_two_levels():
    t = ProposedTrade(stop_source="HVN_14d", confluence_count=2)
    assert g2_basis_quality(t).status == PASS


def test_g2_fail_thin_source():
    t = ProposedTrade(stop_source="ATR(1)", confluence_count=3)
    assert g2_basis_quality(t).status == FAIL


def test_g2_fail_too_few_levels():
    t = ProposedTrade(stop_source="VAL_6mo", confluence_count=1)
    assert g2_basis_quality(t).status == FAIL


def test_g2_na_without_inputs():
    assert g2_basis_quality(ProposedTrade()).status == NA


# --- G3 fallback artifact --------------------------------------------------
def test_g3_fail_unflagged_momo_deep_val():
    t = ProposedTrade(entry=365.0, stop=292.0, regime="MOMENTUM", flagged=False, stop_source="VAL_12mo")
    assert g3_fallback_artifact(t).status == FAIL  # 20% VAL stop, Scenario C


def test_g3_pass_when_flagged():
    t = ProposedTrade(entry=365.0, stop=292.0, regime="MOMENTUM", flagged=True, stop_source="VAL_12mo")
    assert g3_fallback_artifact(t).status == PASS


def test_g3_pass_tight_momo_micro_stop():
    t = ProposedTrade(entry=365.0, stop=356.0, regime="MOMENTUM", flagged=False, stop_source="HVN_14d")
    assert g3_fallback_artifact(t).status == PASS


def test_g3_na_without_flag():
    assert g3_fallback_artifact(ProposedTrade(regime="MOMENTUM")).status == NA


# --- G4 event --------------------------------------------------------------
def test_g4_fail_inside_window():
    assert g4_event(ProposedTrade(days_to_event=3)).status == FAIL


def test_g4_pass_outside_window():
    assert g4_event(ProposedTrade(days_to_event=10)).status == PASS


def test_g4_na_without_date():
    assert g4_event(ProposedTrade()).status == NA


# --- G5 extension ----------------------------------------------------------
def test_g5_fail_too_extended():
    t = ProposedTrade(entry=130.0, trail_anchor=100.0, atr=10.0)  # 3×ATR above anchor
    assert g5_extension(t).status == FAIL


def test_g5_pass_within_reach():
    t = ProposedTrade(entry=115.0, trail_anchor=100.0, atr=10.0)  # 1.5×ATR
    assert g5_extension(t).status == PASS


def test_g5_na_without_anchor():
    assert g5_extension(ProposedTrade(entry=115.0, atr=10.0)).status == NA


# --- G6 liquidity (cut — permanent NA stub) ---------------------------------
def test_g6_is_always_na_and_never_blocks():
    """G6 was cut: no liquidity data source. It must be NA for any trade, so it
    can never block a commit in blocking mode."""
    assert g6_liquidity(ProposedTrade()).status == NA
    assert g6_liquidity(ProposedTrade(qty=2_000_000.0, entry=100.0, stop=90.0)).status == NA


# --- G7 portfolio heat (theme dimension cut) --------------------------------
def test_g7_fail_portfolio_heat_over_cap():
    # cap = 3 × 1.0 = 3.0%. Adding ~1% R on top of 2.5% correlated heat -> > 3%.
    t = ProposedTrade(entry=100.0, stop=90.0, qty=100.0, nav=100000.0, max_r_pct=1.0,
                      portfolio_heat_pct=2.5)
    assert g7_portfolio_heat(t).status == FAIL


def test_g7_pass_within_cap():
    t = ProposedTrade(entry=100.0, stop=99.0, qty=100.0, nav=1_000_000.0, max_r_pct=1.0,
                      portfolio_heat_pct=0.5)
    assert g7_portfolio_heat(t).status == PASS


def test_g7_na_without_context():
    assert g7_portfolio_heat(ProposedTrade(entry=100.0, stop=90.0, nav=100000.0)).status == NA


def test_g7_na_without_nav():
    assert g7_portfolio_heat(ProposedTrade(entry=100.0, stop=90.0, qty=100.0,
                                           portfolio_heat_pct=1.0)).status == NA


# --- G8 currency -----------------------------------------------------------
def test_g8_pass_same_currency():
    assert g8_currency(ProposedTrade(ccy="USD", base_ccy="USD")).status == PASS


def test_g8_pass_foreign_informational():
    assert g8_currency(ProposedTrade(ccy="USD", base_ccy="EUR")).status == PASS


def test_g8_fail_over_fx_cap():
    t = ProposedTrade(ccy="USD", base_ccy="EUR", entry=100.0, qty=1000.0, nav=1_000_000.0,
                      fx_rate=1.0, fx_exposure_cap_pct=5.0)  # 10% exposure > 5% cap
    assert g8_currency(t).status == FAIL


def test_g8_na_without_currencies():
    assert g8_currency(ProposedTrade()).status == NA


# --- Aggregate -------------------------------------------------------------
def test_evaluate_gates_returns_eight_in_order():
    results = evaluate_gates(ProposedTrade())
    assert [r.gate for r in results] == ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]


def test_summary_blocking_only_on_fail():
    # A clean G1 trade with everything else NA -> nothing fails -> not blocking.
    t = ProposedTrade(entry=100.0, stop=98.0, atr=4.0, ccy="USD", base_ccy="USD")
    summary = gates_summary(evaluate_gates(t))
    assert summary["n_fail"] == 0 and summary["blocking"] is False

    # A too-wide stop -> G1 fails -> blocking.
    t2 = ProposedTrade(entry=100.0, stop=80.0, atr=4.0)
    summary2 = gates_summary(evaluate_gates(t2))
    assert summary2["n_fail"] >= 1 and summary2["blocking"] is True


def test_default_gates_mode_is_off(tmp_path, monkeypatch):
    """Default flag reproduces today's behaviour (no gate evaluation on commit)."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    assert db.get_setting("gates_mode", "off") == "off"
