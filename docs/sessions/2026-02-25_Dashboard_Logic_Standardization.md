# Session Log: 2026-02-25 - Dashboard Logic Standardization

## Objectives
- Standardize the system on the "Hybrid" calculation method (Snapshot + Deltas) for maximum accuracy and speed.
- Hardcode the background refresh interval to 60 seconds.
- Simplify the user interface by removing redundant logic-switching prompts.

## Technical Changes
- **`main.py`**:
    - Refactored `handle_view_dashboard` to remove prompts for data method (Hybrid vs Ledger) and view mode (Live vs Static).
    - The dashboard now launches directly into the live view.
- **`dashboard.py`**:
    - Removed `use_ledger` and `refresh_interval` parameters from the `TradingCockpit` class and `run_live_dashboard` entry point.
    - Hardcoded the background refresh heartbeat to 60 seconds.
    - Updated status bar to reflect the simplified, standardized view.
- **`core/portfolio_manager.py`**:
    - Simplified `get_dashboard_df` by removing the `use_ledger` parameter and always defaulting to `get_open_positions_hybrid`.
- **`tests/test_integration.py`**:
    - Updated integration tests to align with the simplified method signatures.

## Logic & Decisions
- **Standardizing on Hybrid**: Hybrid mode is the superior method for a trading desk as it leverages the broker's official "Single Source of Truth" (the snapshot) while incorporating intraday manual trades. Maintaining the "Ledger-only" view as an alternative in the UI added unnecessary complexity.
- **Fixed Heartbeat**: A 60-second refresh provides high-signal monitoring without overwhelming the Yahoo Finance API or local CPU.

## Verification
- Verified that choosing Option [3] in the main menu now launches the dashboard instantly.
- Confirmed the dashboard correctly identifies and filters the entire portfolio using the Hybrid source.
- Verified that background refreshes continue to function on the fixed 60s timer.

## Next Steps
- Implement volume analysis for bear/bull market confirmation.
- Enhance the risk engine with Confluence Zone detection (ATR + EMA/Bollinger).
