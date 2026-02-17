# Trading Desk Project

## 1. Application Development

### Client Portal API
**Understanding the Architecture** - *[website](https://interactivebrokers.github.io/cpwebapi/)*
Before we write any code, it is critical to understand that the Client Portal API (CP API) works a bit differently than a standard web API.
Because financial data is highly sensitive, IBKR requires a "bridge" between your Python script and their servers.
1. You (Python script in VSCode) send a request to your local machine (usually https://localhost:5000).
2. The Gateway (a small Java program running on your PC) receives this, handles the complex encryption/authentication, and forwards it to IBKR.
3. IBKR sends the data back to the Gateway, which passes it to your script.

So, we cannot just "query the API" directly from Python without this Gateway running.

**Next Steps**
1. The Setup (The Gateway) 🏗️ We can start by downloading and configuring the Client Portal Gateway. This is often the trickiest part because it involves handling a secure certificate (since it runs on https) and getting it to "talk" to your browser for the initial login.
2. The Data (The Endpoints) 📊 If you already have the Gateway running (or want to see the capabilities first), we can look at the specific API Endpoints (URLs) you will use to fetch Intraday PnL, Portfolio Risk, and specific Position data.
3. The Code (Python Structure) 🐍 We can sketch out the Python class structure in VSCode that will handle the requests, manage the session cookies (crucial for this API), and parse the JSON data into a clean "Risk Dashboard" format.

Steps to start the gataway:
1. In VSCode terminal go to: cd C:\ibkr_gateway
2. In VSCode terminal run: bin\run.bat root\conf.yaml
3. Go to: https://localhost:5000

### Trade history
This should reconcile into the NAV. But also it's purpouse is to track time value of my investment for risk management purpuses.
- When calculating ATR it matters on what date you started buying the instrument
- When assigning trailing or fixed stop, it matters what is your cost base

To do:
- [ ] Use **Conid** the specific instrument, **BUY** * **Price** * **Quantity** equals the *Cost Base*.
- [ ] When you want to sell something use FIFO or weighted average approach. Which one is better if you have a longer holding period and the market usually goes up?
- [ ] Use one method to fetch data - from IBKR and from yfinance
- [ ] Use one method to parse through the data that you've fetched
- [ ] Risk management - we need to keep certain datapoints in a database or a .json file. For example the first date of entry. Think about this..
- [ ] My father loves me.
- [ ] Simulate a purchase - provide ticker, entry date, entry price - it calculates ATR and provides a recommendation on how much you need to buy.

### Useful notes
VSCode plug-in - All you need to write Markdown (keyboard shortcuts, table of contents, auto preview and more)
Outline - uses the MD headers to create a table of content, you can see it at the bottom left corner of VSCode

### Code
```python
# A simple risk check
def check_limit(position_size):
    if position_size &gt; 100000:
        return &quot;Risk limit exceeded&quot;
    return &quot;Trade approved&quot;
```
### Dashboard
The information that is required in the dashboard is the following:
|Name|Ticker|Date|Qty|Entry|Price|P/L|CCY|Pct|AAGR|
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
|Name|Ticker|the first entry date|total quantity|avearge entry price|current price|unrealized profit|currency|unrealized profit %|average annualized growth rate|

note: [Difference btw. CAGR and AAGR](https://share.google/aimode/FEmi3YkShRDfJyib9)

### Issues
1. When calculating Trade History I use the Trade Confirmation Flex Query.
    - Quantity - Positive when you buy and negative when you sell -> the sum should equal **zero** if your entry and exit are in the time period that is being reported. Otherwise, you will have to go back to collect all entry points that will bring you to the full position size, which you sold in this period.

## 2. Risk Management
### Stop-Loss Rules


## 3. Development Log

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



### [2026-02-15] ATR Risk Engine & Dynamic Trailing Stops

*   **ATR Implementation**: Created `risk_engine.py` to calculate multi-period ATR (21d, 12w, 6m, 8q) using both SMA and EMA methods.

*   **Trailing Stop Logic**: Implemented automated "Max Price Since Entry" detection to calculate real-time trailing stop-loss levels.

*   **Persistent Risk Settings**: Added `position_risk` database table to store assigned ATR values and stop types (Fixed/Trailing) per ticker.

*   **Manual Risk Assignment**: Added CLI interface to assign risk parameters to active positions via single-line input.

*   **ISIN Resolver**: Centralized ticker resolution in `PortfolioManager` to use ISIN for guaranteed matching between IBKR and Yahoo Finance.

*   **Dashboard Expansion**: Integrated risk metrics into the main view with new columns for **DATE**, **P/L**, **ATR**, **SL PRICE**, and **TP PRICE**.

*   **UI Compactness**: Minimized horizontal spacing (padding=0) and implemented short date format (DD/MM/YY) for better terminal fit.

