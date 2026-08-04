# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (requires uv)
uv sync

# Run the application
uv run python main.py

# Run all tests
uv run python -m pytest tests/ -v

# Run a single test file
uv run python -m pytest tests/test_ledger_engine.py -v

# Run a specific test
uv run python -m pytest tests/test_ledger_engine.py::TestLedgerEngine::test_reset_on_zero -v
```

No linting configuration is set up; no ruff/flake8/mypy config exists.

## Architecture

### Three-Tier Storage (Never Mix)

| Layer | Location | Contents |
|---|---|---|
| Code repo | `C:\repos\trade-journal` | Pure logic, no secrets |
| Config vault | OneDrive `Documents\Logos\.repos\trade-journal` | `.env`, ticker mappings |
| Data hub | OneDrive `Companies\HTC_EOOD\TradeJournalData` | `trade_journal.db`, `prices.db`, CSVs, logs |

`DB_PATH`, `PRICES_DB_PATH`, and all data directories resolve from `DATA_PATH` in `.env`. On startup, `sync_config.smart_sync()` syncs `.env` from OneDrive. On exit, it backs it up.

**One writer at a time.** The ledger is a live SQLite file inside a synced OneDrive folder, so OneDrive cannot merge it: two machines writing with overlapping syncs produces a second database beside the first (`trade_journal-LAPTOP-XYZ.db`) rather than an error. Nothing in the app reports which copy it opened, so a forked ledger is indistinguishable from a healthy one. Close the app on one machine and let OneDrive finish syncing before opening it on the other. `sync_config.check_data_hub()` runs on startup and warns when a duplicate ledger appears — it is read-only by design and never picks a winner; deciding which copy is authoritative is a judgement call. Detector: `sync_config.find_duplicate_hub_files()` (pure).

**A stale `DATA_PATH` silently forks the book — never assume an empty hub is a new one.** `config.DATA_DIR` calls `mkdir(parents=True, exist_ok=True)` (`config.py:31`), so a `DATA_PATH` naming a folder that no longer exists does not fail: it *recreates* it, `init_db` fills it with empty tables, and the app runs normally against a book with no history and no risk layer. Renaming the OneDrive parent folder did exactly this in 2026-08 — `.env` still named the old path, and a full ghost hub (empty DB + YTD-only ingest + price sync) was rebuilt under it. **Any path change to the data hub must be made in `.env` at the same time.** If a report looks impossibly sparse, check `DATA_PATH` before anything else: the live book has ~2,300 trades back to 2024-09 and ~54 ACTIVE risk profiles. Two startup guards now report this class of fault — warnings only, and like the duplicate detector neither one picks a hub: `check_data_hub()` calls out a hub holding no `trade_journal.db` *before* `init_db` creates an empty one, and `smart_sync()` reports two `.env` copies naming different `DATA_PATH`s before mtime alone picks the winner (`sync_config.env_value` is the pure parser).

### Data Flow

```
IBKR Flex API → services/ibkr.py → services/ibkr_parser.py → db.py (trades table)
                                                                      ↓
                                                           data_loader.py → List[Trade]
                                                                      ↓
                                                  core/ledger_engine.py (replay → List[Position])
                                                                      ↓
                                         core/reconciliation_service.py (snapshot + delta merge)
                                                                      ↓
                                              core/portfolio_manager.py (enrichment pipeline)
                                           ┌──────────────┬──────────────┬──────────────┐
                              ui/dashboard.py  ui/risk_workspace.py  ui/watch_list_workspace.py  ui/kids_fund_dashboard.py
