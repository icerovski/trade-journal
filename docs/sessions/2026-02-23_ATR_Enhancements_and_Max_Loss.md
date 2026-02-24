# 2026-02-23 Session: ATR Enhancements and Portfolio-Weighted Risk

## Objectives
- Redefine ATR Discovery timeframes to align with institutional PE cycles (Daily 14, Monthly 12, Quarterly 8).
- Implement "Max Loss" tracking relative to entry price within the discovery tool.
- Add portfolio-weighted risk assessment (% of NAV) for stop-loss scenarios.
- Streamline the ATR selection workflow to a one-line selection with optional multipliers.

## Technical Changes
- **`core/risk_engine.py`**:
    - Updated `calculate_atr_metrics` to accept `stop_type`, `qty`, `inst_multiplier`, and `total_nav`.
    - Implemented new timeframe intervals: Daily (14d), Monthly (12m), and Quarterly (8q).
    - Added "P/L at Stop" calculation relative to Entry Price.
    - Added "% of NAV" calculation based on current portfolio equity.
    - Refactored the discovery table to show a focused view based on the chosen stop type (Fixed vs Trailing).
- **`main.py`**:
    - Refined `handle_atr_calculator` to prompt for Stop Type at the start of each ticker's iteration.
    - Integrated one-line selection format: `[option] [multiplier]` (e.g., `3 1.5` to apply 1.5x multiplier to the 12m SMA ATR).
    - Removed redundant confirmations to speed up the batch risk assignment process.
    - Automatically fetches latest NAV from IBKR snapshots for real-time risk weighting.
- **`services/price_service.py`**:
    - Expanded historical lookback to 10 years (`days_back=3650`) to support Quarterly (8q) and Monthly (12m) calculations.
    - Enhanced `fetch_and_store` to handle both forward updates and historical gaps.
- **`tests/test_integration.py`**:
    - Fixed modularization-related import errors and outdated patch targets.
    - Enhanced test isolation by explicitly patching `BASE_DATA_DIR` and `LBD_DIR`.
    - Mocked `yf.download` to prevent tests from pulling live market data.

## Logic & Decisions
- **Reference Point Integrity**: Max Loss is now calculated strictly relative to the **Entry Price**. This ensures that even for trailing stops, the user sees the final trade outcome (Total P/L) if the stop is triggered, maintaining the "CEO Approach" to capital preservation.
- **Dynamic Risk Weighting**: By including % of NAV in the discovery phase, the system provides an immediate sanity check on position sizing before a risk strategy is even assigned.
- **Interactive Efficiency**: The move to one-line command selection (`3 1.5`) mirrors professional terminal workflows, reducing the number of keystrokes needed to manage a large portfolio.

## Next Steps
- **Verification**: Monitor Quarterly SMA ATR values over the next week to ensure resampling stability in the local DB.
- **Feature Expansion**: Consider adding "RR Ratio at Stop" to the discovery table to show potential reward relative to the calculated loss.
