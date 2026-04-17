# Session: Inception Risk Anchor

## Objectives
- Implement a permanent 'Risk Anchor' to track the initial stop loss set for every position.
- Allow for auditing of trailed stop distance.
- Fix background thread lifecycle bugs in the Dashboard.

## Technical Changes
- **Database**: Added inception_stop column to isk_profiles.
- **Models**: Added inception_stop to Position dataclass.
- **Risk Engine**: Updated calculation logic to handle and propagate the inception anchor.
- **Portfolio Manager**: Ensured anchor consistency during account consolidation.
- **UI (Risk Workspace)**: Added Inception Stop and Trailed Distance display to the Audit Sidebar.
- **UI (Dashboard)**: Added Inception Stop display to position details sidebar.
- **Stability**: Implemented on_unmount and defensive checks in dashboard.py to prevent RuntimeError on exit.

## Logic & Decisions
- **Immutability**: The inception_stop is set once upon profile creation (WATCH or ACTIVE) and preserved throughout the position lifecycle.
- **Healed Context**: Inception stop is propagated when a [PROSPECT] is promoted to [OWNED], ensuring the original risk intent is never lost.
- **Thread Safety**: Dashboard background thread now respects the Textual app lifecycle via an exit event flag.

## Verification
- Successfully migrated database schema via init_db().
- Verified that inception stops are correctly captured and displayed in both Risk and Dashboard workspaces.

## Next Steps
- Implement R-Multiplier performance metrics (Current P/L / Inception Risk).