```

### Core Invariants

**Ledger Replay:** Positions are always derived by replaying the `trades` table in chronological order — they are never stored. `LedgerEngine.calculate_positions(trades)` is a pure function. This is the single most important architectural constraint; do not persist computed positions.

**Read paths do not write.** Enrichment, parsing and consolidation compute; a named caller persists. `calculate_position_risk` reports an advanced trailing stop as `Position.pending_ratchet` and does not import `db` at all — `PortfolioManager._enrich_metrics` owns that write and commits the whole refresh through `db.update_high_water_marks` in one transaction (nothing at all when no stop moved). `get_broker_verified_snapshot` collects asset-master rows and calls `db.save_ticker_info_bulk` once; `_consolidate_positions` is pure arithmetic and prospect promotion is its own step. This matters most for the ratchet: it is monotonic and permanent, so a write buried in a per-position render loop lets one bad tick raise a stop for good. When adding to these paths, return the value — do not reach for the database.

**One connection idiom.** Every access in `db.py` goes through the `db.connect()` context manager, which closes on every path out — a mid-body `return` included, and any exception. The old `get_conn()` + trailing `conn.close()` pair leaked the handle, and whatever transaction it had begun, whenever a function raised — on a SQLite file OneDrive is also syncing. It is deliberately *not* sqlite3's own `with conn:`, which commits/rolls back and leaves the handle open; commits stay explicit. `get_conn()` stays the single chokepoint tests patch to prove a read path opens nothing (`tests/test_write_boundaries.py`), so `connect()` is its only permitted caller — `tests/test_db_connections.py` enforces both halves by AST sweep.

**Reset-on-Zero:** When a position's quantity reaches zero (within `QTY_ZERO_THRESHOLD = 0.0001`), cost basis is cleared. Re-entry starts a clean new lot. This prevents ghost positions and allows accurate re-entry tracking.

**Reconciliation Bridge:** `ReconciliationService.reconcile_hybrid()` treats an IBKR open-positions CSV as a verified checkpoint and applies pending deltas (confirmations, manual trades entered after the snapshot date) on top. Cost-basis healing recovers true inception prices from the global ledger when the broker snapshot omits them.

**Dual-Constraint Auditing:** Every open position is evaluated against two independent limits:
- Risk limit: `(entry − stop) × qty / NAV ≤ max_r_pct`
- Exposure limit: `HCM(cost, market) / NAV ≤ max_exp_pct`

The tighter constraint wins. HCM = Higher of Cost or Market (never understates exposure).

**Asset Multipliers:** Bonds use `multiplier = 0.001` (face-value → price-point scaling). Options use contract multipliers. `AssetRegistry` is the single source of truth. Bond point correction (100× scaling) is applied to transfer-derived prices in `ibkr_parser.py`.

**Entry & Stop System is additive/default-off:** Every feature from the Entry & Stop System / horizon-calibration build (gates, classification, exit shapes, gap sizing, calibration lens) sits behind a flag/profile whose default reproduces prior behaviour. `tests/test_characterization.py` (golden master over `scan_ticker` / sizing / `classify_regime` / the exit ladder) is the tripwire — it must stay byte-identical with defaults unchanged. Do not alter a default such that this snapshot moves.

**Three golden masters, one rule.** `test_characterization.py` (core decision paths), `test_risk_panel_characterization.py` (the rendered risk panel, 32 scenarios), and `test_command_dsl_characterization.py` (the command DSL, 51 commands) each compare against a committed snapshot in `tests/snapshots/`. They exist so behaviour-preserving work can be *proved* behaviour-preserving: **commit the snapshot before touching the source**, then require it to stay byte-identical through the change. A diff is either a bug or an intended change — if intended, delete the snapshot and regenerate it in its own commit so the diff is reviewable. Never let one silently re-arm around new behaviour (each fails on bootstrap for that reason).

### Key Modules

- **`core/portfolio_manager.py`** — Central orchestrator. Lazily initializes all services via `@property`. `get_dashboard_df()` runs the full enrichment pipeline. Start here when tracing any data issue.
- **`core/ledger_engine.py`** — Pure accounting, no I/O. `_apply_trade()` is the state machine for BUY/SELL/TRANSFER/SPLIT. `_net_daily_transfers()` nets same-day inflows/outflows before replay.
- **`core/reconciliation_service.py`** — Snapshot + delta. `reconcile_hybrid()` is the merge algorithm. Cost-basis healing logic lives here.
- **`core/stop_loss.py`** — `audit_position_risk()` returns GREEN/YELLOW/RED with budget remnants. `calculate_position_risk()` applies the Ratchet Rule and enriches a Position with SL/TP/RR metrics. `get_atr_discovery_data()` fetches `period="max"` once from yfinance and resamples to all timeframes — do not add extra HTTP calls per timeframe. Discovery rows carry `window_shrunk` (thin history shrank the ATR window); `snap_inception_atr()` is the single FIXED-snap rule (excludes shrunken rows; shared by identity with `tools/migrate_fixed_inception_atr.py`) — never freeze a shrunken-window ATR as an inception R unit. Scale-In has been removed — entry type is always SINGLE.
- **`core/profit_taking.py`** — `compute_exit_milestones()` sets `m1_price`, `m2_price`, `exit_stage` on a Position (uniform R-multiple ladder: M1/M2/TP = entry + 1/2/3×R, where R is the inception ATR, for both stop types — the live trailing ATR sets only the stop, never the reward ladder). `classify_regime()` is the pure regime decision (TREND ≥21d + price>DMA, NORMAL 10-20d or unconfirmed reversal, RANGING) including reversal hysteresis; thresholds are overridable kwargs for the opt-in horizon lens. `enrich_regime(positions, mapper, lens_mode)` fetches the DMA signal and applies it — `lens_mode='horizon'` (`regime_lens` setting, default `default`) judges each position on a DMA matched to its stop's ATR horizon via `select_regime_lens()` (risk unit in daily-ATR14 multiples → 50/100/200-DMA, bands in `constants.REGIME_LENS_BANDS`); classification (`C:`) stays carried-only. `TRIM_MATRIX` maps `(stage, regime) → (fraction, rationale)`; a `0.0` fraction means hold (e.g. M2 in TREND). Called from `portfolio_manager.get_dashboard_df()` step 4.
- **`core/sizing.py`** — `compute_position_size()` returns max share qty under dual R%/exposure% constraints. `compute_portfolio_risk()` and `hhi_label()` aggregate portfolio-level R%, stop-out loss, HHI concentration, and currency breakdown. Called by `portfolio_risk.py` (menu option 7). `compute_position_size_gap()` is the opt-in gap-aware path (§6): it risks against `gap_effective_stop(stop, gap_price) = min(stop, gap_price)` (i.e. the larger of R₁ and R_gap); `gap_price=None` reduces exactly to `compute_position_size`. Both sizers take `fx_rate` (asset ccy → NAV ccy, default 1.0 — sizing is FX-normalized at every call site) and an optional `exposure_price` for a current-price exposure leg.
- **Entry & Stop System modules** (`docs/guides/Entry_and_Stop_System.md`, `Horizon_Calibration_3to6mo.md`) — additive, default-off overlays. All are pure except the `trade_log` table:
  - **`core/gates.py`** — pure entry gates G1–G8. `evaluate_gates(ProposedTrade) → list[GateResult]` (PASS/FAIL/NA + reason); `gates_summary()` blocks only on explicit FAIL (NA never blocks). Thresholds from `constants.py` (`GATE_*`); `ProposedTrade.g1_max_stop_atr/g1_max_stop_pct` override G1's caps (the 3–6mo lens passes the ~18% cap and tests against the weekly 12w discovery ATR instead of daily 14d — G1 never tests the snapped inception ATR, a tautology). Wired into `risk_workspace.py` behind the `gates_mode` setting (`off|advisory|blocking`, default `off`); `_gate_check` feeds G2/G3/G5 from the `scan_context` table (fresh within `GATE_CONTEXT_MAX_AGE_DAYS`, else NA) and G7 from the book's open R%. Spec deviations (assessment 2026-07-04): G6 is a permanent NA stub (no liquidity data source); G7 evaluates portfolio heat only (theme dimension cut).
  - **`core/expectancy.py`** — pure analytics over `trade_log`: per-archetype `E[R] = w·W̄ − (1−w)·L̄`, source-vs-benchmark funnel, base-ccy totals, and `suggest_realized_r(entry, stop, avg_exit)` for §7 backfill. Empty-log safe. E[R] is reported at any sample size, but the **verdict** is gated: below `EXPECTANCY_MIN_SAMPLE` closed trades an archetype is `is_provisional` and can never read `above_threshold`, so one lucky 3R winner cannot license full size. Rendered by `ui/expectancy_report.py` (menu option 9), which is also the interactive §7 capture point: `B` backfills realized R on closed lots (ledger-suggested via `db.avg_sell_price_since`, user-confirmed) and `K` logs skipped source picks — a manual complement to the automated pass in `core/outcome_backfill.py`.
  - **`core/outcome_backfill.py`** — automated §7 outcome backfill, run by `main.handle_expectancy()` before the report. Pure core (`find_close_after` zero-crossing replay mirroring `LedgerEngine` sign conventions, `compute_excursions` MAE/MFE, `window_return`) + thin `run_backfill()` runner. Fills `realized_r`/`mae_r`/`mfe_r`/`result_vs_benchmark` on closed TAKEN rows and refreshes SKIPPED rows vs benchmark to date; benchmark cached in `prices.db` under `BENCHMARK:<ticker>` (`benchmark_ticker` setting). Splits inside the window bail out (no wrong R); `realized_return_base` is never fabricated (needs FX-at-exit). Journal feeds: `SRC:`/`THM:` commit tokens (risk workspace) and the skipped-pick forms (Watch List `L`-key, expectancy report `K`-key).
  - **`core/trade_log.py`** — `TradeLogEntry` dataclass + `COLUMN_TYPES` (single schema source for the `trade_log` table). Decision journal, separate from the `trades` execution ledger; `status ∈ {TAKEN, SKIPPED}` (skipped source picks logged for §0a funnel benchmarking). One row per open lot: classified commits upsert via `db.find_open_trade_log_id` (open = TAKEN with `realized_r IS NULL`); duplicates would double-count a lot in E[R].
  - **`core/exit_shapes.py`** — per-trade exit shape (§5a): `LADDER` (default, = today's ladder) / `HARD` / `THESIS`; `RUNNER` survives only as a legacy alias of the default (cut as a distinct shape — it was behaviourally identical). Two hooks only: THESIS drops `tp_price` in `calculate_position_risk`; HARD makes the TP-stage action a full exit in `_exit_recommendation`. No time stop.
  - **`core/calibration.py`** — `CalibrationProfile`; `DEFAULT_CALIBRATION` (mirrors today's daily constants — a no-op) and `POSITION_3TO6MO` (weekly lens, longer ATR, wider buffers, 30-week-MA anchor, MOMENTUM override). `scan_ticker(calibration=…)` consumes it; selected via the `calibration_profile` setting (default `default`), editable in the risk-workspace `M` modal; the active lens shows in the risk-workspace and zone-scanner headers. The 3–6mo "long ATR" is a daily-window approximation (`CAL_3TO6MO_ATR_WINDOW`); true weekly resampling is deferred.
- **`core/modeling.py`** — the pre-trade what-if engine, extracted from the risk workspace. `build_position_model(position, total_nav, inputs, discovery, exit_recommender)` returns a frozen `PositionModel` carrying the resolved inputs, the dual-constraint audit, the reward geometry (`r_unit`/`tp_target`/`efficiency`), the reconciled `Verdict`, and the post-action `SizingProjection`. `decide_verdict()` encodes the precedence chain (breach → explicit ±N/BE model → exit stage → add → trim → hold) and is separately callable. Pure — no I/O, no markup; `_exit_recommendation` is injected. `ui/risk_workspace.refresh_risk_checklist` renders it and nothing else.
- **`core/command_parser.py`** — the Strategy Lab DSL. `parse_command(raw, CommandContext, presets)` returns a frozen `ParsedCommand` (+ `to_draft()`); token order is load-bearing and documented in the module (`X:T`/`THM:` vs the T flag, `TP:+35%` vs a share add, `TP:N:1` vs a fixed multiple). Owns `parse_classification`, `resolve_tp_mult`, `resolve_tp_ratio` and `resolve_inception_atr` (the FIXED-stop snap, which must never return None — `db.set_position_risk` degrades a NULL inception to `atr_value`, the stop price). Messages are returned as `notes`/`warnings`, never emitted.
- **`core/confluence.py`** — `evaluate_confluence(price, stop, levels, atr)` measures ATR-distance from price and stop to an open dict of structural `levels` (DMAs/EMAs, volume-profile VAL/VAH/POC, anchored VWAPs); returns strength, per-level detail, and named zones. Single source of truth — both `watch_list_workspace.py` and `zone_scan.py` call it (no inline duplicate).
- **`core/volume_profile.py`** — composite volume profile approximated from daily bars (no tick data on Yahoo). `compute_volume_profile()` smears each bar's volume across its high-low range with a triangular weight peaking at the close, into fixed price buckets → POC/VAH/VAL. `find_naked_pocs()` flags unretested high-volume shelves. Pure; reads the `prices_daily` cache via the caller. Daily-bar approximation — never represent it as tick-derived.
- **`core/anchored_vwap.py`** — `find_pivots()` (symmetric fractal swing detection), `anchored_vwap()` (volume-weighted typical price from an anchor bar), `compute_anchored_vwaps()` (most-recent swing-low and swing-high anchors). Pure.
- **`core/zone_scan.py`** — Entry/Exit Zone Scanner orchestrator. `scan_ticker()` / `build_zone_report()` merge VP + AVWAP + DMAs into one confluence read, pick a stop (nearest support, or momentum micro-structure), and size under all presets; I/O is injected via a `price_loader`. The zone flag counts only **independent** levels (`ZONE_DEDUP_EPS_ATR` — coincident VAL/POC count once, §4a); tickers too young for the scan window surface as `insufficient_data` stub rows instead of being dropped. **Momentum Regime:** when price runs >`MOMENTUM_VAL_PREMIUM_PCT` above the 6mo VAL, the stop switches to the tightest micro-structure level below price from the `MICRO_LOOKBACK_DAYS` window — VAL, high-volume node (`find_high_volume_nodes`, ≥`HVN_MIN_PROMINENCE`), swing-low AVWAP, or breakout-gap floor (`_breakout_gap_floor`, gap ≥`GAP_MIN_ATR`) — minus `MICRO_STOP_BUFFER_ATR`; the row is tagged `ZONE-MOMO` and the winning anchor is named in `stop_source` (`VAL_14d`/`HVN_14d`/`AVWAP_14d`/`GAP_14d`). `scan_ticker(calibration=…)` accepts a `core/calibration.CalibrationProfile` that overrides the horizon knobs; the `position_3to6mo` profile disables the micro-stop so a MOMENTUM flag falls back to the weekly value anchors (`None`/`DEFAULT_CALIBRATION` = today's scan, unchanged).
- **`services/ibkr_parser.py`** — CSV interpretation. External ID fingerprint = `TransactionID-AccountID-Side` for de-duplication. Updates `ticker_info` (Asset Master) during ingestion.
- **`services/ticker_mapper.py`** — IBKR → Yahoo Finance symbol resolution. Priority: DB conid lookup → YF ISIN search → heuristics (exchange suffixes `.DE`, `.L`, `.AS`).
- **`ui/risk_workspace.py`** — ACTION column uses asymmetric thresholds: ≥10% budget remaining triggers Add, ≥5% triggers Trim (filters transaction noise). Command syntax: `VALUE [F/T] [P:S/B/L] [R:x] [E:x] [TP:n] [C:TH/TE] [G:gap] [X:H/T] [SRC:name] [THM:theme]` — `TP:n` take-profit override (forms: `nR`, `+35%`, `N:1`, `-`; the `$` form was cut); `C:` THESIS/TECHNICAL tag (§0a, carried — a THESIS tag couples to the thesis exit shape unless an explicit `X:` overrides); `G:` plausible gap price → opt-in gap-aware sizing (§6); `X:` exit shape (§5a; `X:R` = legacy alias of the default ladder); `SRC:`/`THM:` idea source/theme (§7, journal-only — not persisted on the profile). Drafting workflow holds bulk updates in-memory before committing. On commit, `_gate_check` runs entry gates per the `gates_mode` setting (`off|advisory|blocking`, default `off`, toggled in the `M` preset/settings modal alongside `regime_lens` and `calibration_profile`; the active gates/lens show in the header banner); a classified or sourced commit (`C:` or `SRC:`) upserts the open lot's `trade_log` entry (one decision, one row) incl. r1. PLAN section includes full exit stage and regime breakdown.
- **`ui/watch_list_workspace.py`** — Confluence distances are measured in Daily ATR units; < 0.25R is a meaningful zone. Undisturbed Trend Engine tracks 200-DMA direction changes with a 21-day confirmation trigger (🟢 BUY / 🔴 SELL). `L` key logs a **skipped source pick** (§0a) — a `SKIPPED` `trade_log` row with date/price/source/theme for funnel benchmarking.
- **`ui/chart_utils.py`** — `launch_price_chart(display_ticker, conid, yf_ticker)` spawns `chart_worker.py` as a subprocess. Triggered by `G` key in all three workspaces.
- **`ui/chart_worker.py`** — Standalone subprocess entry point. Renders price + 200 DMA chart (5Y) via matplotlib/TkAgg in its own main thread. Never imported directly.
- **`ui/zone_scan_workspace.py`** — Entry/Exit Zone Scanner (menu option 8). Scans the universe (ACTIVE holdings + `status='WATCH'`) via `core/zone_scan.py`, rendering the `ZONE` / `ZONE-MOMO` / `THIN` tag, converging signals, stop, target, and preset sizes. Persists `scan_context` per ticker after each scan (gate inputs) and, via the `c` key on a flagged row, a one-shot `pending_handoff` that prefills the Risk Workspace command box on its next launch. Runs the scan in a background thread.

### Database Schema (SQLite — `trade_journal.db`)

- **`trades`** — Activity ledger. `side` ∈ {BUY, SELL, TRANSFER_IN, TRANSFER_OUT, SPLIT, OPENING_BALANCE, IBKR_CONFIRMATION}. `external_id` is the de-duplication fingerprint (UNIQUE).
- **`risk_profiles`** — Risk settings per conid. `status` ∈ {ACTIVE, WATCH, CLOSED}. Unique index on `(conid, status='ACTIVE')` and `(conid, status='WATCH')`. `classification` (THESIS/TECHNICAL, §0a) and `exit_shape` (§5a) are additive, NULL-defaulted, and carried onto the Position — the exit ladder branches on `exit_shape` only (THESIS drops the target). `ccy` (additive, NULL-defaulted) records a WATCH prospect's pricing currency at add time so sizing borrows the right ccy→NAV fx rate (`core/portfolio_manager.resolve_prospect_fx` — held-book borrow first, live FX fallback); NULL = legacy row, USD assumed.
- **`trade_log`** — Decision journal (Entry & Stop System §7), separate from the `trades` execution ledger. Schema is driven by `core/trade_log.COLUMN_TYPES`; every column is nullable/defaulted, and the per-column `ALTER` loop in `init_db` is the additive migration. `status` ∈ {TAKEN, SKIPPED}.
- **`ticker_info`** — Asset Master keyed by `conid`. Populated by the parser; the resolver looks here first.
- **`schema_migrations`** — one row per applied one-shot migration. `init_db`'s `CREATE TABLE`/`ALTER` statements are structurally idempotent and still re-run every startup; every statement that **mutates user rows** lives in `db._ONE_SHOT_MIGRATIONS` and runs exactly once. Their `WHERE` clauses are historical guards, not permanent invariants — re-running them can rewrite a legitimate row created long afterwards. **Adding a new entry to that tuple is the migration mechanism**; never put a mutating statement inline in `init_db` again.
- **`kids_config`** — Private wealth glide path beneficiary config (manual).
- **`scan_context`** — latest zone-scan structural context per ticker (regime, flagged, independent confluence count, stop_source/price, DMA200 trail anchor, scan_date). Written by `ui/zone_scan_workspace.py` after every scan; read freshness-guarded by `_gate_check` so gates G2/G3/G5 get real inputs. REPLACE per ticker — never accumulates.
- **`settings`** — key/value app settings. Keys: `action_threshold_pct`, `gates_mode` (`off|advisory|blocking`), `calibration_profile` (`default|position_3to6mo`), `regime_lens` (`default|horizon`), `benchmark_ticker` (default `SPY`), `pending_handoff` (one-shot zone-scanner→risk-workspace prefill, JSON, consumed on workspace mount).

Secondary database **`prices.db`** holds `prices_daily (conid, date PK)` for OHLCV cache.

**Price basis is pinned (one series, one adjustment basis):** yfinance is queried with `auto_adjust=True`, so every split and dividend re-bases Yahoo's *entire* history, while `save_prices` only ever appends dates it has not seen. Unguarded, the cache becomes old-basis history welded to new-basis recent bars, with an invisible seam that corrupts ATR, the 200-DMA, the volume profile, and — worst — `highest_high_since`, which feeds the trailing ratchet that writes a stop into the DB permanently. `fetch_and_store` therefore starts its forward update `PRICE_BASIS_OVERLAP_DAYS` *before* the last cached bar and calls `basis_shifted()`: a settled bar that disagrees with the cache means Yahoo re-based, and `rebuild_series()` re-downloads and REPLACEs the whole series. The newest cached bar is excluded from the comparison (mid-session it is a partial day). Maintenance option 5 forces the rebuild for pre-existing seams.

### Risk Metrics

**ATR Standards:** Institutional timeframes — Daily(14), Weekly(12), Monthly(12), Quarterly(12). Wilder ATR via `ewm(com=window-1, adjust=False)`, seeded from the first TR (not the SMA of the first n TRs — pandas has no SMA seed). The difference decays to nothing over the `period="max"` history every call site uses; both ATR implementations (`stop_loss._compute_atr_rows`, `zone_scan._wilder_atr`) use the identical method so they cannot disagree.

**Portfolio Heat (never nets):** `compute_portfolio_risk`'s `total_r_pct` sums only **positive** `risk_pct_nav`. A stop ratcheted above entry carries a negative value (a gain locked in at the stop) — correct for "what does a stop-out pay?", wrong for "how much NAV is still at risk". Netting would let one winner cancel live downside elsewhere and hand back budget headroom that does not exist. `total_r_pct_net` carries the netted figure for display only; `total_stop_out` (currency P/L) stays net by design. The G7 heat proxy in `risk_workspace._gate_check` floors each name at zero by the same rule.

**Volatility Buffer (Fixed Dollar):** Stop percentages are converted to a fixed dollar `atr_value` at entry. As price rises the percentage tightens — this is intentional. Never recompute from a percentage at current price.

**R (% NAV):** `(entry − stop) × qty / NAV`. Normalized to NAV currency via live FX rates from the broker snapshot.

**RR Efficiency:** `(TP − Price) / (Price − Stop)`. **Informational only — not an exit trigger.** Color bands (PLAN strip): 🟢 ≥ 2.0, 🟡 ≥ 1.0, 🔴 < 1.0. (The former sub-1.0 RR "efficiency floor" that forced a FIXED-stop exit was removed: a deep stop drags RR low on geometry alone. Exits come from the stop and a RANGING regime; see `docs/TECHNICAL_DOCS.md` §5.)

**Exit Milestones & Regime:** Milestones computed in `profit_taking.compute_exit_milestones()`; regime in `profit_taking.enrich_regime()`/`classify_regime()` (step 4 of `get_dashboard_df`). TP and milestones are entry-anchored and use the inception ATR (R-multiple) for both stop types; the live trailing ATR sets only the stop. For a **FIXED** stop (where the user enters a stop *price*, not an ATR distance) the inception ATR is the discovery-timeframe ATR nearest `entry − stop` — snapped at commit in `risk_workspace.py`, so the ladder matches the stop's horizon instead of a hardcoded daily ATR; TRAILING carries its own distance unchanged. The TP top rung is overridable per position via `risk_profiles.tp_atr_mult` (a multiple of the *frozen inception* ATR; `NULL` = default `TP_ATR_MULTIPLE` = 3R) — set with the `TP:n` command (`resolve_tp_mult`); M1/M2 stay at 1R/2R. Full thresholds and trim guidance in `docs/TECHNICAL_DOCS.md` §5.

**Capital-Efficiency Flag (Dead Money):** `Position.is_stale` (set in `calculate_financial_metrics`) flags a holding older than `STALE_MIN_AGE_DAYS` whose price-only `aagr` is below `CAPITAL_HURDLE_PCT`. Orthogonal to the exit ladder; income assets (`AssetRegistry.is_income_asset`) are excluded. Surfaced in the `risk_workspace.py` PLAN panel.

### Presentation Layer (Textual UIs)

All UIs are Textual apps in `ui/`, launched from `main.py`. They are display-only and do not write to the database except `ui/risk_workspace.py` (persists `risk_profiles` edits via command syntax, e.g. `15 T P:L` = 15% stop, Trailing, Large preset; upserts `trade_log` on classified commits) and `ui/zone_scan_workspace.py` (persists per-ticker `scan_context` after each scan and the one-shot `pending_handoff` setting via the `c` key). Scale-In has been removed; entry type is always SINGLE.

**F1 Help (single source of truth):** `services/ui_components.py` `HelpScreen` renders the `.md` files listed in `HELP_FILES` (the `docs/guides/*.md` set + `docs/TECHNICAL_DOCS.md`) via the Textual `Markdown` widget — no hardcoded help strings. `docs/guides/` is therefore canonical for all user-facing definitions and workflows; editing a guide updates F1 automatically, but a new guide must be registered in `HELP_FILES` to appear. `Indicator_Glossary.md` is the canonical home for every indicator/metric definition; `User_Guide.md` (first tab) is the task-level operating manual — procedure only, strategy rationale stays in the strategy guides.

### Session Protocol

When asked to "wrap it up":
1. `git diff --stat` / `git log --oneline` — identify all changes since last session log.
2. Create `docs/sessions/YYYY-MM-DD_Brief_Description.md` — sections: Objectives, Technical Changes, Logic & Decisions, Verification, Next Steps.
3. Update this file (CLAUDE.md) for architectural changes only — module additions, schema changes, new invariants. No feature detail or trim percentages.
4. Update `docs/TECHNICAL_DOCS.md` for any user-facing feature additions or changes.
5. Commit session log + any doc changes.
6. Remind user to run backup (`uv run python sync_config.py`).

Use `/wrap-up` to trigger the session wrap-up command.
