# Session Log: 2026-04-01 - Risk Audit Precision & SOLID Analysis

## Objectives
- Resolve contradictory "Add Shares" vs "Remaining Cap" metrics in the Risk Workspace.
- Synchronize price anchoring for risk auditing to follow institutional mandates (Current Market Price).
- Perform a SOLID principles audit and provide architectural recommendations.

## Technical Changes
### Core Risk Engine (`core/risk_engine.py`)
- **Synchronized Price Anchoring**: Refactored `audit_position_risk` to use `current_price` instead of `entry_price` when calculating "Shares to Add" (room). 
- **Preserved Trim Logic**: Maintained `entry_price` anchoring for "Trim" operations to accurately reflect risk reduction relative to inception cost.

### Risk Workspace UI (`risk_workspace.py`)
- **Metric Unification**: Consolidated financial calculations (`market_val`, `target_outlay`, `remaining_cap`) into a single block to ensure consistency between the Execution Plan and the audit metrics.
- **Enhanced Transparency**: Added **Market Value** to the Audit Panel.
- **Label Correction**: Updated the "To reach X sh" label to reflect the actual quantity determined by the audit adjustment rather than the legacy pilot target.

### Regression Testing
- Created `tests/test_risk_engine.py` with two primary test cases:
    - `test_audit_position_risk_current_price_anchoring`: Verifies 100-share adjustment for breakeven stops.
    - `test_audit_position_risk_trimming_uses_entry`: Verifies correct risk reduction for underwater positions.

## Logic & Decisions
- **The "Audit-First" Rule**: In `SINGLE` entry mode, the Execution Plan now leads with the Audit results (hard limits) rather than Pilot results (strategic targets). This ensures the user is never told to buy more shares than their Risk or Exposure limits allow.
- **Dynamic Anchoring**: By switching to `current_price` for new shares, we recognize that the risk of a *new* share is the distance from the *current* market price to the stop, not the original entry price of the existing position.

## Verification
- **Reproduction**: Successfully reproduced the "Add 476 shares / Remaining Cap: 0" bug using a standalone script.
- **Validation**: Confirmed the fix with the same script, showing consistent behavior (e.g., "Add 100 shares / Remaining Cap: 11,000").
- **Pytest**: All new tests passed with `PYTHONPATH="."`.

## SOLID Audit Results
- **DIP Violation**: Core logic is heavily coupled to the `sqlite3` implementation in `db.py`. Recommendation: Introduce a Repository pattern.
- **SRP Issues**: `PortfolioManager` is a "God Class" handling both reconciliation and UI formatting. Recommendation: Extract metadata healing to a dedicated service.
- **OCP Limitations**: `AssetRegistry` uses hardcoded if/else for Bonds. Recommendation: Implement an Asset Strategy pattern.

## Next Steps
- Implement Repository pattern for `db.py` to decouple core logic from SQLite.
- Refactor `AssetRegistry` into a Strategy Factory.
- Sync changes to OneDrive.
