# 2026-03-31: NAV Synchronization and UI Refinement

## Objectives
- Identify the source of the NAV used for percentage-based risk calculations.
- Synchronize NAV and currency across the Risk Workspace, Dashboard, and Main Menu.
- Fix UI bugs related to NAV currency display.
- Improve scrollbar visibility and functionality in the ATR Discovery section of the Risk Workspace.

## Technical Changes

### Core Logic & Services
- **`services/ibkr_parser.py`**: Updated `parse_nav_csv` to return a 4-element tuple including the `currency` (extracted from the `CurrencyPrimary` column). Ensured all error and empty-file paths also return 4 values.
- **`core/portfolio_manager.py`**: Updated `fetch_nav_data` to handle and return the new 4-element tuple.

### UI & UX
- **`main.py`**: 
    - Updated the menu to display the current AUM (Total NAV) and currency next to the "Risk Workspace" and "View Dashboard" options.
    - Updated `main()` to fetch NAV once at startup and refresh it after a sync.
- **`risk_workspace.py`**:
    - Fixed a bug where the account list was being assigned to the currency variable.
    - Updated CSS for `#discovery-layout` to support `overflow-y: auto`.
    - Enabled forced horizontal scrolling for `#fixed-stop-table` and `#trailing-stop-table` to ensure all columns (P/L, R, BUF%) are visible on laptop screens.
    - Increased `scrollbar-size` to `2 2` for better visibility.
- **`dashboard.py`**:
    - Updated the `fetch_data` loop and `print_nav_table` to handle the 4-element NAV tuple.
    - Switched to explicit if-else unpacking for the NAV result to prevent "too many values to unpack" errors.
- **`kids_fund_dashboard.py`**: Updated `action_refresh` to correctly unpack the 4-element NAV tuple.

## Logic & Decisions
- **Consolidated NAV**: Confirmed that the "Single Source of Truth" for the portfolio's denominator is the sum of the "Total" equity column across all accounts in the IBKR `nav_lbd.csv` report.
- **Currency Support**: Moved from hardcoded "€" to dynamic currency extraction from the IBKR report to support multi-currency account reporting.

## Verification
- **NAV Extraction**: Manually verified that the sum of the "Total" column in `nav_lbd.csv` equals the ~2,255,742 EUR displayed in the UI.
- **Error Resolution**: Fixed the "too many values to unpack" error that occurred during background refreshes after the service signature change.

## Next Steps
- Investigate why horizontal scrollbars remain elusive on the user's laptop despite CSS overrides.
- Consider adding a global "Currency Setting" if IBKR reports provide mixed currencies across accounts.
