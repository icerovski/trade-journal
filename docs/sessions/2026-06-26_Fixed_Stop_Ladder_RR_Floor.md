# Session — 2026-06-26 — FIXED-Stop Milestone Ladder & RR Floor

## Objectives

Investigate why **UDOW** showed a "raise stop to entry" directive at only ~2% unrealized profit. Determine whether it was a calculation bug or a logic flaw, then fix the root cause across all affected positions.

## Technical Changes

- **`ui/risk_workspace.py`**
  - FIXED-stop commit path (~`risk_workspace.py:1373`): `inception_atr` is now snapped to the discovery-timeframe ATR (daily/weekly/monthly/quarterly) nearest the risk distance `entry − stop`, instead of the hardcoded `14d` (daily) ATR. TRAILING is unchanged (it already carries its supplied distance).
  - `_exit_recommendation()`: removed the sub-1.0 RR **efficiency floor** branch (FIXED M2/TP forced-exit / restore-stop). M2/TP now follow the `TRIM_MATRIX` uniformly for both stop types. `rr`/`cur_p`/`stop_type` retained in the signature for call-site stability.
  - `_exit_guidance_str()`: removed the now-unreachable EXIT prose branch and the floor-reference comment.
- **`tools/migrate_fixed_inception_atr.py`** (new): one-off migration. Dry-run by default; `--apply` writes. Re-stamps `inception_atr` for every ACTIVE FIXED profile using the same `get_atr_discovery_data` rows the UI produces (parity with the commit-path fix). Direct `UPDATE` because `set_position_risk` only fills `inception_atr` when NULL.
- **`tests/test_exit_recommendation.py`**, **`tests/test_profit_taking.py`**: the three floor-behaviour tests replaced with new-design tests (RR is informational; directive follows the matrix; FIXED and TRAILING behave identically at low RR).
- **`docs/TECHNICAL_DOCS.md`** §5: documented per-stop-type inception-ATR sourcing and the RR-floor removal.
- **`CLAUDE.md`**: RR Efficiency marked informational-only; FIXED snap rule noted under Exit Milestones.

## Logic & Decisions

- **Root cause.** For a FIXED stop the user supplies a stop *price*, not an ATR distance, so the milestone ladder had no natural R unit and the code defaulted to the *daily* ATR. On a deliberately deep stop this mis-scales the ladder: UDOW's daily ATR (1.86) against a 21.5-point stop put M1 = entry+1.86, tripping "go risk-free" at a +2.8% gain. Not a calc error — a wrong-timeframe R.
- **Why snap to `entry − stop` rather than use it raw.** Using the raw distance (21.5) pushes milestones so far out the profit ladder goes dormant (M1≈88). Snapping to the nearest discovery ATR keeps milestones at a reachable, volatility-grounded horizon (UDOW → quarterly ≈ 12.3, M1≈79). For the entire current FIXED book every stop distance exceeds the quarterly ATR, so all but UGL snapped to quarterly (UGL → monthly, its cached quarterly series came out smaller). The rule stays general: a tight FIXED stop would snap to a shorter timeframe.
- **For FIXED, `inception_atr` drives only the upside.** The stop itself is the stored price (`atr_value`); `calculate_position_risk` does not derive the FIXED stop from `inception_atr`. So re-stamping the R unit moves M1/M2/TP only — the deep stop is untouched. This is what makes the "deep downside / volatility-based upside ladder" split valid.
- **RR floor removal.** RR `(TP − price)/(price − stop)` runs structurally low on a deep stop because the `price − stop` denominator is large — the floor fired on stop geometry, not on a real loss of edge. Confirmed the artifact is self-correcting: raising the stop as price advances lifts RR back above 1.0 (at M2 with the stop laddered to M1, RR = 1.00 exactly). Exits are now driven by the stop (a breach is the exit) and the RANGING regime (M2 50% / TP 100% via the matrix). RR remains displayed in the PLAN panel as a "what am I paid to hold from here" read.
- **Migration provenance.** Computed via `get_atr_discovery_data` (same PriceService conid cache as the UI), so stored values equal what a fresh re-commit would write. Entry prices taken from the audited reset-on-zero ledger via `get_dashboard_df`, not re-derived.

## Verification

- `uv run python -m pytest tests/ -q` → **166 passed**.
- Migration dry-run reviewed before applying; DB backed up to `trade_journal.backup_20260626_205655.db`.
- `--apply` updated **9** ACTIVE FIXED profiles. Key: UDOW `inception_atr` 1.86 → 12.26; TQQQ 3.10 → 15.60; UGL 2.38 → 10.66.
- Post-migration check: UDOW M1 = 78.76, M2 = 91.02, TP = 103.28 at price 68.71 → stage **PRE-M1**. The premature stop-raise is gone.
- `db.py` / `models.py` carried pre-existing (pre-session) modifications and were **excluded** from this session's commit.

## Next Steps

- Confirm TQQQ / UGL / FOUR PRA panels read sensibly in the live UI (stage + ladder) at next run.
- Decide whether the laddering-stop guidance (M1→entry, M2→M1, TP→M2) should be surfaced explicitly in the PLAN panel rather than left as a manual convention.
- Resolve the pre-existing uncommitted `db.py` / `models.py` changes (origin/intent unknown this session).
