# Application Assessment & Integrity Fixes

**Date:** 2026-08-04
**Branch:** `feature/entry-stop-system`
**Commits:** `9d45e90` (fixes), `71f13d4` (merge with the parallel regime-lens branch)

## Objectives

1. A whole-application assessment — complexity, architecture, functionality, quantitative theory — broader than the 2026-07-04 Entry & Stop System audit, which was scoped to that build.
2. Fix the findings that make a live number wrong or can corrupt stored state, in priority order.

## Technical Changes

### 1. `C:TH` classification was crashing (shipped broken since `df47db0`)

`ui/risk_workspace.py` — the §0a coupling block read `active_shape` at line 1350 and the variable was bound at 1367. Short-circuit evaluation meant `C:TE` was fine and **`C:TH` always raised `UnboundLocalError`**, swallowed by `except Exception` into a bare `logger.error`. No draft, no notification, table still showing the previous model. Moved the block below the `X:` parse — the only position where `active_shape is None` truthfully means "no `X:` typed this edit".

*The remote branch fixed the same defect independently in `45d8376`; the merge kept one copy plus this branch's test coverage.*

### 2. Prospect promotion dropped decision metadata

`db.promote_prospect_to_active` inserted 12 of 17 columns, silently discarding `profile`, `tp_atr_mult`, `classification`, `exit_shape` and `ccy` the moment a watch-list idea was filled — with no user action to associate the loss with, since promotion runs inside `get_dashboard_df`'s consolidation step on every render. Carried columns are now a named `_PROMOTED_COLUMNS` constant. Added an `idx_active_conid` guard: an existing ACTIVE profile wins untouched and the redundant WATCH row is retired, instead of raising `IntegrityError` up through the dashboard. `highest_sl` is deliberately excluded — the ratchet belongs to the lot.

### 3. Schema versioning — `schema_migrations`

`init_db` had six statements that **mutate user rows** re-executing on every startup with no version tracking. Moved into `db._ONE_SHOT_MIGRATIONS`, each run once and recorded. Adding an entry to that tuple is now the migration mechanism.

### 4. Silent failures surfaced

`on_strategy_change` and `_log_classification` now notify the user, not just the log. Deduped per distinct fault (`Input.Changed` fires per keystroke), cleared on a successful parse, on empty input and on row change.

### 5. Portfolio heat no longer nets

`core/sizing.compute_portfolio_risk` — `total_r_pct` sums positive `risk_pct_nav` only; `headroom` and `pct_budget_used` follow it. `total_r_pct_net` and `n_locked_in` added for display. `total_stop_out` stays net. Same floor applied to the G7 heat proxy in `_gate_check`.

### 6. Price adjustment basis pinned

`services/price_service.py` — the forward update now starts `PRICE_BASIS_OVERLAP_DAYS` (7) *before* the last cached bar; `basis_shifted()` compares those settled bars against the cache and `rebuild_series()` re-downloads and REPLACEs the series when they disagree beyond 0.1%. Extracted `_normalize()` so `save_prices` and the check cannot shape dates differently. Maintenance option **5** forces a rebuild for pre-existing seams.

### 7. Expectancy verdicts gated on sample size

`EXPECTANCY_MIN_SAMPLE = 20`. `above_threshold` now requires the sample as well as the E[R]; new `is_provisional` / `n_min_sample` fields drive a third display state.

### 8. Cleanups

Deleted `main.print_watch_list_summary` (dead, and subscripted a dataclass — would have raised if ever called); removed import-time `log_system_milestone` calls in `data_loader.py` and `services/ibkr.py`; removed an unused import in `portfolio_manager.get_open_positions_hybrid`; corrected the "SMA-seeded" ATR claim and the `_micro_support` swing-low comment; fixed a stale `core/portfolio_analytics.py` reference in TECHNICAL_DOCS §5.

## Logic & Decisions

**Why the FIXED-stop migration was the dangerous one.** `UPDATE risk_profiles SET atr_value = inception_stop … WHERE atr_value < inception_stop * 0.5` was a *historical* guard — "this looks like an ATR distance, not a price" — re-evaluated on every startup, forever. A leveraged name that halves and is legitimately re-stopped at, say, 60 against a 400 inception stop matches it. The migration would restore the old stop **and** ratchet `highest_sl` up to match, fabricating a breach on a position just re-stopped. This is the general argument for versioning: a guard that is safe against 2026 data is not an invariant.

