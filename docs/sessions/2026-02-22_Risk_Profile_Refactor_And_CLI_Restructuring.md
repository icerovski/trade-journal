# 2026-02-22 Session: Risk Profile Refactor, Real-Time Merge, and ATR Optimization

## Objectives
- Evolve position risk management into a historical "Risk Profile" system.
- Implement a "Real-Time Merge" workflow using IBKR Trade Confirmations.
- Restructure the main CLI menu into a "Minimalist (Action-First)" model.
- Resolve ATR underestimation by aligning timeframes with institutional charts (Weekly 12, Monthly 24).

## Technical Changes
- **`db.py`**:
    - Replaced `position_risk` table with `risk_profiles` (Session-based tracking).
    - Implemented `delete_manual_duplicates` for "Fingerprint" de-duplication (Ticker, Date, Qty).
    - Added `wipe_trades_only()` for surgical ledger resets.
- **`services/ibkr.py` & `services/ibkr_parser.py`**:
    - Added support for **Trade Confirmations** Flex Query.
    - Implemented real-time execution parsing with automated manual trade reconciliation.
- **`core/risk_engine.py`**:
    - Refactored ATR windows: **Weekly (12)** and **Monthly (24)** to match long-term PE strategy.
    - Added clear labeling for **SMA** vs. **Wilder's** smoothing methods.
- **`main.py`**:
    - Restructured CLI into workflow groups: SYNC ALL, MANUAL ENTRIES, VIEW DASHBOARD, MAINTENANCE.
    - Implemented "Fast Path" Dashboard (Enter for Defaults).
    - Integrated on-demand Refresh prompt for Snapshots + Intraday trades.
- **`config.py`**:
    - Formalized paths for snapshots and intraday confirmations.

## Logic & Decisions
- **Fingerprint Reconciliation**: To handle rounded manual prices, the system matches on Ticker/Date/Qty. When a broker execution arrives, the manual "estimate" is surgically replaced by the "official truth."
- **Timeframe Alignment**: ATR underestimation was identified as a timeframe mismatch (Daily vs. Monthly). Shifting to Monthly(24) SMA aligns the system with TradingView/StockCharts institutional views.
- **On-Demand Snapshots**: Moved slow IBKR snapshot fetching from the main sync to the dashboard, triggered only when needed, keeping the daily ledger refresh fast.

## Next Steps
- **Verification**: User to verify GOOGL ATR values (~29.14) against TradingView (~29.21).
- **Flex Query**: User needs to ensure `IBKR_QUERY_ID_CONFIRMATIONS` is active in IBKR and `.env`.
