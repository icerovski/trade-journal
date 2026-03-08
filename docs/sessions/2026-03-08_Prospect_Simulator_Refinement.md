# Session Log: Prospect Simulator Refinement & Sizing Logic

**Date:** 2026-03-08
**Status:** Completed

## Objectives
- Resolve the "0.0 Trailing Base" issue for prospective stock simulations.
- Implement hypothetical sizing for prospects to show meaningful P/L at Stop and Risk (R) metrics.
- Ensure the Risk Audit sidebar and Grid row react instantly to simulation inputs.

## Technical Changes

### Risk Engine (`core/risk_engine.py`)
- **Market Price Anchoring**: Updated `get_atr_discovery_data` to automatically use the current market price as the "Effective Entry" when actual cost basis is unknown (0.0). This ensures `SL%` and `R` calculations are anchored to the current volatility floor.
- **Hypothetical sizing**: Implemented logic to calculate a "Standard Unit" size for prospects (qty=0). If no shares are owned, the engine now calculates P/L and R based on the maximum shares allowed by the 1% Risk and 5% Exposure limits.

### Risk Workspace (`risk_workspace.py`)
- **Reactive Modeling**: Updated `on_strategy_change` to use the discovered market price as the anchor for both Fixed and Trailing stops during simulation.
- **Grid Row Enrichment**: Enabled the `[PROSPECT]` grid row to display live modeling math (Stop Price, SL%, Risk, P/L Stop) instead of "---" placeholders.
- **Sidebar Integration**: Enhanced `refresh_risk_checklist` to display full roadmaps and audits for prospective purchases by passing hypothetical strategy parameters.
- **Error Handling**: Improved error logging during modeling to prevent silent calculation failures.

## Logic & Decisions
- **Standard Unit Sizing**: Decided to use the system's "Dual-Constraint" target as the baseline for prospect risk metrics. This provides the user with an immediate answer to: "What is my maximum institutional loss if I buy this stock right now?"
- **Temporary Grid Injection**: Retained the behavior of injecting a `[PROSPECT]` row into the main grid to allow for side-by-side comparison with existing holdings during discovery.

## Verification
- Verified that discovering `USCI` now shows valid `SL%` (non-zero) in the discovery tables.
- Confirmed that the `[PROSPECT] USCI` grid row correctly fills with math when a strategy (e.g., `25 t s`) is entered.
- Verified that the sidebar roadmap (Stage 1, 2, 3) now projects correctly for 0-qty prospects.

## Next Steps
- Implement "Bulk Action" for closing multiple breached positions simultaneously.
- Refine the Trailing Stop ratchet to allow for manual high-water mark overrides if needed.