**Why heat must not net.** `risk_pct_nav = (entry − stop) × qty / NAV` goes negative once a stop ratchets above entry — right for "what does a stop-out pay me", wrong for "how much NAV is still at risk". On a book of three 1%-risk positions plus one winner stopped 3% above entry, the old sum reported 0.40% heat and 3.60% headroom against a true 2.70% / 1.30%. The same figure feeds G7, so the error both mis-reported the book and would wave through the next entry.

**Why detect-and-heal for the price basis, not a periodic re-download or `auto_adjust=False`.** A cadence is expensive and mistimed; raw prices trade a silent seam for a real discontinuity at every split. Overlapping settled bars fires exactly when a re-basing happened and costs nothing otherwise. Empirically the live cache is currently **clean** — cached closes match a fresh adjusted pull to within 0.07% across 2,511 days for BXMT (high-yield REIT), BMW.DE (large annual dividend) and AVGO (10:1 split in 2024), because all 43 conids were seeded in one bulk fetch after those events. The defect was latent, not active; it would have fired on the next corporate action in a held name.

**Why a sample gate on expectancy.** The formula is exact; a small sample is not. At n = 1 a single +3R winner reads `E[R] = +3.00R` and promotes an archetype to full size — the metric manufacturing the over-sizing the journal exists to prevent. E[R] is still reported at any n so it can be watched accumulating; only the verdict waits. At a few trades a month, 20 is roughly a year per archetype, which is the honest cost of an evidence-based rule.

**Assessment findings deliberately not actioned** (structural, each a session): extract the modeling engine and command DSL out of `ui/risk_workspace.py`; push DB writes out of read paths; cover the ingestion boundary. See Next Steps.

## Verification

- **Full suite: 370 passed** (298 at session start; +44 this branch, +28 from the merge).
- `tests/snapshots/phase0_golden.json` **byte-identical** throughout, including across the merge — the tripwire confirming two parallel feature branches did not move a legacy number between them.
- Every new test was **run against the pre-fix code and confirmed to fail**: 4/6 classification (with the exact `UnboundLocalError`), 7/10 migration+promotion, 4/11 portfolio-heat, 3/4 notification. The remainder are controls that pass either way.
- Upgrade dry-run on a **copy** of the production database (live file untouched): two consecutive `init_db()` calls left all six table counts unchanged and recorded exactly 6 migration rows.
- Split self-heal simulated end to end: a 10:1 re-basing is detected (90% disagreement), the series rebuilds, and the result has a max day-over-day ratio of 1.0 — no seam.
- Merge verified beyond the test suite: no conflict markers repo-wide, `active_shape` binding order correct, `SRC:`/`THM:` plumbed through to the `trade_log` write, and this branch's error reporting and heat clamp intact.

**Observation, not a change:** the `trade_journal.db` at the configured `DATA_PATH` holds 488 trades and 68 `ticker_info` rows but **0 `risk_profiles`, 0 `trade_log`, and `gates_mode='off'`** — so the advisory-gates flip recorded in `OPEN_ITEMS.md` is not present in the data. Worth confirming that is the intended hub before reading any report from it.

## Next Steps

1. **Extract the modeling engine and command DSL out of `ui/risk_workspace.py`** — `refresh_risk_checklist` (336 lines, 139 branches, 9 optional `hypo_*` args) and `on_strategy_change` (258 lines, 81 branches) are the top two complexity scores in the repo and the highest-churn file, with no headless entry point. Tests already reach into six private helpers to get at them. Every defect found this session sat in an untested function. **Coordinate before starting — this branch has a second writer and this is the file that conflicts.**
2. **Push DB writes out of read paths** — `calculate_position_risk` writes the ratchet inside the enrichment loop; `_consolidate_positions` promotes prospects; `get_broker_verified_snapshot` writes the asset master. Return values, let one caller persist.
3. **Cover the ingestion boundary** — `ticker_mapper.resolve_yf_ticker` (36 branches, zero tests) and `data_loader.get_broker_verified_snapshot` against a fixture CSV. This is where wrong data enters a system whose entire value is being right about the numbers.
4. Optional: `db.py` opens 33 connections against one `try/finally`; an exception mid-function leaks the handle.
