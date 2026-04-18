# Numeric thresholds used across multiple modules.
# Centralised here so changes propagate everywhere and the intent is explicit.

# Minimum quantity treated as non-zero throughout the ledger.
# Prevents floating-point dust from keeping ghost positions alive.
QTY_ZERO_THRESHOLD = 0.0001

# Minimum annualised age used as the AAGR denominator.
# Floors positions younger than ~2 weeks to avoid extreme AAGR readings.
AAGR_MIN_YEARS = 0.04

# ATR-distance thresholds for the confluence engine.
# A level within CONFLUENCE_ATR_THRESHOLD of price/stop is "in the zone".
# Within CONFLUENCE_FORTRESS_THRESHOLD it is a "fortress" level.
CONFLUENCE_ATR_THRESHOLD = 0.25
CONFLUENCE_FORTRESS_THRESHOLD = 0.10

# Status-colour multipliers for the dual-constraint audit.
# RED fires when actual exceeds the custom limit by these factors.
RISK_RED_MULTIPLIER = 1.5
EXPOSURE_RED_MULTIPLIER = 1.1

# Take-profit is placed this many ATRs above the stop loss.
TP_ATR_MULTIPLE = 3
