# GEMINI.md: Project Context for Trade Journal & Risk Management

This document provides a comprehensive technical and strategic overview of the Trade Journal project.

## 1. Project Identity & Strategic Vision
**Project Name:** Trade Journal & Risk Management System
**Core Philosophy:**
*   **"CEO Approach":** Designed for scalability, auditability, and maintaining a "Single Source of Truth."
*   **Ledger-Based Accounting:** Holdings are computed on-the-fly by replaying transaction history (Buy/Sell/Transfer/Split).
*   **Institutional Consolidation:** Positions are consolidated across all accounts by default to provide a unified portfolio view.
*   **Cost Basis Healing:** Recovers historical entry prices from the global ledger when broker snapshots are incomplete or accounts differ.
*   **Reset-on-Zero:** When a position's quantity hits zero, its cost basis is wiped, allowing for a clean re-entry tracking.
*   **Docs-as-Code:** Risk procedures and session logs are integrated as metadata-rich documentation.
*   **Learning-as-Systems:** Contains a built-in "Advanced Python Systems" course using the project as source material.

## 2. Technical Architecture

### Core Stack
*   **Language:** Python 3 (managed via uv)
*   **Databases:**
    *   trade_journal.db: Primary ledger, historical **Risk Profiles**, and the **Asset Master (ticker_info)**. Derived exclusively from broker data (Single Source of Truth).
    *   prices.db: Persistent historical price/volume cache (OneDrive).
*   **Data Processing:** pandas and numpy
*   **Market Data:** yfinance with local caching.
*   **UI/CLI:** Textual for the non-blocking Trading Cockpit and the interactive **Risk Workspace**.

### Module Structure
#### Orchestration
*   **main.py**: The Entry Point. Implements a Minimalist CLI (Sync All, Risk Workspace, View Dashboard, Kids Fund, Maintenance, Watch List). Includes real-time **Watch List Counter** for instant prospect awareness.
*   **watch_list_workspace.py**: The Technical Audit Desk.
    * **Institutional Timing Dashboard**: Enhanced prospects table showing real-time **Price**, **Buffer to Stop (%)**, and **Risk-at-Stop (% NAV)** for all monitored ideas.
    * **Comprehensive Confluence Audit**: Evaluates distances between Price/Stops and 8 indicators (EMA/DMA 200, 100, 50, 10).
    * **Volatility-Adjusted Proximity**: Measures confluence zones in Daily ATR units (< 0.25R) to ensure cross-asset mathematical consistency.
    * **Undisturbed Trend Engine**: Tracks 200-DMA direction changes with a 21-day "Confirmed Trend" trigger (🟢 BUY / 🔴 SELL).
*   **core/portfolio_manager.py**: The Portfolio Hub. Handles multi-account consolidation and institutional enrichment.
* **risk_workspace.py**: The Audit Terminal.
    * **Unified Execution Desk**: Merges Risk Audit and Roadmap planning into a single "Institutional Execution Desk." Forced mathematical alignment between compliance checks and stage-based milestones.
    * **Asymmetric Action Indicators**: Implements a conviction-based **ACTION** column that suggests adds (10% threshold) or trims (5% threshold) while filtering out transaction noise.
    * **Synchronized Price Anchoring**: Both compliance and planning use the **Current Market Price** as the primary anchor for "Shares to Add" calculations, bypassing legacy inception price confusion.
    * **Institutional Strategy Lab**: Supports the **`S0`** flag to explicitly disable Scale-In steps and revert to a Standard entry type with a single target.
    * **Optimized Layout Split**: Implements a **55/45** horizontal and vertical distribution to maximize information density on professional-grade monitors.
    * **Institutional Sizing Discovery**: Added a **QTY** column to ATR Discovery tables, showing required shares for each volatility timeframe based on NAV limits.
    * **Auditability Enhancements**: Added **AVG COST** column to the main grid and **Cost Value** (Inception Valuation) to the execution desk for direct performance audit.
    * **Persistent NAV Summary**: Displays total Portfolio NAV at the top of the screen for real-time risk sanity checks.
    * **Dual-Constraint Auditing**: Evaluates both Risk-at-Stop and Capital Exposure limits.
*   **dashboard.py**: The Trading Cockpit. Implements a 60s background refresh and high-visibility breach indicators (Price cell highlighting) to match the Audit Terminal's rigor.

