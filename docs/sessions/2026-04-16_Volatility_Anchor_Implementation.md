# Session: Volatility Anchor (Inception ATR)

## Objectives
- Supplement the 'Inception Risk Anchor' with a 'Volatility Anchor' by storing the initially assigned ATR.
- Enable auditing of volatility expansion/contraction relative to initial entry.

## Technical Changes
- **Database**: Added inception_atr column to isk_profiles. Updated set_position_risk and promote_prospect_to_active to persist this anchor.
- **Models**: Added inception_atr to Position dataclass and dictionary exports.
- **Risk Engine**: Updated calculation logic to handle and propagate the inception ATR anchor.
- **UI (Risk Workspace)**: Added 'INCEPTION ATR' and expansion percentage (e.g., +15%) to the Audit Sidebar.
- **UI (Dashboard)**: Added 'Initial ATR' display to the position details sidebar.

## Logic & Decisions
- **Volatility Delta**: Calculated as (Current ATR / Inception ATR) - 1. Highlighted in red if expansion > 10% to signal increased risk regime.
- **Persistence**: Similar to the stop anchor, the inception_atr is captured only once (when NULL) to preserve the original entry context.

## Verification
- Successfully migrated database schema via init_db().
- Verified that inception ATR is correctly captured for new modeled strategies and carried over during prospect promotion.

## Next Steps
- Audit portfolio-wide volatility expansion during market corrections.