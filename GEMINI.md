# GEMINI.md: Project Context for Trade Journal & Risk Management

This document provides a comprehensive technical and strategic overview of the Trade Journal project for the Gemini CLI.

## 1. Project Identity & Strategic Vision
**Project Name:** Trade Journal & Risk Management System
**Owner Persona:** MD of a Private Equity fund; former CEO of a Development Bank.
**Core Philosophy:**
*   **"CEO Approach":** Designed for scalability, auditability, and maintaining a "Single Source of Truth."
*   **Ledger-Based Accounting:** Holdings are not stored as static states; instead, they are computed on-the-fly by replaying transaction history (Buy/Sell). This ensures mathematical integrity and eliminates double-entry errors.
*   **Reset-on-Zero:** When a position's quantity hits zero, its cost basis is wiped, allowing for a clean re-entry tracking.
*   **Docs-as-Code:** Risk procedures and trading rules are integrated as metadata-rich documentation intended for both human readability and future automated engines.

## 2. Technical Architecture

### Core Stack
*   **Language:** Python 3 (managed via `uv`)
*   **Database:** SQLite (`simple_journal.db`) for long-term archiving and manual trade entry persistence.
*   **Data Processing:** `pandas` and `numpy` for financial calculations (WAC, realized/unrealized P/L, AAGR).
*   **Market Data:** `yfinance` for fetching near real-time prices.
*   **IBKR Integration:** `requests` and `xml.etree.ElementTree` to interface with the Interactive Brokers Flex Web Service (XML/CSV).
*   **UI/CLI:** `rich` for professional, formatted terminal dashboards.

### Module Structure (Separation of Concerns)
The project is organized into 6 core modules to ensure a clear separation of concerns and prevent circular imports:

1.  **`main.py`**: **The Controller.** Manages the interactive CLI menu and orchestrates the flow between logic and presentation.
2.  **`config.py`**: **The Configuration.** Centralizes environment variables (`.env`), directory paths (defaulting to `data/` or a custom `DATA_PATH`), and file constants.
3.  **`db.py`**: **The Storage Layer.** Manages the SQLite schema, migrations (e.g., adding `description`), and basic CRUD operations.
4.  **`portfolio_manager.py`**: **The Logic Engine.**
    *   Implements the core portfolio math and IBKR-to-Yahoo ticker mapping.
    *   Calculates AAGR (Annualized Growth) and % NAV exposure.
    *   Handles "Reset-on-Zero" logic.
5.  **`ibkr.py`**: **The Data Bridge.** Handles the multi-step handshake with IBKR Flex Service to download Trade Confirmations and NAV reports.
6.  **`dashboard.py`**: **The View Layer.** A pure presentation module that renders professional tables with conditional formatting (P/L colors) using `rich`.

### Dashboard Requirements
The following metrics are required for the primary dashboard:
| Name | Ticker | Date | Qty | Entry | Price | P/L | CCY | Pct | AAGR |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Name | Ticker | First entry date | Total quantity | Average entry price | Current price | Unrealized P/L | Currency | Unrealized % | Annualized Growth |

## 3. Data & Risk Management

### Source Files & Locations
*   **Primary Input:** `trades_manual.csv` in the data directory.
*   **IBKR Data:** Flex Query exports (e.g., `2025_FY.csv`, `2026_YTD.csv`).
*   **Storage Path:** Data files are centrally managed in a OneDrive shared folder to ensure persistence and accessibility:
    `C:\Users\User\OneDrive\Accounts\HTC_EOOD\TradeJournalData`

### Risk Management Protocols (Roadmap)
*   **Kill Switch:** Support for portfolio-level stops (e.g., "Block all buys if Daily Drawdown > 1.5%").
*   **ATR Integration:** Adaptive stop-loss and take-profit levels using Average True Range (ATR) to adjust for market volatility.
*   **Capital Preservation:** All logic prioritizes the safety of the family portfolio over aggressive growth.
*   **Cost Basis:** Use FIFO or Weighted Average Cost (WAC) refinement for tax-optimization simulations.

## 4. Setup & Operations

### Installation & Execution
*   **Dependency Management:** Uses `uv`. Install via:
    ```bash
    uv pip install requests rich yfinance pandas python-dotenv
    ```
*   **Running the Application:**
    ```bash
    python main.py
    ```

### Configuration (.env)
The system requires a `.env` file in the root with the following structure:
```env
IBKR_TOKEN="YOUR_TOKEN"
IBKR_QUERY_ID_TRADES="YOUR_TRADES_QUERY_ID"
IBKR_QUERY_ID_NAV="YOUR_NAV_QUERY_ID"
DATA_PATH="C:\Users\User\OneDrive\Accounts\HTC_EOOD\TradeJournalData"
```

### Development Conventions
*   **Ticker Mapping:** IBKR symbols are mapped to Yahoo Finance tickers via heuristics (e.g., `.DE` for XETRA, `-P` for preferred shares).
*   **Safety:** `.gitignore` excludes `.venv`, `.env`, and local data files to protect sensitive financial history.


