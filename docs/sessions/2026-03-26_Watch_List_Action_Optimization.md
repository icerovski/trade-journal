# Session Log: Watch List & Portfolio Action Optimization

**Date:** 2026-03-26
**Session ID:** WatchList-Action-Refinement-v1

## Objectives
- Refine the Watch List lifecycle for better entry timing.
- Implement a "Meaningful Action" indicator for the Portfolio Risk Status.
- Align help documentation with the updated workflows.

## Technical Changes
- **main.py**: 
    - Added real-time Watch List counter to the main menu.
- **risk_workspace.py**:
    - Added "Watch List & Entry" tab to the F1 Help screen.
    - Implemented "ACTION" column in the Portfolio Risk Status table.
    - Added asymmetric materiality thresholds for scaling: 10% for adding shares, 5% for trimming shares.
- **watch_list_workspace.py**:
    - Enhanced the prospects table with real-time Price, Buffer %, and Risk % metrics.
    - Integrated `PortfolioManager.get_dashboard_df` for consistent data enrichment.

## Logic & Decisions
- **Asymmetric Materiality:** Risk reduction (trimming) is prioritized with a 5% sensitivity threshold, while position expansion (topping up) requires a higher 10% conviction threshold to reduce transaction noise.
- **Watch List Lifecycle:** Formally documented the "Prospect -> Watch -> Active" flow to ensure auditability and ease of use for new entries.

## Verification
- Verified that "ACTION" signals appear correctly in the Risk Workspace based on the 10%/5% logic.
- Confirmed the Watch List counter correctly reflects the database state.
- Verified that the technical analysis (Confluence/Trend) in the Watch List Command Center uses real-time pricing.

## Next Steps
- Investigate persistent "NoneType" errors in `yf.download` during batch fetches.
- Finalize the "Emergency Banner" for the main menu to signal active stop breaches.
