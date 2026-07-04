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

# Independence check (Entry & Stop System §4a, minimum viable form): entry signals
# whose level values sit within this many ATRs of EACH OTHER are one signal counted
# twice (e.g. VAL and POC landing on the same volume-profile bucket), not two
# independent walls. Only the flag decision dedups; the signal list stays complete.
ZONE_DEDUP_EPS_ATR = 0.05

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

# --- Scanner structural windows ---------------------------------------------
# Phase 1 extraction: these were hardcoded literals inside core/zone_scan.py.
# Values are unchanged from the originals — this only centralises them so the
# Entry/Stop-system work can tune them later without editing code paths.

# Moving-average lookbacks (in daily bars) the scanner adds to its level map.
DMA_LONG_WINDOW = 200
DMA_SHORT_WINDOW = 50

# Trading-days-per-month approximation used by _slice_months ONLY when the
# frame has no 'date' column (the date path is exact and preferred).
TRADING_DAYS_PER_MONTH = 21

# Default ATR lookback (daily bars) for the scanner's volatility yardstick.
SCANNER_ATR_WINDOW = 14

# When no structural support sits below price, the scanner falls back to a stop
# this many ATRs beneath price (labelled "ATR(1)") so the zone can still size.
ATR_FALLBACK_MULT = 1.0

# --- Regime day-count thresholds (200-DMA) ----------------------------------
# Phase 1 extraction from core/profit_taking.classify_regime. TREND needs the
# DMA rising this many consecutive days (with price above it); NORMAL needs at
# least the lower floor. Values unchanged.
REGIME_TREND_MIN_DAYS = 21
REGIME_NORMAL_MIN_DAYS = 10

# --- Exit milestone R-multiples ---------------------------------------------
# Phase 1 extraction from core/profit_taking.compute_exit_milestones. The ladder
# is entry + Mn × R (R = inception ATR): M1 at 1R, M2 at 2R; TP uses
# TP_ATR_MULTIPLE (default 3R) above. Values unchanged.
MILESTONE_M1_MULT = 1.0
MILESTONE_M2_MULT = 2.0

# --- ATR discovery timeframes -----------------------------------------------
# Phase 1 extraction from core/stop_loss._compute_atr_rows. Institutional ATR
# standards: (label, window, resample-timeframe). Values unchanged.
ATR_DISCOVERY_INTERVALS = (
    ("14d", 14, "daily"),
    ("12w", 12, "weekly"),
    ("12m", 12, "monthly"),
    ("12q", 12, "quarterly"),
)

# --- Entry gates (Entry & Stop System §4) -----------------------------------
# Advisory-first hard-gate thresholds. Defaults are the doc's starting points,
# meant to be tuned from the trade log (§7/§8) — not laws. Consumed by
# core/gates.py; a gate with missing inputs returns NA (never blocks).

# G1 Stop-width: R₁ ≤ MAX_STOP_ATR × ATR  AND  R₁/entry ≤ MAX_STOP_PCT.
GATE_G1_MAX_STOP_ATR = 1.5
GATE_G1_MAX_STOP_PCT = 0.08
# G2 Basis quality: ≥ MIN_CONFLUENCE independent levels AND a non-thin stop_source.
GATE_G2_MIN_CONFLUENCE = 2
GATE_G2_THIN_SOURCES = ("ATR(1)",)             # too thin to count as basis (Scenario D)
GATE_G2_TIGHT_PREFIXES = ("VAL", "HVN", "AVWAP", "GAP", "DMA", "POC")
# G3 Fallback artifact: an unflagged MOMENTUM row with a double-digit VAL_* stop.
GATE_G3_MOMO_VAL_STOP_PCT = 0.10
# G4 Event: no new entry within this many days of earnings/known catalyst.
GATE_G4_EVENT_DAYS = 5
# G5 Extension: don't initiate if price is > this many ATRs above the trail anchor.
GATE_G5_MAX_EXTENSION_ATR = 2.0
# G6 Liquidity: cut — permanent NA stub in core/gates.py, no constants.
# G7 Portfolio-heat cap = this multiple of the single-trade R% cap.
# (The spec's theme dimension is cut until themes exist somewhere in the app.)
GATE_G7_HEAT_MULT = 3.0

# --- Expectancy (Entry & Stop System §5) ------------------------------------
# Minimum E[R] (in R units, after costs) for an archetype to be considered
# "proven" and worth trading at full size. Below this, trade starter size only.
EXPECTANCY_THRESHOLD_R = 0.20

# --- Horizon calibration (Horizon_Calibration_3to6mo.md) --------------------
# The default (short-swing) lens uses the daily constants above. The 3–6mo
# position lens retunes every horizon-sensitive knob (see core/calibration.py).
# %-of-price bands are the doc's targets (§1a/§3); the scanner works on daily
# bars, so its "long ATR" is approximated by a longer daily window (true weekly
# resampling is deferred — flagged). The profile changes the LENS only; it adds
# no time stop (the doc's "two roles of time").
CAL_3TO6MO_ATR_WINDOW = 60          # ≈12 weeks of daily bars — a longer-horizon vol read
CAL_3TO6MO_MICRO_BUFFER_ATR = 0.5   # 0.25–0.5 × (weekly) ATR beneath the anchor
CAL_3TO6MO_CONFLUENCE_PCT = 0.05    # wider band (~0.5 × weekly ATR) than the daily 0.025
CAL_3TO6MO_STOP_BUFFER_PCT_BAND = (0.03, 0.07)   # buffer beneath the anchor, % of price
CAL_3TO6MO_STOP_WIDTH_PCT_BAND = (0.10, 0.18)    # total entry→stop width, % of price
CAL_3TO6MO_EXTENSION_ATR_MAX = 2.0  # G5: not > 2 × (weekly) ATR above the 30-week MA
