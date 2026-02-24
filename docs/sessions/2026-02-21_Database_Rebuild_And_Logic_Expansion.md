# Session Log: Feb 21, 2026 - Database Rebuild & Ledger Expansion

## Objectives
- Align the data structure with the bifurcated folder system (`data_base` and `last_business_day`).
- Expand the ledger engine to support Transfers and Corporate Actions (Splits).
- Ensure "Reset-on-Zero" logic maintains mathematical integrity during non-trade movements.

## Technical Changes
- **`config.py`**: Updated `BASE_DATA_DIR` and `LBD_DIR` paths to match the user's manual folder organization in OneDrive.
- **`ibkr_parser.py`**: 
    - Implemented `parse_transfers_csv()` with cost basis calculation from `PositionAmount`.
    - Implemented `parse_corporate_actions_csv()` to identify and process stock splits.
- **`ibkr.py`**: Refactored `process_local_csvs()` to iterate across all historical file patterns (`trades_*.csv`, `transfers_*.csv`, `corp_actions_*.csv`).
- **`data_loader.py`**: Updated `clean_trade_data()` to allow new transaction sides (`TRANSFER_IN`, `TRANSFER_OUT`, `SPLIT`).
- **`portfolio_manager.py`**: Updated `calculate_positions()` to correctly adjust quantities for Transfers and Splits while maintaining cost basis.
- **`main.py`**:
    - Consolidated IBKR data fetching into "Fetch Recent Data".
    - Added "Rebuild Database" and "Update Database (YTD)" management options.
    - Integrated `sync_config.smart_sync()` on startup to ensure OneDrive configurations (like `.env`) are always current.

## Logic & Decisions
- **Transfer Pricing:** When `Price` is zero in a transfer CSV, the engine now derives the price via `PositionAmount / Quantity`. This ensures the cost basis remains accurate across account movements.
- **Split Handling:** Splits are treated as quantity adjustments (`side='SPLIT'`) with a price of `0.0`. This updates the share count in the ledger without introducing artificial profit or loss.
- **Smart Sync:** The application now compares local and OneDrive modification times. This prevents configuration drift when switching between different machines.

## Verification
- **Full Database Rebuild:** Successfully wiped the old database and re-imported the complete history from 10+ CSV files.
- **Final Ledger Summary:**
    - BUY: 1,136 records
    - SELL: 588 records
    - TRANSFER_IN: 29 records
    - SPLIT: 4 records
- **System Stability:** Verified `uv run python main.py` loads the hybrid portfolio correctly and reconciles with IBKR Verified Snapshots.

## Next Steps
- User to test the "Fetch Recent Data" and "Dashboard" flows.
- Review ATR and Risk formulas in light of the expanded ledger data.
