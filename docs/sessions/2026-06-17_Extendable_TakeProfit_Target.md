# Session — 2026-06-17 · Extendable Take-Profit Target

## Objectives

A winning position (VOO, +31%) that runs past its default +3R target maxes out the exit
ladder: the panel sits permanently at "TP / trim 20%" with no forward milestone, and RR
reads negative because price is above the frozen TP. The session goal was to give the user
**optionality to extend the take-profit target as a position grows** — without re-inception
(which would discard the original cost basis and unrealized P/L) and without the target
drifting away on every tick. Plus a guardrail to control that an extended target still pays
at least 3:1 reward:risk.

## Technical Changes

- **`constants.py`** — added `RR_SETUP_FLOOR = 3.0`; documented `TP_ATR_MULTIPLE` as the
  *default* multiple now that a per-position override exists.
- **`db.py`** — `risk_profiles.tp_atr_mult` column (additive migration, `db.py:88`).
  `set_position_risk` gains a `tp_atr_mult` parameter with a `_KEEP` sentinel
  (`db.py:185`): a number sets it, `None` clears it (→ default 3R), and an omitted arg
  leaves it untouched. Unlike the write-once inception fields, this is **write-many**.
- **`models.py`** — `RiskProfile.tp_atr_mult`; `Position.tp_atr_mult` (effective multiple)
  and `Position.tp_is_override` (bool) for display.
- **`core/stop_loss.py`** (`calculate_position_risk`) — reads `profile.tp_atr_mult`; TP =
  `entry + tp_mult × inception_atr` where `tp_mult` is the override or `TP_ATR_MULTIPLE`.
  Sets the two new Position fields. `rr_ratio` therefore recomputes against the chosen TP.
- **`core/profit_taking.py`** (`compute_exit_milestones`) — monotonicity guard: logs a
  warning when an override lands at/below M2 (< 2R, a non-monotonic ladder). M1/M2 stay at
  1R/2R regardless of the override.
- **`ui/risk_workspace.py`** — `resolve_tp_mult()` (module helper) parses the four input
  forms into an inception-ATR multiple; `TP:` token parsed in `on_strategy_change` **before**
  the `+N/-N` quantity regex (so `TP:+35%` isn't read as a quantity); draft + both commit
  paths thread `tp_atr_mult`; `refresh_risk_checklist` gains `hypo_tp_mult` and renders a
  **TARGET** line with the forward RR flagged against `RR_SETUP_FLOOR`. Placeholder updated.
- **`services/ui_components.py`** — F1 → Strategy Lab: new "TAKE-PROFIT TARGET (TP:n)"
  section, syntax line, and combined examples.
- **`docs/TECHNICAL_DOCS.md` §5** and **`CLAUDE.md`** — documented the override and command.
- **Tests** — `tests/test_profit_taking.py` (+5: extend, default, RR recompute, stage shift),
  `tests/test_tp_override.py` (+9: all resolver input forms and unresolvable cases).

## Logic & Decisions

- **Frozen anchor, not live ATR.** The override is a multiple of the **inception** ATR, not
  the live `atr_value`. This was a deliberate reversal of the user's first instinct (live
  ATR): coupling the target to the live stop ATR meant tightening the stop *cratered* the
  target (VOO: `TP:+35%` at ATR 85 → target $711, then a weekly-ATR stop of 18 → target
  collapses to ~$566, below market). Anchoring to the frozen inception ATR keeps the target
  stable and reachable; editing the stop never moves it. M1/M2 already use inception ATR, so
  the ladder stays internally consistent.
- **TP-only, stop independent.** The control sets the target; the trailing stop keeps
  ratcheting on its own ATR. Re-inception was explicitly rejected (it discards unrealized
  P/L and the cost basis).
- **Forward RR, not entry RR.** The 3:1 guardrail uses `(target − price)/(price − stop)` —
  reward:risk *remaining from here* — not the entry-setup ratio. Once a winner's trailing
  stop sits above entry there is no risk from entry (profit is locked), so the entry-anchored
  3:1 is meaningless; the forward ratio is the honest "what am I paid to keep holding"
  measure and is *expected* to read low near a target. The displayed RR (`rr_ratio`) and its
  color bands / FIXED-stop sub-1.0 exit floor all key off `tp_price`, so they recompute
  correctly against an overridden target with no extra wiring.
- **`_KEEP` sentinel.** `set_position_risk` is called from paths that don't manage the TP
  override (e.g. `tools/reconstruct_inception_risk.py`). The sentinel prevents those callers
  from silently wiping an override, while still allowing an explicit `None` to clear it.
- **Input unit bridge.** `%`/`$` inputs are a friendly façade over the R-multiple: they are
  converted to a multiple via the inception ATR once, at set-time. `$` targets require a
  share count and are rejected otherwise.

## Verification

- **Full suite: 110 passed** (`uv run python -m pytest tests/ -q`), incl. 14 new tests.
- Schema migration applied via `init_db()`; `risk_profiles.tp_atr_mult` present;
  `get_all_risk_settings()` loads `RiskProfile` cleanly.
- `set_position_risk` round-trip on a scratch conid: create (4.0) → preserve-on-omit (4.0)
  → explicit `None` clears → row deleted. Sentinel semantics confirmed.
- Live pipeline smoke: VOO (no override) → `tp_price = 669.11`, `tp_atr_mult = 3.00`,
  `tp_is_override = False` — exactly `entry + 3 × inception_atr`. No regression to the
  default path.

## Next Steps

- **VOO stop still wide.** `atr_value = 85` (stop ~$614, ~12% buffer). User paused the
  weekly-ATR (18.13) change. One workspace command now does both: `18.13 T TP:5R` (tighten
  trailing stop to weekly **and** set a 5R target = $763.98).
- Consider surfacing the override multiple in the main grid (currently only in the audit
  panel TARGET line and the M1/M2/TP ladder after reload).
- During modeling, the M1/M2/TP ladder line still shows the saved `tp_price`; only the
  TARGET line previews the modeled override until commit + reload. Acceptable, but could be
  unified if it causes confusion.
