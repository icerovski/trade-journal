# Session Log: Risk Workspace Layout Optimization

## Objectives
- Couple the "Assign Risk Strategy" input area with the main Portfolio Table for better ergonomic flow.
- Ensure the right pane acts as a dedicated research and modelling sidebar.
- Improve the visibility and responsiveness of the Asset Context panel.

## Technical Changes
### View Layer (`risk_workspace.py`)
- **Layout Refactor:** Moved the `input-container` (Assign Risk Strategy) from the right pane to the bottom of the left pane. 
- **Pane Balancing:** Standardized on a **60/40 split** between the Portfolio Grid and the Discovery sidebar.
- **Context Fix:** Increased the `position-context` panel height to 4 to prevent border clipping and implemented `update_context_only()` for instant responsive feedback when highlighting rows.
- **Visual Spacing:** Added specific padding to the left and right panes to ensure clear separation of concern between "Audit" (left) and "Research" (right).

## Logic & Decisions
- **Action-Selection Coupling:** By moving the input widgets directly under the selection table, the user's focus remains on the left side of the screen during the primary task (mass assignment), reducing eye strain and mouse/tab travel.
- **Sidebar Paradigm:** The right pane now exclusively handles "Modelling" (Fixed vs. Trailing comparison), making it clear that it is a reference zone rather than an action zone.

## Verification
- Verified that the `position-context` text is fully visible.
- Confirmed that highlighting a row updates the Name and Date immediately while ATR data loads.

## Next Steps
- Continue refining the vertical height distribution of discovery tables to prevent overflow on smaller terminal windows.
- Assess the integration of the "De-risking Path" in the expanded left-pane grid.
