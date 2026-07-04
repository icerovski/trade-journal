"""Exit shapes (Entry & Stop System §5a) — extends the exit ladder, never replaces it.

Two per-trade exit shapes, selected at entry alongside the stop:

  1. HARD target — a TECHNICAL setup with a defined objective: bank the full target,
                   no runner. (Only the TP-stage action changes.)
  2. THESIS exit — no guessed-at-entry price target; exit on thesis/stop only.

The default (unset) is **today's** regime-aware M1/M2/TP ladder — scale out at the
objective, let a runner ride behind the trailing stop — so a position with no shape
set behaves as it always has. RUNNER survives only as a compatibility alias of that
default (assessment cut, 2026-07-04: it was behaviourally identical to the ladder,
so it is no longer presented as a distinct shape; stored `RUNNER` values and the
`X:R` token normalize to the default ladder, chip and all). Only two behavioural
hooks exist, both opt-in:
  * `suppresses_price_target` (THESIS)  → calculate_position_risk drops the TP target;
  * `is_hard_target` (HARD)             → the TP-stage directive becomes a full exit.

There is deliberately **no time stop**: no shape forces an exit on elapsed time. A trade
ends on its price stop or a broken thesis — never a clock (§5a).
"""

SHAPE_LADDER = "LADDER"        # default: today's regime-aware M1/M2/TP ladder
SHAPE_HARD_TARGET = "HARD"     # TECHNICAL: exit fully at the target
SHAPE_SCALE_RUNNER = "RUNNER"  # legacy alias of the default ladder (kept for stored values)
SHAPE_THESIS = "THESIS"        # no price target; exit on stop/thesis only

VALID_SHAPES = (SHAPE_LADDER, SHAPE_HARD_TARGET, SHAPE_SCALE_RUNNER, SHAPE_THESIS)

# Command/token aliases → canonical shape. Empty/None/unknown → default ladder.
# RUNNER *is* the default ladder: stored legacy values and the X:R token normalize
# to LADDER so no consumer (chips, labels, branches) treats it as a third shape.
_ALIASES = {
    "": SHAPE_LADDER,
    "L": SHAPE_LADDER, "LADDER": SHAPE_LADDER, "DEFAULT": SHAPE_LADDER,
    "H": SHAPE_HARD_TARGET, "HARD": SHAPE_HARD_TARGET, "HARD_TARGET": SHAPE_HARD_TARGET, "TARGET": SHAPE_HARD_TARGET,
    "R": SHAPE_LADDER, "RUNNER": SHAPE_LADDER, "SCALE": SHAPE_LADDER,
    "T": SHAPE_THESIS, "TH": SHAPE_THESIS, "THESIS": SHAPE_THESIS,
}


def normalize_shape(shape) -> str:
    """Map any token/alias to a canonical shape. Unset/unknown → SHAPE_LADDER (default)."""
    if shape is None:
        return SHAPE_LADDER
    return _ALIASES.get(str(shape).strip().upper(), SHAPE_LADDER)


def suppresses_price_target(shape) -> bool:
    """THESIS trades carry no guessed-at-entry price target (§5a)."""
    return normalize_shape(shape) == SHAPE_THESIS


def is_hard_target(shape) -> bool:
    """HARD-target trades exit fully at the objective — no runner past the target."""
    return normalize_shape(shape) == SHAPE_HARD_TARGET


def shape_label(shape) -> str:
    """Short human label for display. (RUNNER normalizes to the ladder, so it can
    never reach a label of its own.)"""
    return {
        SHAPE_LADDER: "Ladder",
        SHAPE_HARD_TARGET: "Hard target",
        SHAPE_THESIS: "Thesis exit",
    }[normalize_shape(shape)]
