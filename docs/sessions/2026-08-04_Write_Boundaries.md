# Write Boundaries — DB Writes Out of Read Paths

**Date:** 2026-08-04 (third session of the day)
**Branch:** `feature/entry-stop-system`
**Commits:** `d945493`, `7708680`
**Closes:** the last structural item from `2026-08-04_Application_Assessment_And_Integrity_Fixes.md`.

## Objectives

Three database writes sat inside functions that read like pure computation:

| Site | Write | Frequency |
|---|---|---|
| `calculate_position_risk` | the trailing ratchet | once per position, per refresh |
| `_consolidate_positions` | prospect promotion | once per position, per refresh |
| `get_broker_verified_snapshot` | the asset master | once per CSV row |

The ratchet is the one that matters: it is monotonic and persisted, so a write buried in a per-position render loop lets one bad price tick raise a stop permanently, with nothing in the call stack saying a read could do that.

## Technical Changes

### `calculate_position_risk` is pure

It no longer imports `db` at all. An advanced stop is reported as `Position.pending_ratchet` (`None` when the ratchet held). `PortfolioManager._enrich_metrics` collects them and commits once through the new `db.update_high_water_marks(pairs)` — `executemany` in a single transaction, keeping `MAX(highest_sl, ?)` in SQL so a stale or out-of-order batch still cannot lower a stop.

### Parsing is a transform

`get_broker_verified_snapshot` accumulates asset-master rows during the parse and calls the new `db.save_ticker_info_bulk(rows)` once at the end. `save_ticker_info` and the bulk form now share `_TICKER_INFO_UPSERT` and `_ticker_info_params`, so the single-row and batched paths cannot drift.

### Promotion is a step, not a side effect

`promote_prospect_to_active` moved out of the WAC merge loop into an explicit `_promote_bought_prospects()` call in `get_open_positions_hybrid`. Same trigger and same data; `_consolidate_positions` is now pure arithmetic over the list it is handed.

### Fallout

Three dead imports removed (`calculate_position_risk` from both UI modules, `audit_position_risk` from the watch list) — all exposed by the change.

## Logic & Decisions

**The safety net went in before the source moved.** The failure mode being guarded against is *purity without persistence*: making the calculation pure and losing the write. Nothing visible breaks — the panel still shows the ratcheted stop, because it was computed in memory. It would surface weeks later as a stop that reverted after a restart. So `test_write_boundaries.py` was written and run against the **unmodified** code first, proving the ratchet persisted end-to-end through `_enrich_metrics`, before `stop_loss.py` was touched.

**Purity is asserted structurally, not with a mock.** Two tests: one parses `core.stop_loss` with `ast` and asserts `db` is not among its imports; the other replaces `db.get_conn` with a raiser and calls the function, which catches any database access regardless of how a module happens to import things. A mock of one name would only prove that one name went unused.

**`Position.pending_ratchet` over a changed return signature.** `calculate_position_risk` returns the position and every caller discards it, so threading a second return value would have churned every call site to no benefit. One nullable field on the object the function already mutates is the smaller change and reads as what it is: "this needs persisting".

**The promotion trigger was deliberately left alone.** Moving it to sync-time is defensible — positions can only appear via ingest — but that is a behaviour change, and this was a refactor. It now runs at the same point, just visibly.

**The 17 monkeypatches are the finding, not the chore.** Four test files patched `stop_loss.update_high_water_mark` purely so that testing arithmetic would not write to a database. After the change they did not merely become unnecessary — they began *erroring*, because the name no longer exists. That is the coupling measured rather than asserted. All 17 removed, along with the `monkeypatch` fixture parameters they left behind.

## Verification

- **Full suite: 593 passed** (579 at the start of this session). `tests/` is now 6,611 lines against 11,588 of source — a 1:1.75 ratio.
- **All three golden masters byte-identical**, including `phase0_golden.json` whose `_exit_ladder_cases` helper lost its `monkeypatch` argument.
- **Connection count, 45 positions with every stop advancing:** 45 → **0** direct connections from the enrichment loop, one batched writer call covering all 45. An idle refresh with no stop advancing now performs no database work at all.
- **Against a copy of the production database** (live file untouched, 54 ACTIVE profiles): two real profiles raised (+5.00, +1.00), a lowering attempt correctly ignored by `MAX`, zero collateral rows altered.
- Monotonicity re-verified end to end on a real SQLite file: price rallies → stop advances to 120; price falls back → stored stop holds at 120.

## Next Steps

Nothing structural remains from the assessment. What is left in `docs/OPEN_ITEMS.md` is small and optional:

1. **Other laptop** — launch once, confirm it reports `Companies\`, run menu 1. The only item with a real deadline, since a stale `.env` there would rebuild the ghost hub.
2. Two latent ingestion defects, both config-dependent (`yyyyMMdd` ReportDate → 1970; a blank Conid dropping LOT inception dates). Each is pinned by a test naming its trigger.
3. `db.py` opens 33 connections against one `try/finally` — an exception mid-function leaks the handle. The batched writers added here use `try/finally`; the older single-row functions mostly do not.
