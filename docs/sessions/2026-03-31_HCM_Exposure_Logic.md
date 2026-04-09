# Session Log: "Higher of Cost or Market" (HCM) Exposure Logic
**Date:** 2026-03-31

## Objectives
- Implement a conservative institutional exposure auditing protocol.
- Ensure position limits are anchored to the higher of the original capital commitment (Cost Basis) or current valuation (Market Value).
- Prevent "averaging down" traps for underwater positions.

## Technical Changes
### Position Model (`models.py`)
- Added `hcm_value` property to the `Position` class. This provides a single source of truth for conservative valuation: `max(entry_price, current_price) * qty * multiplier`.

### Risk Engine (`core/risk_engine.py`)
- **`audit_position_risk`**: Updated to use `exposure_val = max(entry_price, current_price) * qty * multiplier`. This affects the `adjustment` (Add/Trim) signal.
- **`calculate_pilot_entry`**: Updated signature to accept `current_qty`. Refactored target quantity calculation to ensure total HCM exposure stays within limits.

### Portfolio Manager (`core/portfolio_manager.py`)
- **`_enrich_metrics`**: Updated the dashboard `nav_pct` calculation to use `p.hcm_value`. The "Exposure" column now reflects the conservative commitment.

### Risk Workspace (`risk_workspace.py`)
- **UI & Modeling**: Synchronized the main grid, scale-in triggers, and Strategy Lab modeling with the HCM standard. The Sandbox now correctly flags "тЪа" (Limit Exceeded) based on conservative commitment.

## Logic & Decisions
- **Conservative Anchoring**: By using HCM, we eliminate the math-driven temptation to add to losers. If a position drops 50%, the system still treats it as its original 100% cost commitment, meaning no "free room" is created by the loss.
- **Winning Discipline**: For profitable positions, using Market Value ensures that growth is correctly accounted for as exposure, triggering profit-harvesting (Trim) signals when limits are reached.

## Verification
- **Underwater Scenario**: Verified that positions with losses show exposure based on original cost, effectively blocking "averaging down" additions if the original limit was reached.
- **Winner Scenario**: Verified that profitable positions show exposure based on current market price, triggering trimmings as expected.
- **Lab Modeling**: Confirmed that the "Exp" cell in the Strategy Lab accurately reflects the purchase commitment using HCM logic.

## Next Steps
- Add automated unit tests for HCM valuation scenarios in `tests/test_risk_engine.py`.
- Audit bond-specific scaling logic to ensure HCM valuation works correctly with 10x multipliers.
