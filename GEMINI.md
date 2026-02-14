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
