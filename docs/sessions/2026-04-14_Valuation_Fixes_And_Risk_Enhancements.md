# Session Log: 2026-04-14 - Valuation Fixes & Risk Workspace Enhancement

## Objectives
1.  Resolve "Zero Market Value" bug on Dashboard (Option 3).
2.  Fix excessive share recommendations and incorrect average costs in Risk Workspace (Option 2).
3.  Add "AVG COST" column and "Cost Value" metrics to the Risk Workspace for improved auditability.
4.  Align "Remaining Cap" calculation with the HCM (Higher of Cost or Market) capital discipline mandate.

## Technical Changes

### Core Logic & Data Pipeline
- **`models.py`**: 
    - Updated `calculate_financial_metrics` to use `mark_price` as an institutional fallback when live `current_price` (Yahoo Finance) is unavailable or zero. This ensures P/L and Market Value stay mathematically sound.
    - Added `fx_rate` field to the `Position` model to support cross-currency normalization.
- **`data_loader.py`**:
    - Fixed a critical typo in broker snapshot parsing: replaced incorrect `'FX Rate To EUR'` with the actual CSV header `'FXRateToBase'`.
    - Enriched the snapshot dictionary with `FXRateToEUR` to allow the Risk Engine to normalize exposure against the portfolio base currency.
- **`core/portfolio_manager.py`**:
    - Updated NAV exposure and Risk-at-Stop calculations to be `fx_rate` aware, ensuring correct % NAV metrics for non-EUR denominated positions.
- **`core/risk_engine.py`**:
    - Refactored `audit_position_risk` and `calculate_pilot_entry` to accept and utilize `fx_rate` for all budget and share-adjustment calculations.

### Risk Workspace UI (`risk_workspace.py`)
- **New Column:** Added "AVG COST" next to "CUR P" in the main Portfolio Risk Status table.
- **Dynamic Updates:** The "AVG COST" column now updates in real-time when modeling hypothetical entry prices in the Strategy Lab.
- **Audit Metrics:** 
    - Added "Cost Value" (Qty * Avg Cost) to the Asset Context & Risk Audit side panel.
    - Updated "Remaining Cap" formula to: `max(0, Target Outlay - max(Cost Value, Market Value))`, strictly adhering to the HCM mandate.
- **Bug Fix:** Updated prospect row insertion to accommodate the new column count, preventing UI misalignment.

## Logic & Decisions
- **HCM Capital Discipline:** We chose to anchor the "Remaining Cap" to the *higher* of cost or market value. This prevents "averaging down" traps for losers while respecting the real-time exposure growth of winners.
- **Institutional Fallback:** By moving the `mark_price` fallback into the `Position` model's core metric calculation, we ensure that the entire app (Dashboard, Risk Workspace, and Reports) remains visually and mathematically consistent even during data outages.

## Verification
- **Data Integrity:** Verified that `open_positions_lbd.csv` now loads correctly. BXMT and TLT positions are now fully recognized (6,269 and 505 shares respectively) instead of being limited to recent trades.
- **Mathematical Accuracy:** 
    - TLT Average Cost correctly healed to **88.92**.
    - BXMT Average Cost healed to **18.25**.
    - Total Portfolio NAV correctly aggregated at **~2.34M EUR**.
- **UI Consistency:** Verified that modeling a new ticker (e.g., AAPL) updates all 11 columns correctly without shifting data.

## Next Steps
- Investigate the 0.50 discrepancy in BXMT average cost (User reality 18.75 vs Ledger 18.25) to identify if historical trades from early 2024 are missing.
- Review corporate action history for any missed stock splits that might affect cost basis healing.
