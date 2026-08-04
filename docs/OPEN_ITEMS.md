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
- [ ] **Push DB writes out of read paths.** `calculate_position_risk` writes the ratchet inside the enrichment loop; `_consolidate_positions` promotes prospects; `get_broker_verified_snapshot` writes the asset master. Return the values; let one caller persist.
- [x] **Cover the ingestion boundary** — done 2026-08-04. 74 tests over `ticker_mapper.resolve_yf_ticker` and `data_loader.get_broker_verified_snapshot`/`clean_trade_data`, all hermetic (no network, no data hub). Three defects found and pinned:
  - [ ] **`ticker_mapper.py:137` `UnboundLocalError` — reachable today, silent.** `info` is bound only inside `if conid:`, but a symbol matched in the cached positions CSV *assigns* `conid` further down, so `if conid and info:` then raises. Trigger: resolve without a conid for a symbol you already hold — i.e. the prospect/discovery flow (`fetch_atr_data(None, ticker=…)`). `get_atr_discovery_data` swallows it, so discovery just returns nothing. The live CSV holds `BRK B`, `FOUR PRA` and an IWM option, which all reach this path. Same class as the `C:TH` bug; one-line fix.
  - [ ] **`yyyyMMdd` ReportDate parses to 1970.** The live open-positions query emits ISO so this is latent, but Flex date format is per-query and the *trades* query already uses `yyyyMMdd`. `pd.to_datetime(20260730)` reads nanoseconds-since-epoch with no error, and `report_date` is the reconciliation checkpoint — a 1970 checkpoint re-applies every confirmation on top of a snapshot that already contains it (double-counted positions).
  - [ ] **A blank Conid drops every LOT inception date.** Lot keys come from `astype(str)` ("12345.0" once pandas sees one blank and types the column float) while the lookup asks for `str(int(float(...)))` ("12345"). Latent: the current query returns no LOT rows at all. Would fire the moment lot detail is enabled.
- [ ] Low: `db.py` opens 33 connections against one `try/finally` — an exception mid-function leaks the handle.
- [x] Confirm the configured `DATA_PATH` is the intended hub — it was **not**. The OneDrive parent folder was renamed `Accounts` → `Companies` without updating `.env`, so `config.mkdir` recreated the old path as a ghost hub and `init_db` + a YTD-only ingest filled it (488 trades, 0 profiles). Repointed to `OneDrive\Companies\...` 2026-08-04, both `.env` copies; verified 2,306 trades / 54 ACTIVE / `gates_mode=advisory`.
- [x] Delete the ghost hub `OneDrive\Accounts\` — done 2026-08-04 (7 files / 13.9 MB, none older than the rename). Path references purged from `.env`, `CLAUDE.md`, `README.md`.
- [ ] **On the other laptop:** launch the app once and confirm the header/logs show `Companies\`. Its `.env` should self-heal (`sync_config` pulls the newer vault copy), but if its local `.env` has a newer mtime it will push the old path back and rebuild the ghost hub. Then run menu 1 — the broker snapshot CSVs in the live hub are from 7/30.
- [x] OneDrive conflict copies in the data hub — resolved 2026-08-04. The forked DB (`-LAPTOP-20V5N4Q9`, 6/28) was verified a **strict subset** of the live ledger (0 trades and 0 profiles unique to it), so nothing was lost; it and five stray `.log` copies were deleted (26 MB). `sync_config.check_data_hub()` now warns on startup if a duplicate ledger reappears. Single-writer rule documented in CLAUDE.md + TECHNICAL_DOCS §12.
