# Session Log: Scale-In Refinement & Structured Help Desk

**Date:** 2026-03-02  
**Status:** Completed  

## Objectives
- Resolve capital outlay vs. share count contradictions in the Risk Audit.
- Implement configurable Scale-In Step sizes (0.5x vs 1.0x ATR) with Smart Default logic.
- Overhaul the Help System into a structured, tabbed "Help Desk".
- Implement upside triggers for Scale-In and Take Profit milestones with improved visual separation.

## Technical Changes

### Core Risk Engine (`core/risk_engine.py`)
- **Backwards Compatibility**: Updated `calculate_position_risk` to handle varying risk profile tuple lengths gracefully, preventing crashes during schema transitions.
- **Configurable Scaling**: Integrated `scale_step` into the mathematical roadmap calculation.

### Database (`db.py`)
- **Schema Update**: Added `scale_step` column to `risk_profiles` table.
- **Migration**: Added a robust migration block to safely add the column to existing databases without data loss.

### Risk Workspace (`risk_workspace.py`)
- **Structured Help Desk**: Converted the single-block F1 help text into a `TabbedContent` interface with four categories: Visual Glossary, Metrics & Audit, Scale-In Guide, and Strategy Lab.
- **Smart Default Logic**: Implemented an automated detector for scale steps. ATRs <= 1.2x daily baseline are treated as Micro trends (1.0x step), while larger ATRs are treated as Macro trends (0.5x step).
- **Upside Triggers**: 
    - Removed high-intensity green price backgrounds to reserve color-blocks for emergency Stop Breaches.
    - Added Ticker-adjacent indicators: `⬆` for Scale-In adds and `★` for Take Profit targets.
- **Roadmap Clarity**: Added 3-state logic for Roadmap milestones: Pending (standard), Triggered (yellow warning), and Filled (dim green checkmark).
- **Financial Fix**: Pivoted "Remaining Cap" to be quantity-aware. It now correctly shows 0 EUR if the target share count is already met, even if current cost is below the theoretical budget.

## Logic & Decisions
- **Signal vs. Noise**: Decided to remove the green background from prices. In a high-stakes trading environment, background color should only signal "Capital at Risk" (Red). Upside opportunities are secondary and use icons instead.
- **Micro vs. Macro Scaling**: Implemented the rule that tight stops (Micro) require more price confirmation (1.0x step) to avoid whipsaws, while wide stops (Macro) allow for faster compounding (0.5x step).

## Verification
- **Stability**: Fixed a `MarkupError` caused by unescaped `[/S]` tags in the help markup.
- **Integrity**: Verified that switching strategies in the sandbox correctly triggers the new smart-default step assignment.

## Next Steps
- Implement "Bulk Actions" for closing multiple breached positions simultaneously.
- Refine the Trailing Stop ratchet to allow for manual high-water mark overrides if needed.
