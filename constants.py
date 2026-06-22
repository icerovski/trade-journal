# Numeric thresholds used across multiple modules.
# Centralised here so changes propagate everywhere and the intent is explicit.

# Minimum quantity treated as non-zero throughout the ledger.
# Prevents floating-point dust from keeping ghost positions alive.
QTY_ZERO_THRESHOLD = 0.0001

# Minimum annualised age used as the AAGR denominator.
# Floors positions younger than ~2 weeks to avoid extreme AAGR readings.
AAGR_MIN_YEARS = 0.04

# Capital-efficiency ("dead money") flag. A position older than STALE_MIN_AGE_DAYS
# whose annualised unrealised return (AAGR) is below CAPITAL_HURDLE_PCT is flagged
# STALE — the capital is not clearing the opportunity-cost hurdle and warrants review.
# Orthogonal to the ATR exit ladder: answers "is this capital working?", not "take profit?".
CAPITAL_HURDLE_PCT = 8.0
STALE_MIN_AGE_DAYS = 180

# Regime hysteresis. The 200-DMA direction-day count resets to ~1 on any reversal,
# so a single counter-trend day would otherwise crash a long TREND straight to RANGING.
# A DMA reversal must persist this many days before it demotes the regime to RANGING;
# until confirmed, the position is held one notch up at NORMAL. Dampens boundary whipsaw.
REGIME_REVERSAL_CONFIRM_DAYS = 3

# ATR-distance thresholds for the confluence engine.
# A level within CONFLUENCE_ATR_THRESHOLD of price/stop is "in the zone".
# Within CONFLUENCE_FORTRESS_THRESHOLD it is a "fortress" level.
CONFLUENCE_ATR_THRESHOLD = 0.25
CONFLUENCE_FORTRESS_THRESHOLD = 0.10

# Status-colour multipliers for the dual-constraint audit.
# RED fires when actual exceeds the custom limit by these factors.
RISK_RED_MULTIPLIER = 1.5
EXPOSURE_RED_MULTIPLIER = 1.1

# Both stop types: TP is placed TP_ATR_MULTIPLE ATRs above entry → ladder is M1=+1, M2=+2, TP=+3.
# (Anchoring TRAILING TP to the ratcheted stop made it collide with M2 at inception.)
# This is the DEFAULT multiple; a per-position override (risk_profiles.tp_atr_mult) can
# extend the target to any multiple of the SAME frozen inception ATR (e.g. 4R, 5R), keeping
# the target reachable and stable — editing the live stop ATR never moves it. M1/M2 always
# stay on the inception ATR for reference.
TP_ATR_MULTIPLE = 3

# Setup reward:risk floor. When a target is set, the FORWARD reward:risk from the current
# price — (target − price) / (price − stop) — is flagged if it falls below this. Lets the
# user control that an extended target still pays at least 3:1 from here.
RR_SETUP_FLOOR = 3.0

# --- Entry/Exit Zone Scanner ------------------------------------------------
# Composite volume profile, anchored VWAP, and MA confluence used by the zone
# scanner (core/volume_profile.py, core/anchored_vwap.py, core/zone_scan.py).

# Composite volume-profile lookbacks (months). Two profiles are built in
# parallel per ticker; a level confirmed on both windows is stronger.
VP_LOOKBACKS_MONTHS = (6, 12)

# Price-bucket width as a fraction of the window's reference price (0.5%).
# This is the histogram row size — finer buckets sharpen POC but add noise.
VP_BUCKET_PCT = 0.005

# Fraction of total volume contained in the value area around the POC.
# VAH/VAL are the upper/lower bounds of this band (institutional standard 70%).
VP_VALUE_AREA_PCT = 0.70

# Pivot swing-detection window (bars each side) for anchored-VWAP anchor points.
# A bar is a swing high/low if it exceeds all PIVOT_WINDOW bars on both sides.
PIVOT_WINDOW = 10

# Confluence band for the zone scanner: current price must sit within this
# fraction of a structural level (VAL/VAH/POC, AVWAP, 50/200 DMA) for it to
# count toward a zone. Reconciled to ATR units internally for display.
ZONE_CONFLUENCE_PCT = 0.025

# Minimum number of distinct structural signals converging at the current price
# for the scanner to flag an entry zone (the brief's "2 or more align").
ZONE_MIN_CONFLUENCE = 2

# Momentum-regime stop tiering. When price runs more than MOMENTUM_VAL_PREMIUM_PCT
# above the 6-month VAL, the 6mo support is too far for a momentum-flag entry
# (a 20%+ stop). The scanner switches to a micro-structure stop built from the
# last MICRO_LOOKBACK_DAYS bars: the micro volume-profile VAL and an AVWAP
# anchored to the most recent swing low in that window. The stop sits
# MICRO_STOP_BUFFER_ATR daily-ATRs below the nearest micro support — a clean
# break of it means the parabolic move is done. Tagged ZONE-MOMO in output.
MOMENTUM_VAL_PREMIUM_PCT = 0.10
MICRO_LOOKBACK_DAYS = 14
MICRO_STOP_BUFFER_ATR = 0.25

# Momentum stop-tier v2 micro-anchors. Beyond the micro VAL and swing-low AVWAP,
# two more anchors are considered in the momentum window, and the tightest
# qualifying one below price wins (stop still set MICRO_STOP_BUFFER_ATR below it):
#  - Breakout gap: the most recent up-gap (today's low above yesterday's high)
#    leaves an unfilled shelf. Its floor (the pre-gap high) is where a clean fill
#    breaks momentum. Only gaps >= GAP_MIN_ATR daily-ATRs count (filters trivial
#    gaps); the floor (not the gap top) is used so a partial fill doesn't shake out.
#  - High-volume node: the nearest heavy volume shelf below price in the micro
#    profile — a local histogram peak clearing HVN_MIN_PROMINENCE of the tallest
#    bucket. Tighter and more precise than the VAL edge when volume has stacked.
GAP_MIN_ATR = 0.5
HVN_MIN_PROMINENCE = 0.5
