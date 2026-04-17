# Session: Institutional Risk Reconstruction

## Objectives
- Clarify Pilot Stop vs. Inception Stop definitions.
- Reconstruct historical 'Risk Anchors' using 12-Quarter Wilder ATR at time of entry (Option B).
- Align Audit UI with volatility expansion metrics.

## Technical Changes
- **Database**: Extended isk_profiles with inception_atr and conditional update logic.
- **Models**: Added inception_atr and InceptionATR (for dict/UI) to Position dataclass.
- **UI (Risk Workspace)**: Updated Help Desk definitions. Integrated 'Inception ATR' and 'Expansion %' into the Audit Terminal.
- **UI (Dashboard)**: Enriched details sidebar with 'Initial ATR'.
- **Tooling**: Created econstruct_inception_risk.py to perform historical volatility recovery.

## Logic & Decisions
- **Pilot Stop Defined**: The stop for the *full aggregate position* after a scale-in tranche is added.
- **12q ATR Reconstruction**: Leverages 3.5 years of historical data ending at the entry date to establish the original volatility regime.
- **Expansion Signaling**: Visual red flag in Risk Workspace if current volatility has expanded >10% since inception.

## Verification
- Successfully executed econstruct_inception_risk.py across the portfolio.
- Verified that PSA, META, AVGO, and others now have sound historical anchors.
- Verified that new Watch List ideas correctly capture current ATR as inception ATR.

## Next Steps
- Audit portfolio for 'Volatility Creep' (positions where expansion has made the original stop mathematically invalid).