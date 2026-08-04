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

- [ ] **Extract the modeling engine + command DSL out of `ui/risk_workspace.py`.** `refresh_risk_checklist` (336 lines / 139 branches / 9 `hypo_*` args) and `on_strategy_change` (258 / 81) are the repo's top complexity scores, in its highest-churn file, with no headless entry point — tests reach into six private helpers to get at them. Every defect found in the assessment sat in an untested function here. **Coordinate first: this branch has a second writer and this is the file that conflicts.**
- [ ] **Push DB writes out of read paths.** `calculate_position_risk` writes the ratchet inside the enrichment loop; `_consolidate_positions` promotes prospects; `get_broker_verified_snapshot` writes the asset master. Return the values; let one caller persist.
- [ ] **Cover the ingestion boundary.** `ticker_mapper.resolve_yf_ticker` (36 branches, zero tests) and `data_loader.get_broker_verified_snapshot` against a fixture CSV — where wrong data enters.
- [ ] Low: `db.py` opens 33 connections against one `try/finally` — an exception mid-function leaks the handle.
- [ ] Confirm the configured `DATA_PATH` is the intended hub: it holds 488 trades but 0 `risk_profiles`, 0 `trade_log`, and `gates_mode='off'` (the advisory flip above is not in that data).
