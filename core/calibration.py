"""Horizon calibration profiles (Horizon_Calibration_3to6mo.md).

A calibration profile is the *lens* the entry engine looks through — the timeframe,
the volatility window, the micro-structure behaviour, and the %-of-price bands. It
does NOT change the trade rules and, per the doc's "two roles of time", it adds **no
time stop**: it only changes what you look at, never a clock that forces you out.

Two profiles ship:

  * DEFAULT_CALIBRATION  — today's short-swing lens. Its knob values equal the daily
    constants the scanner already uses, so passing it is behaviourally identical to
    passing nothing (proven by test). This is the default.
  * POSITION_3TO6MO      — the 3-to-6-month position lens: a longer ATR window, wider
    buffers (3–7% of price) and stop-width band (10–18%), a 30-week-MA anchor, and the
    MOMENTUM override — a momentum flag means "extended, wait for a weekly pullback",
    NOT a tight micro-stop. So its `use_micro_momentum_stop` is False: on a MOMENTUM
    flag the scanner falls back to the weekly value anchors instead of the 14-bar
    micro structure.

Selection is book-level (a `calibration_profile` setting), resolved via `get_calibration`.
"""

from dataclasses import dataclass

from constants import (
    SCANNER_ATR_WINDOW,
    VP_LOOKBACKS_MONTHS,
    MOMENTUM_VAL_PREMIUM_PCT,
    MICRO_LOOKBACK_DAYS,
    MICRO_STOP_BUFFER_ATR,
    ZONE_CONFLUENCE_PCT,
    GATE_G1_MAX_STOP_PCT,
    GATE_G5_MAX_EXTENSION_ATR,
    CAL_3TO6MO_ATR_WINDOW,
    CAL_3TO6MO_MICRO_BUFFER_ATR,
    CAL_3TO6MO_CONFLUENCE_PCT,
    CAL_3TO6MO_STOP_BUFFER_PCT_BAND,
    CAL_3TO6MO_STOP_WIDTH_PCT_BAND,
    CAL_3TO6MO_EXTENSION_ATR_MAX,
)


@dataclass(frozen=True)
class CalibrationProfile:
    """A horizon lens. Scanner knobs are wired into core/zone_scan.scan_ticker; the
    %-of-price bands and anchor are advisory metadata surfaced to the user / gates."""

    name: str
    timeframe: str                 # "daily" | "weekly" — the structural coordinate system
    ma_anchor: str                 # trend rail(s) to anchor/trail from

    # --- Scanner knobs (wired) ---
    atr_window: int                # ATR lookback in daily bars (longer = longer-horizon vol)
    lookbacks: tuple               # volume-profile lookbacks, in months
    momentum_premium: float        # % over VAL_6mo that flags MOMENTUM
    use_micro_momentum_stop: bool  # False → MOMENTUM override: use weekly anchors, not a micro stop
    micro_days: int                # micro-structure window (bars)
    micro_buffer_atr: float        # ATR buffer beneath the chosen anchor
    confluence_pct: float          # in-zone band as a fraction of price

    # --- Advisory bands / gate overrides (metadata) ---
    stop_buffer_pct_band: tuple    # (lo, hi) buffer beneath anchor, % of price
    stop_width_pct_band: tuple     # (lo, hi) total entry→stop width, % of price
    extension_atr_max: float       # G5 extension cap, in ATRs above the trail anchor


# Today's short-swing lens. Values MIRROR the daily constants the scanner already
# defaults to, so DEFAULT_CALIBRATION is behaviourally a no-op (see tests).
DEFAULT_CALIBRATION = CalibrationProfile(
    name="default",
    timeframe="daily",
    ma_anchor="50/200 DMA",
    atr_window=SCANNER_ATR_WINDOW,
    lookbacks=VP_LOOKBACKS_MONTHS,
    momentum_premium=MOMENTUM_VAL_PREMIUM_PCT,
    use_micro_momentum_stop=True,
    micro_days=MICRO_LOOKBACK_DAYS,
    micro_buffer_atr=MICRO_STOP_BUFFER_ATR,
    confluence_pct=ZONE_CONFLUENCE_PCT,
    stop_buffer_pct_band=(0.0, GATE_G1_MAX_STOP_PCT),   # up to the G1 8% width cap
    stop_width_pct_band=(0.0, GATE_G1_MAX_STOP_PCT),
    extension_atr_max=GATE_G5_MAX_EXTENSION_ATR,
)

# The 3-to-6-month position lens (the calibration doc).
POSITION_3TO6MO = CalibrationProfile(
    name="position_3to6mo",
    timeframe="weekly",
    ma_anchor="30-week MA",
    atr_window=CAL_3TO6MO_ATR_WINDOW,
    lookbacks=VP_LOOKBACKS_MONTHS,           # 6/12-month value ranges are the weekly anchors
    momentum_premium=MOMENTUM_VAL_PREMIUM_PCT,
    use_micro_momentum_stop=False,           # MOMENTUM = "extended, wait for a weekly pullback"
    micro_days=MICRO_LOOKBACK_DAYS,
    micro_buffer_atr=CAL_3TO6MO_MICRO_BUFFER_ATR,
    confluence_pct=CAL_3TO6MO_CONFLUENCE_PCT,
    stop_buffer_pct_band=CAL_3TO6MO_STOP_BUFFER_PCT_BAND,
    stop_width_pct_band=CAL_3TO6MO_STOP_WIDTH_PCT_BAND,
    extension_atr_max=CAL_3TO6MO_EXTENSION_ATR_MAX,
)

CALIBRATIONS = {
    DEFAULT_CALIBRATION.name: DEFAULT_CALIBRATION,
    POSITION_3TO6MO.name: POSITION_3TO6MO,
}


def get_calibration(name) -> CalibrationProfile:
    """Resolve a profile name to its CalibrationProfile. Unknown/empty → the default."""
    if not name:
        return DEFAULT_CALIBRATION
    return CALIBRATIONS.get(str(name).strip().lower(), DEFAULT_CALIBRATION)