#### Learning & Development
* **course/**: A standalone curriculum for rebuilding the system from scratch to teach advanced Python and Algorithm concepts.
    * **Module 1: Foundation**: Data modeling, immutability, and database persistence.

#### Core Logic (core/)
*   **ledger_engine.py**: The Accounting Engine. Implements "Reset-on-Zero" ledger replay and dynamic `SPLIT` proportionality to maintain correct inception prices. Handles both forward splits (positive qty) and reverse splits (negative qty) using signed quantity from the Trade object.
*   **reconciliation_service.py**: The Healer. Reconciles broker snapshots with manual trades using a dual-pass "Global Ledger" to wash out internal account transfers, recovering the true, original cost basis.
*   **risk_engine.py**: The Risk Engine. Calculates Stop Losses and Take Profits based on **ACTIVE Risk Profiles**. Supports structured ATR analysis and Dual-Constraint Auditing. `get_atr_discovery_data()` is decomposed into `_fetch_price_data()` (I/O) and `_compute_atr_rows()` (computation); accepts a `mapper=` parameter to avoid redundant service instantiation when called from a workspace that already holds a `PortfolioManager`.
*   **asset_registry.py**: The Rule Registry. Centralizes asset-specific heuristics (e.g., 10.0 multiplier for Bonds).
*   **kids_fund_engine.py**: The Trustee. Calculates individual ownership units and Glide Path compliance. Implements **Parity-Based Distribution** to ensure equal purchasing power at age 18 (adjusted for 3.5% inflation).

#### External Services (services/)
*   **market_data_service.py**: The Data Pipeline. Performs optimized batch fetching from Yahoo Finance.
*   **price_service.py**: The Price Hub. Manages local OHLCV caching and technical indicator calculation (DMA/EMA).
*   **ticker_mapper.py**: The Symbol Resolver. Maps symbols to Yahoo tickers using the DB-based **Asset Master**.
*   **ibkr_parser.py**: The Translator. Interprets IBKR Flex CSVs (NAV, Trades, Transfers, Corp Actions) and ingests them into the ledger.
    * **Fingerprint De-duplication**: Uses multi-factor external IDs (TransactionID-AccountID-Side) to prevent collisions.
    * **Bond Point Correction**: Automatically scales transfer-derived prices by 100x to maintain standard "Percentage of Par" pricing.

## 3. Data Management
*   **Price Persistence**: OHLCV data is indexed by (Conid, Date) in the persistent prices.db.
* **Risk Metrics**:
    *   **ATR Standards**: Uses institutional timeframes: Daily (14), Weekly (12), Monthly (12), Quarterly (8). Standardized on Wilder ATR with SMA for audit.
    *   **Volatility Buffer**: Implements a "Fixed Dollar" stop loss strategy. Percentages entered are converted to a fixed dollar amount (`atr_value`) to maintain consistent risk units throughout a trend, effectively tightening the percentage stop as prices rise.
    *   **HCM Exposure (Conservative)**: Anchors capital exposure to the **Higher of Cost or Market** value. Prevents "averaging down" traps for underwater positions while maintaining mark-to-market discipline for winners.
    * **R (% NAV)**: Institutional Risk-at-Stop. Calculated as (Entry Price - Stop Price) * Qty / NAV. Implements **Quantity-First Auditing** where capital requirements are secondary to risk-unit limits. Metrics are automatically **normalized to the NAV currency** using live FX rates from the broker snapshot.
    * **RR Efficiency**: Reward-to-Risk ratio. Calculated as (TP - Price) / (Price - Stop). Signal: < 1.0 (Exit). Color-coded thresholds: 🟢 > 1.0%, 🟡 > 0.5%.
    * **Drafting Workflow**: Supports in-memory draft state for bulk risk strategy updates.
*   **Database Schema (trade_journal.db)**:
    * `trades`: Activity ledger. Includes `multiplier` for accurate valuation of options and bonds.
    * `ticker_info`: Asset Master. Single Source of Truth for metadata (ISIN, multiplier, exchange).
    * `risk_profiles`: Historical and active risk strategies. Includes `inception_stop` and `inception_atr` as permanent risk anchors for auditing.
    * `kids_config`: Parity-adjusted unit baselines and birthdates.

## 4. Operational Protocols
*   **Startup:** smart_sync() ensures local config is up to date with OneDrive.
*   **Exit:** backup mirrors logs and config to OneDrive automatically.
*   **Risk Workspace:** Asynchronous background data fetching with instant multiplier (1.5) and percentage (10%) input parsing. Focus-optimized TAB navigation. Implements **High-Conviction Scaling** (10% threshold for both Adds and Trims) to prioritize meaningful rebalancing over transaction noise.
*   **Dynamic Cockpit:** Supports in-memory **Sorting** (Keys 1-4) and **Mnemonic Filtering** (Keys: a, s, o, b, t). Uses high-contrast price highlighting (Bold Red/Green) to signal breaches or target achievements.