### Testing
When you finish a feature always create a test and make sure if it is working properly. Ask me questions if you have to.

## 5. Development Log

### [2026-02-14] Branch Initialization
*   Created branch `gemini-development`.
*   Committed initial project structure including GitHub workflows and `GEMINI.md`.
*   Established this log to track autonomous development steps.

### [2026-02-14] Documentation & Git Configuration
*   Updated `.gitignore` to include `GEMINI.md` and remove `.gemini`.

### [2026-02-14] Incremental IBKR Sync & Archiving
*   Implemented `sync_ibkr_trades()` in `ibkr.py`.
*   Added logic to archive existing YTD files before downloading fresh data.
*   Added automatic processing of previous year's Full Year (FY) data if present.
*   Integrated the new sync option into the CLI menu in `main.py`.

### [2026-02-14] Testing & Dependency Management
*   Added missing dependencies (`pandas`, `python-dotenv`) via `uv`.
*   Created automated test suite in `tests/test_ibkr.py` to verify synchronization logic.
*   Verified that `main.py` starts correctly and tests pass.

### [2026-02-14] DB Metadata & Live Dashboard
*   Extended `trades` table schema to include `Conid`, `ListingExchange`, `Currency`, and `UnderlyingSymbol`.
*   Refactored `PortfolioManager` to load trades directly from SQLite by default.
*   Implemented idempotent sync to fill gaps in database without duplicates.
*   Refactored dashboard into discrete calculation and formatting substeps.
*   Added **LIVE Portfolio** dashboard with 30-second auto-refresh.

### [2026-02-15] End-to-End Integration Testing
*   Created `tests/test_integration.py` providing a full mock of the IBKR -> DB -> Position -> Dashboard flow.
*   Verified "Reset-on-Zero" math and P/L calculations within the integration suite.

### [2026-02-15] Instrument Filtering & Local-First Policy
*   Implemented instrument selection menu (Stocks, Options, Bonds, All).
*   Updated `PortfolioManager` to support multi-category filtering (e.g., STK + ETF).
*   Implemented "Local-First" data policy: dashboard uses DB/local files by default; network sync must be explicitly triggered.
*   Resolved `UnicodeEncodeError` by replacing emojis with standard text symbols in console output.
*   Integrated IBKR report date into NAV and Portfolio headers.

### [2026-02-15] Granular CLI Menu Structure & Data Integrity Fixes
*   Restructured main menu into four distinct operations: Fetch Trades, Fetch NAV, Incorporate CSVs, View Dashboard.
*   Added support for fetching specific years (FY/YTD) from IBKR while maintaining `trades.csv` as the quick default.
*   **Opening Balance Fix:** Implemented `cp1251` encoding and header-skip logic for `open_positions.csv` migration.
*   **Double-Counting Prevention:** Updated ledger replay to reset an asset's history when an `OPENING_BALANCE` source is encountered.
*   Verified XLB share count correctly totals 1,418.

### [2026-02-15] Dashboard Sorting & Test Isolation
*   Implemented sorting functionality for the portfolio dashboard (Ticker, Market Value, P/L %).
*   Updated `main.py` and `dashboard.py` to support user-selected sorting preferences.
*   Created `tests/test_dashboard_sort.py` to verify sorting logic.
*   Fixed `tests/test_integration.py` to ensure complete isolation from real data files by patching `IBKR_TRADES_CSV`.

### [2026-02-15] Simplified Trade Fetching Logic
*   Restructured the "Fetch Trades" menu to distinguish between Current Year (YTD) and Specific Year (Full Year).
*   Enforced "Full Year" mode for specific year downloads, removing the manual toggle.
*   Updated `ibkr.py` logs to reflect the YTD focus for recent history.

### [2026-02-15] Data Directory Cleanup & Storage Centralization
*   Confirmed `simple_journal.db` is correctly managed in the central OneDrive directory (`C:/Users/User/OneDrive/Accounts/HTC_EOOD/TradeJournalData`).
*   Deleted the redundant local `data/` directory to maintain a single source of truth and prevent configuration confusion.

### [2026-02-15] Risk-Focused Dashboard & Hybrid Open Logic
*   **Portfolio Logic**: Refactored `PortfolioManager` to use a **Hybrid approach** (IBKR Snapshot as ground truth + Ledger for recent manual trades). Added a **Pure Ledger Replay** mode for comparison and auditing.
*   **Market Data**: Implemented **Smart Market Data** with online ISIN searching via Yahoo Finance, automated Option ticker construction, and an IBKR **MarkPrice fallback** to eliminate `nan` prices.
*   **Manual Trade Management**: Added a dedicated interface in `main.py` allowing **single-line entry** (e.g., `aapl, buy, 100, 112.5`) and database persistence.
*   **Visual Refactor**: Updated the dashboard to **group positions by Asset Class**, added absolute **P/L** and **AGE** (investment duration) columns, and implemented professional subtotals and grand totals.
*   **Data Integrity**: Fixed a duplication bug by filtering IBKR CSV imports for `EXECUTION` rows only and optimized database loading to target only active positions.
