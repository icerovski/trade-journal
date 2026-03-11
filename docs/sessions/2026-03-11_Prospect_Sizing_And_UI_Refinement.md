# Session Log: Prospect Sizing Discovery and UI Refinement

**Date:** 2026-03-11
**Title:** Prospect Sizing Discovery and UI Refinement

## Objectives
- Integrate institutional sizing (quantity calculation) into the prospect discovery workflow.
- Ensure market-anchored pricing for strategy discovery during pre-market/trading hours.
- Decommission the manual trade entry feature to maintain a single source of truth from broker data.
- Optimize the Risk Workspace layout for smaller laptop displays.

## Technical Changes

### 1. Institutional Sizing & Risk Discovery
- **models.py**: Added `qty` field to `ATRDiscoveryRow` to pass sizing data back to the UI.
- **core/risk_engine.py**: 
    - Updated `get_atr_discovery_data` to calculate the required quantity for each ATR timeframe based on dual-constraints (Risk and Exposure).
    - Implemented **Adaptive ATR Windowing**: The engine now automatically reduces the calculation window if historical data is limited (e.g., for newer stocks or Quarterly ATR), preventing data loss in the UI.
    - Fixed a bug where a zero distance to stop (ATR=0) would crash the sizing calculation; it now defaults to the Exposure limit.
- **risk_workspace.py**: 
    - Added a **QTY** column to both Fixed and Trailing discovery tables.
    - Implemented a prominent `PROPOSED BUY` line in the sidebar that instantly updates as strategy parameters (ATR, R%, E%) are typed in the Lab.

### 2. UI Layout Optimization
- **risk_workspace.py**: 
    - Migrated the Asset Context sidebar to a `ScrollableContainer` with a fixed height (16 lines). This ensures that large roadmaps (e.g., 3-stage Scale-Ins) don't push the Discovery tables off-screen on laptop displays.
    - Added a `MODELING STRATEGY` header to the sidebar to clearly distinguish hypothetical sandbox calculations from current portfolio data.

### 3. Feature Decommissioning
- **main.py**: Removed the "Manual Entries" submenu. Promoted the **Risk Workspace** to option `[2]` for faster access.
- **db.py**: Removed `get_manual_trades`, `delete_trade`, and `delete_manual_duplicates`. Added an automatic cleanup in `init_db` that wipes legacy `MANUAL` source trades.
- **services/ibkr_parser.py**: Removed redundant logic that checked for manual duplicates during broker ingestion.
- **core/reconciliation_service.py**: Removed 'MANUAL' from the delta reconciliation loop, focusing purely on broker snapshots and execution confirmations.

## Logic & Decisions
- **Market-Anchored Discovery**: For prospects, the system assumes the current market price as the "Effective Entry." This allows for accurate volatility buffers and sizing relative to the current market floor, even if tested pre-market.
- **Exposure-First Sizing**: When an ATR is not yet specified in the Lab, the system now defaults to showing the maximum quantity allowed by the **Exposure Limit** (e.g., 5% of NAV), providing immediate feedback to the trader.

## Verification
- Verified that discovery tables (14d, 12w, 12m, 12q) correctly display the required share count.
- Confirmed that the sidebar is scrollable and discovery tables remain visible on smaller screen resolutions.
- Rebuild of `trade_journal.db` confirmed that legacy manual trades are purged and the ledger remains broker-verified.

## Next Steps
- Implement "Scale-In Audit" to check if current positions should be added to based on ATR milestones.
- Enhance the Kids Fund glide path logic to handle individual asset volatility.
