# Technical Documentation: Trade Journal & Risk Management

This document serves as the "Single Source of Truth" for the technical implementations and operational workflows of the system.

---

## 1. Institutional Prospect Simulator & Watch List

The Prospect Simulator allows for the analysis and simulation of potential stock purchases using existing institutional risk frameworks before capital is committed.

### Operational Workflow
1.  **Ticker Discovery**: Within the **Risk Workspace** (Option 2 -> 1 from main menu), use the **"Discover Ticker"** input field.
2.  **Instant Simulation**: Entering a ticker (e.g., `NVDA`, `TSLA`) triggers an automated background process:
    *   **Price Fetching**: Real-time pricing and historical OHLCV data are retrieved via `yfinance`.
    *   **Volatility Analysis**: ATR horizons are calculated across multiple timeframes: 14d (Daily), 12w (Weekly), 12m (Monthly), and 12q (Macro).
    *   **Prospect Anchoring**: For unowned assets (entry price = 0.0), the system automatically assumes a purchase at the **current market price**.
    *   **Standard Unit Sizing**: Metrics like "P/L at Stop" and "Risk (R)" are calculated based on a **Standard Unit** (the maximum shares allowed by the 1% Risk and 5% Exposure limits).
    *   **Strategy Modeling**: Users can model "What-If" scenarios in the **Strategy Lab** to see hypothetical stops and targets.
3.  **Institutional Sizing**: The system performs a **Dual-Constraint Audit** against live total NAV:
    *   **Risk Limit**: Ensures potential loss at stop does not exceed 1.0% of NAV.
    *   **Exposure Limit**: Ensures total market value does not exceed 5.0% of NAV.
    *   The most restrictive constraint automatically dictates the recommended share count.
4.  **Watch List Persistence**: Pressing `CTRL+ENTER` saves the simulation as a **"Watch List"** profile in the database.
5.  **The "Healing" Bridge**:
    *   Prospects are tracked using a `PROSPECT:TICKER` virtual ID.
    *   Upon purchasing the asset, the next broker sync will discover a real IBKR `conid`.
    *   The system automatically "promotes" the Watch List settings to the live `ACTIVE` position, preserving all original analysis and ATR settings.

### Technical Implementation Details
*   **Data Persistence**: Watch list items are stored in the `risk_profiles` table with a status of `WATCH`.
*   **Database Integrity**: A unique index (`idx_watch_conid`) prevents duplicate prospect entries.
*   **Seamless Integration**: Watch List items are injected into the consolidated dashboard view (flagged as `WATCHLIST`), allowing for performance monitoring against targets before execution.
*   **Account Agnostic**: Cost-basis healing and promotion logic operate at the asset level to handle multi-account environments.

---

## 2. Multi-Account Consolidation & Cost Basis Healing

Institutional-grade accounting logic that ensures a unified portfolio view and accurate cost-basis recovery across multiple entities and account types.

### Operational Workflow
1.  **Unified Portfolio View**: The Dashboard and Risk Workspace automatically consolidate positions with the same `conid` across all accounts into a single row by default.
2.  **Automated Healing**: If a broker snapshot reports a zero cost basis (typical for asset transfers), the system automatically performs a recursive scan of the global trade ledger.
3.  **Manual Ledger Enrichment**: Users can "force heal" a position by entering a manual `TRANSFER_IN` or `BUY` record with correct historical data via Option 2 -> 2. The system will link this history during the next calculation.

### Technical Implementation Details
*   **Weighted Average Cost (WAC)**: Merged positions calculate entry price using the formula: `((Qty1 * Price1 * Mult1) + (Qty2 * Price2 * Mult2)) / (TotalQty * ConsolidtedMult)`.
*   **Inception Anchoring**: Trailing stops and roadmap milestones are anchored to the earliest `date_entry` and original `inception_price` found across all accounts for that asset.
*   **Account-Agnostic Reconciliation**: The `ReconciliationService` implements a multi-stage lookup: it first attempts an exact `(Account:Conid)` match for cost basis, then falls back to a global `Conid` match if entry price remains unknown.
*   **Stability**: Consolidating by `conid` prevents `DuplicateKey` UI crashes in environments where the same asset is held in multiple accounts.

---
