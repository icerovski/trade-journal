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
