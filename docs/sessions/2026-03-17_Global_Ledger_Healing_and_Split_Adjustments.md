# Session Log: Global Ledger Healing & Split Adjustments
**Date:** 2026-03-17

## Objectives
- Filter the Risk Workspace to exclusively show Stock (`STK`) positions, ignoring Bonds and Options.
- Fix inflated P/L at Stop metrics for positions that underwent a stock split (e.g., `XLB`).
- Fix artificially inflated cost basis for positions transferred internally between accounts (e.g., `BXMT`).

## Technical Changes
- **`risk_workspace.py`**: Added `asset_class_filter=['STK']` to `get_dashboard_df` to ensure the Risk Audit terminal focuses exclusively on equities.
- **`core/ledger_engine.py`**: Updated the `SPLIT` processing logic. When a split occurs, the system now scales the `inception_price` proportionally (`qty / (qty + split_qty)`) to ensure trailing stop high-water marks remain anchored correctly.
- **`core/reconciliation_service.py`**: Implemented a "Global Ledger" pass. The healer now generates a truly account-agnostic ledger by forcing all trades to a `CONSOLIDATED` account, stripping away the artificial step-ups in price caused by internal inter-account transfers.
- **Database Intervention (`trade_journal.db`)**: Executed a direct database patch via Python to halve the `atr_value` and `highest_sl` for `XLB`, perfectly aligning its historical risk profile with the 2-for-1 split.

## Logic & Decisions
- **True Inception Healing**: The reconciliation engine now performs a dual-pass ledger generation. By completely ignoring `account_id` during the global pass, internal `TRANSFER_OUT` and `TRANSFER_IN` events wash each other out, revealing the pure, original cash outlay. This prevents the broker's "mark-to-market" transfer logic from artificially inflating the cost basis.
- **Split Proportionality**: Stock splits maintain total dollar cost but increase quantity. Previously, the engine wasn't dividing the `inception_price` (the anchor for trailing stops). By scaling the inception price inversely to the quantity jump, the system maintains accurate risk distance.

## Verification
- Validated `XLB`: The max since entry properly recovered, and the P/L at stop flipped from significantly negative (-42k) to structurally accurate (+7k).
- Validated `BXMT`: The cost basis was successfully healed from the post-transfer $120,066 down to the accurate pre-transfer ~$114,469.

## Next Steps
- Implement automated detection and adjustment of stored `risk_profiles` when new `SPLIT` actions are ingested from the broker CSV.
