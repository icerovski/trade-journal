"""Exit shapes (Entry & Stop System §5a) — extends the exit ladder, never replaces it.

Three per-trade exit shapes, selected at entry alongside the stop:

  1. HARD target   — a TECHNICAL setup with a defined objective: bank the full target,
                     no runner. (Only the TP-stage action changes.)
  2. SCALE + RUNNER — take partial profit at the objective, let a runner ride behind the
                     trailing stop. This is exactly today's regime-aware ladder.
  3. THESIS exit    — no guessed-at-entry price target; exit on thesis/stop only.

The default (unset) reproduces **today's** behaviour exactly — the regime-aware
M1/M2/TP ladder — so a position with no shape set behaves as it always has. Only two
behavioural hooks exist, both opt-in:
  * `suppresses_price_target` (THESIS)  → calculate_position_risk drops the TP target;
  * `is_hard_target` (HARD)             → the TP-stage directive becomes a full exit.

There is deliberately **no time stop**: no shape forces an exit on elapsed time. A trade
ends on its price stop or a broken thesis — never a clock (§5a).
"""

SHAPE_LADDER = "LADDER"        # default: today's regime-aware M1/M2/TP ladder
SHAPE_HARD_TARGET = "HARD"     # TECHNICAL: exit fully at the target
SHAPE_SCALE_RUNNER = "RUNNER"  # scale out at objective, trail the runner (== default behaviour)
SHAPE_THESIS = "THESIS"        # no price target; exit on stop/thesis only

VALID_SHAPES = (SHAPE_LADDER, SHAPE_HARD_TARGET, SHAPE_SCALE_RUNNER, SHAPE_THESIS)

# Command/token aliases → canonical shape. Empty/None/unknown → default ladder.
_ALIASES = {
    "": SHAPE_LADDER,
    "L": SHAPE_LADDER, "LADDER": SHAPE_LADDER, "DEFAULT": SHAPE_LADDER,
    "H": SHAPE_HARD_TARGET, "HARD": SHAPE_HARD_TARGET, "HARD_TARGET": SHAPE_HARD_TARGET, "TARGET": SHAPE_HARD_TARGET,
    "R": SHAPE_SCALE_RUNNER, "RUNNER": SHAPE_SCALE_RUNNER, "SCALE": SHAPE_SCALE_RUNNER,
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
    """Short human label for display."""
    return {
        SHAPE_LADDER: "Ladder",
        SHAPE_HARD_TARGET: "Hard target",
        SHAPE_SCALE_RUNNER: "Scale+runner",
        SHAPE_THESIS: "Thesis exit",
    }[normalize_shape(shape)]
