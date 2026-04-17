# Session: Architectural Refactor & Cleanup

## Objectives
- Standardize risk data flow using structured objects instead of fragile tuples.
- Centralize asset-specific scaling and valuation logic.
- Modularize UI components for improved maintainability.
- Perform system-wide cleanup of temporary files.

## Technical Changes
- **Models**: Introduced RiskProfile dataclass to formalize risk configuration.
- **Database**: Refactored db.py to return RiskProfile objects for all retrieval queries.
- **Asset Registry**: Centralized Bond/Bill scaling logic in AssetRegistry.standardize_asset_quantity_and_multiplier.
- **UI Utils**: Created core/ui_utils.py for centralized theme colors and financial formatting.
- **UI Components**: Extracted HelpScreen from isk_workspace.py into services/ui_components.py.
- **Risk Engine**: Refactored calculate_position_risk to utilize the RiskProfile object.
- **Cleanup**: Deleted temporary investigation scripts and moved econstruct_inception_risk.py to 	ools/.

## Logic & Decisions
- **Type Safety**: Moving to dataclasses for database rows significantly reduces the risk of 'index-out-of-range' errors during schema updates.
- **DRY Principle**: Centralizing Bond scaling logic removes duplication between the flex parser and the portfolio manager.

## Verification
- Executed erify_system.py (now deleted) which confirmed all green for DB, Models, Risk Engine, and UI components.
- Verified UI stability after modularizing the Help Desk.

## Next Steps
- Continue modularizing isk_workspace.py to separate audit logic from layout logic.