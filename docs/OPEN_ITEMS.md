# Open Items

Living checklist of pending work, surfaced on startup by `main.py`.
Tick an item (`- [ ]` → `- [x]`) or delete it when done. Keep it short.

## Entry & Stop System feature stream (all done)

- [x] Launch ZONE SCANNER (option 8) and confirm the Textual panel renders/navigates correctly
- [x] Fix watch-list price-cache gap: WATCH names lack prices.db history (sync covers only open positions) and are silently dropped from the zone scan — fetch on add, or fetch-on-demand in run_scan
- [x] Build one dedicated add-to-watchlist entry point (NOT via the Risk Workspace)
- [x] Momentum stop-tier v2: breakout-gap and high-volume-node micro-anchors
- [x] Horizon-aware regime lens: the trim-driving regime is hardcoded to the 200-DMA (21d confirmation) regardless of the trade's horizon. Key the lens off the stop's volatility horizon instead — stop distance in daily-ATR multiples → Daily≈tight → 50-DMA/10d; Weekly → 100-DMA/15d; Monthly+ → 200-DMA/21d (today's behaviour). Mirrors the inception-ATR snapping already done for the milestone ladder; classification (C:) stays carried-only. Default-off behind the `regime_lens` setting (`M` modal); characterization snapshot unchanged.
- [x] Complete the Entry & Stop System §7 logging loop — DONE: `SRC:`/`THM:` commit tokens (risk workspace), Watch List `L`-key skipped-pick logging, `benchmark_ticker` setting (SPY) cached as `BENCHMARK:<ticker>` in prices.db, and `core/outcome_backfill.py` (realized R + MAE/MFE + vs-benchmark, auto-run on menu 9). `realized_return_base` deliberately left NULL (needs an FX-at-exit source — future item).

## Audit remediation & advisory gates

Source: Fable_Application_Assessment_Review.md (Must-fixes and Cuts done 2026-07-04).

### Do now — small, NOT gated on the fork (all done 2026-07-04)

- [x] De-dup `trade_log` writes per (conid, open lot) — `C:`-tagged commits write rows regardless of `gates_mode`, so duplicates poison E[R] the moment tagging starts
- [x] Zone scanner: de-duplicate identical-price levels in confluence counting (spec §4a minimum viable form — VAL==POC currently counts twice)
- [x] Zone scanner: surface "insufficient data" rows instead of silently dropping young tickers
- [x] One-line mode banner (`gates: off · lens: default`) in risk-workspace and zone-scanner headers
- [x] Make `calibration_profile` selectable in the `M` modal — the 3–6mo lens currently has no door

### Fork — DECIDED 2026-07-04: advisory gates + handoff (all built)

- [x] DECIDE the strategic fork: advisory gates + scanner→workspace handoff; `blocking` waits until advisory output earns trust
- [x] G1 tests against a fixed named market ATR (daily 14d; weekly 12w under the 3–6mo lens) — inception-ATR tautology gone
- [x] Gates reconciled with the calibration profile (G1 → 18% cap + weekly ATR under `position_3to6mo`)
- [x] Scanner→workspace handoff: `scan_context` table feeds G2/G3/G5 on every commit; `c` key prefills the command box (one-shot, 1h expiry); G7 wired to open book R%
- [x] Flip `gates_mode` to `advisory` (set directly in settings 2026-07-04; the banner shows it)

### Decide separately — the expectancy loop (done 2026-07-04)

- [x] Minimal §7 capture: menu 9 now backfills realized R on closed lots (ledger-suggested, user-confirmed) and logs skipped picks via `K`

### Low / whenever (done 2026-07-04)

- [x] Couple C:TH to X:T as an overridable default (one clock per trade, spec §0a)
- [x] Cheap §1a staleness check — 14d vs 12w ATR ratio warning under the 3–6mo lens
- [x] README.md rewritten to match the current app (Gemini-era content removed)

Queue clear. Standing observation (not an action item): run gates in `advisory` for a
few weeks and review the FAIL/NA pattern before considering `blocking`.

## Whole-application assessment (2026-08-04)

Source: `docs/sessions/2026-08-04_Application_Assessment_And_Integrity_Fixes.md`.
Items 1–7 and the doc cleanups are done; what remains is structural.

- [x] **Extract the modeling engine + command DSL out of `ui/risk_workspace.py`** — done 2026-08-04. `core/modeling.py` (the what-if engine + verdict chain) and `core/command_parser.py` (the DSL) are pure and directly tested; the file is 1,595 → 1,326 lines, `refresh_risk_checklist` 336 → 231 (139 → 74 branches), `on_strategy_change` 258 → 107 (81 → 29). Two golden masters (`risk_panel_golden.json`, `command_dsl_golden.json`) were committed BEFORE the source moved and stayed byte-identical through it.
- [x] **Push DB writes out of read paths** — done 2026-08-04. `calculate_position_risk` is pure and no longer imports `db` at all (it reports `pending_ratchet`); `PortfolioManager._enrich_metrics` owns the write and batches it via `db.update_high_water_marks`. Snapshot parsing collects asset-master rows and writes once (`db.save_ticker_info_bulk`); prospect promotion is an explicit step, no longer hidden inside the WAC merge. A 45-position refresh went from 45 ratchet connections to 1 — and to **zero** when no stop advanced. The 17 test monkeypatches that existed only to neutralise the write are gone.
- [x] **Cover the ingestion boundary** — done 2026-08-04. 74 tests over `ticker_mapper.resolve_yf_ticker` and `data_loader.get_broker_verified_snapshot`/`clean_trade_data`, all hermetic (no network, no data hub). Three defects found and pinned:
  - [x] **`ticker_mapper` `UnboundLocalError` — fixed 2026-08-04.** `info` is now bound before the `if conid:` block, so the CSV-driven `conid` reassignment can no longer read an unbound name. Discovering an already-held symbol (`BRK B`, `FOUR PRA`) works, and the CSV-discovered conid is persisted to the asset master as intended. 4 regression tests, verified failing against the pre-fix module.
  - [x] **`yyyyMMdd` ReportDate parses to 1970 — fixed 2026-08-04.** `_parse_flex_date` parses the 8-digit form explicitly (Flex sets the date format per query; the *trades* query already uses `yyyyMMdd`, so the open-positions query can change under us) and returns **None, never NaT**, when nothing parses. The NaT return was a second silent failure: `_filter_pending_deltas` guards with `if not report_date`, and `bool(pd.NaT)` is `True`, so NaT slipped past the guard and then compared `False` against every trade date — discarding every pending delta rather than applying them all. 3 regression tests.
  - [x] **A blank Conid drops every LOT inception date — fixed 2026-08-04.** Lot keys and the summary key now both go through one `_conid_key` helper, so a blank Conid floating the column to float64 can no longer spell the same asset "12345.0" on one side and "12345" on the other. `clean_trade_data` delegates to the same helper. 1 regression test.
- [x] **`db.py` leaked connections on any error path — fixed 2026-08-04.** All 35 call sites now go through one `db.connect()` context manager (`get_conn` stays the chokepoint tests patch, so `test_write_boundaries` is untouched); `data_loader.load_trades_from_db` got the same treatment via `contextlib.closing`. `init_db`'s body moved to `_create_schema(conn)` so the 190-line schema block did not have to be re-indented. `tests/test_db_connections.py` (8 tests) pins it, including an AST sweep asserting `connect()` is the only caller of `get_conn()` and that no manual `conn.close()` returns — that guard is what stops the next function added to `db.py` from reintroducing the pair.
- [x] Confirm the configured `DATA_PATH` is the intended hub — it was **not**. The OneDrive parent folder was renamed `Accounts` → `Companies` without updating `.env`, so `config.mkdir` recreated the old path as a ghost hub and `init_db` + a YTD-only ingest filled it (488 trades, 0 profiles). Repointed to `OneDrive\Companies\...` 2026-08-04, both `.env` copies; verified 2,306 trades / 54 ACTIVE / `gates_mode=advisory`.
- [x] Delete the ghost hub `OneDrive\Accounts\` — done 2026-08-04 (7 files / 13.9 MB, none older than the rename). Path references purged from `.env`, `CLAUDE.md`, `README.md`.
- [ ] **On the other laptop (needs that machine — cannot be closed from here):** launch the app once and confirm the header/logs show `Companies\`. Its `.env` should self-heal (`sync_config` pulls the newer vault copy), but if its local `.env` has a newer mtime it will push the old path back and rebuild the ghost hub. Then run menu 1 — the broker snapshot CSVs in the live hub are from 7/30.
  - Guarded 2026-08-04 so this is now *loud* rather than silent, but still needs the visit: `smart_sync()` prints `THE TWO .env COPIES NAME DIFFERENT DATA HUBS` (naming both, choosing neither) before mtime decides, and `check_data_hub()` prints `NO LEDGER IN THE CONFIGURED DATA HUB` before `init_db` creates an empty book. Pure parser `sync_config.env_value`; 18 tests in `tests/test_hub_conflicts.py`. Verified silent against the healthy config on this machine.
- [x] OneDrive conflict copies in the data hub — resolved 2026-08-04. The forked DB (`-LAPTOP-20V5N4Q9`, 6/28) was verified a **strict subset** of the live ledger (0 trades and 0 profiles unique to it), so nothing was lost; it and five stray `.log` copies were deleted (26 MB). `sync_config.check_data_hub()` now warns on startup if a duplicate ledger reappears. Single-writer rule documented in CLAUDE.md + TECHNICAL_DOCS §12.
