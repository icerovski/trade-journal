# Session Log: 2026-04-15 - Stop Loss Philosophy Documentation

## Objectives
- Clarify the system's internal handling of Stop Losses (Fixed Dollar vs. Percentage).
- Document the "Volatility Buffer" rationale for institutional risk management.
- Update technical documentation to reflect the "Fixed Dollar" persistence logic.

## Technical Changes
- **docs/TECHNICAL_DOCS.md**: Added Section 4 "Stop Loss Philosophy: Fixed Dollar vs. Constant Percentage".
    - Explained the one-time calculation of percentage to dollar amount (`atr_value`).
    - Detailed the behavior of Trailing Stops as fixed dollar offsets.
    - Documented the "Tightening" effect on SL % during price appreciation.

## Logic & Decisions
- **Fixed Dollar Persistence**: Confirmed that `risk_profiles.atr_value` stores a constant dollar amount. This ensures that the "statistical noise" allowance for an asset remains consistent throughout a trend, rather than expanding with price (which would happen with a constant percentage).
- **Institutional Alignment**: Standardized documentation to emphasize "Volatility-Adjusted Proximity" and "Risk-Unit ($) Consistency."

## Verification
- Codebase audit of `core/risk_engine.py` and `db.py` confirmed that `atr_value` is used as a fixed offset from the base price.
- `risk_workspace.py` confirmed to perform the one-time % to $ conversion during strategy submission.

## Next Steps
- Consider adding an `original_atr_pct` column to the database to track inception-risk targets vs. current tightened stops.
