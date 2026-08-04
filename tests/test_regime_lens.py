"""Horizon-aware regime lens (default-off, `regime_lens` setting).

Covers the two pure functions: select_regime_lens (stop-horizon → DMA window +
confirmation thresholds) and the parameterized classify_regime. The default call
signatures must reproduce today's 200-DMA behaviour exactly — that contract is
what keeps the characterization snapshot byte-identical.
"""

from core.profit_taking import classify_regime, select_regime_lens
from constants import REGIME_TREND_MIN_DAYS, REGIME_NORMAL_MIN_DAYS


STRUCTURAL = (200, REGIME_TREND_MIN_DAYS, REGIME_NORMAL_MIN_DAYS)


class TestSelectRegimeLens:
    def test_daily_atr_stop_gets_tactical_lens(self):
        # SOXL-style trade: risk unit ≈ 1 daily ATR → 50-DMA, 10d/5d.
        assert select_regime_lens(10.0, 10.0) == (50, 10, 5)

    def test_weekly_atr_stop_gets_swing_lens(self):
        # ratio ≈ √5 ≈ 2.2 — a stop snapped to the weekly ATR.
        assert select_regime_lens(22.0, 10.0) == (100, 15, 7)

    def test_monthly_atr_stop_keeps_structural_lens(self):
        # ratio ≈ √21 ≈ 4.6 — DXJF-style wide conviction stop → today's 200-DMA.
        assert select_regime_lens(46.0, 10.0) == STRUCTURAL

    def test_band_edges(self):
        assert select_regime_lens(1.6, 1.0) == (50, 10, 5)     # inclusive upper edge
        assert select_regime_lens(1.61, 1.0) == (100, 15, 7)
        assert select_regime_lens(3.4, 1.0) == (100, 15, 7)
        assert select_regime_lens(3.41, 1.0) == STRUCTURAL

    def test_missing_data_falls_back_to_structural(self):
        # No risk unit, no daily ATR, or nonsense → today's behaviour, never a crash.
        assert select_regime_lens(0.0, 10.0) == STRUCTURAL
        assert select_regime_lens(10.0, 0.0) == STRUCTURAL
        assert select_regime_lens(None, None) == STRUCTURAL
        assert select_regime_lens(-5.0, 10.0) == STRUCTURAL


class TestClassifyRegimeDefaults:
    """Default-argument calls must match today's 200-DMA classification exactly."""

    def test_trend_needs_21_days_and_price_above(self):
        assert classify_regime('UP', 21, True) == "TREND"
        assert classify_regime('UP', 21, False) == "NORMAL"   # pullback below DMA
        assert classify_regime('UP', 20, True) == "NORMAL"

    def test_normal_floor_and_ranging(self):
        assert classify_regime('UP', 10, True) == "NORMAL"
        assert classify_regime('UP', 9, True) == "RANGING"

    def test_reversal_hysteresis(self):
        assert classify_regime('DOWN', 2, True) == "NORMAL"    # unconfirmed reversal
        assert classify_regime('DOWN', 3, True) == "RANGING"   # confirmed decline


class TestClassifyRegimeScaledThresholds:
    """The horizon lens passes shorter confirmation windows for faster DMAs."""

    def test_tactical_lens_confirms_trend_at_10_days(self):
        assert classify_regime('UP', 10, True, trend_min_days=10, normal_min_days=5) == "TREND"
        # Same inputs on the structural thresholds would only be NORMAL.
        assert classify_regime('UP', 10, True) == "NORMAL"

    def test_tactical_lens_normal_floor_at_5_days(self):
        assert classify_regime('UP', 5, True, trend_min_days=10, normal_min_days=5) == "NORMAL"
        assert classify_regime('UP', 4, True, trend_min_days=10, normal_min_days=5) == "RANGING"

    def test_price_below_lens_dma_still_gates_trend(self):
        assert classify_regime('UP', 15, False, trend_min_days=10, normal_min_days=5) == "NORMAL"

    def test_hysteresis_unchanged_by_lens(self):
        assert classify_regime('DOWN', 2, True, trend_min_days=10, normal_min_days=5) == "NORMAL"
        assert classify_regime('DOWN', 3, True, trend_min_days=10, normal_min_days=5) == "RANGING"
