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
| Data hub | OneDrive `Accounts\HTC_EOOD\TradeJournalData` | `trade_journal.db`, `prices.db`, CSVs, logs |

`DB_PATH`, `PRICES_DB_PATH`, and all data directories resolve from `DATA_PATH` in `.env`. On startup, `sync_config.smart_sync()` syncs `.env` from OneDrive. On exit, it backs it up.

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

**Reset-on-Zero:** When a position's quantity reaches zero (within `QTY_ZERO_THRESHOLD = 0.0001`), cost basis is cleared. Re-entry starts a clean new lot. This prevents ghost positions and allows accurate re-entry tracking.

**Reconciliation Bridge:** `ReconciliationService.reconcile_hybrid()` treats an IBKR open-positions CSV as a verified checkpoint and applies pending deltas (confirmations, manual trades entered after the snapshot date) on top. Cost-basis healing recovers true inception prices from the global ledger when the broker snapshot omits them.

**Dual-Constraint Auditing:** Every open position is evaluated against two independent limits:
- Risk limit: `(entry − stop) × qty / NAV ≤ max_r_pct`
- Exposure limit: `HCM(cost, market) / NAV ≤ max_exp_pct`

The tighter constraint wins. HCM = Higher of Cost or Market (never understates exposure).

**Asset Multipliers:** Bonds use `multiplier = 0.001` (face-value → price-point scaling). Options use contract multipliers. `AssetRegistry` is the single source of truth. Bond point correction (100× scaling) is applied to transfer-derived prices in `ibkr_parser.py`.

### Key Modules

- **`core/portfolio_manager.py`** — Central orchestrator. Lazily initializes all services via `@property`. `get_dashboard_df()` runs the full enrichment pipeline. Start here when tracing any data issue.
- **`core/ledger_engine.py`** — Pure accounting, no I/O. `_apply_trade()` is the state machine for BUY/SELL/TRANSFER/SPLIT. `_net_daily_transfers()` nets same-day inflows/outflows before replay.
- **`core/reconciliation_service.py`** — Snapshot + delta. `reconcile_hybrid()` is the merge algorithm. Cost-basis healing logic lives here.
- **`core/stop_loss.py`** — `audit_position_risk()` returns GREEN/YELLOW/RED with budget remnants. `calculate_position_risk()` applies the Ratchet Rule and enriches a Position with SL/TP/RR metrics. `get_atr_discovery_data()` fetches `period="max"` once from yfinance and resamples to all timeframes — do not add extra HTTP calls per timeframe. Scale-In has been removed — entry type is always SINGLE.
- **`core/profit_taking.py`** — `compute_exit_milestones()` sets `m1_price`, `m2_price`, `exit_stage` on a Position (uniform R-multiple ladder: M1/M2/TP = entry + 1/2/3×R, where R is the inception ATR, for both stop types — the live trailing ATR sets only the stop, never the reward ladder). `classify_regime()` is the pure regime decision (TREND ≥21d + price>DMA, NORMAL 10-20d or unconfirmed reversal, RANGING) including reversal hysteresis; `enrich_regime()` fetches the 200-DMA signal and applies it. `TRIM_MATRIX` maps `(stage, regime) → (fraction, rationale)`; a `0.0` fraction means hold (e.g. M2 in TREND). Called from `portfolio_manager.get_dashboard_df()` step 4.
- **`core/sizing.py`** — `compute_position_size()` returns max share qty under dual R%/exposure% constraints. `compute_portfolio_risk()` and `hhi_label()` aggregate portfolio-level R%, stop-out loss, HHI concentration, and currency breakdown. Called by `portfolio_risk.py` (menu option 7).
- **`core/confluence.py`** — `evaluate_confluence()` measures ATR-distance from price and stop to all configured DMAs; returns strength score and zone list.
- **`services/ibkr_parser.py`** — CSV interpretation. External ID fingerprint = `TransactionID-AccountID-Side` for de-duplication. Updates `ticker_info` (Asset Master) during ingestion.
- **`services/ticker_mapper.py`** — IBKR → Yahoo Finance symbol resolution. Priority: DB conid lookup → YF ISIN search → heuristics (exchange suffixes `.DE`, `.L`, `.AS`).
- **`ui/risk_workspace.py`** — ACTION column uses asymmetric thresholds: ≥10% budget remaining triggers Add, ≥5% triggers Trim (filters transaction noise). Command syntax: `VALUE [F/T] [P:S/B/L] [R:x] [E:x]`. Drafting workflow holds bulk updates in-memory before committing. PLAN section includes full exit stage and regime breakdown.
- **`ui/watch_list_workspace.py`** — Confluence distances are measured in Daily ATR units; < 0.25R is a meaningful zone. Undisturbed Trend Engine tracks 200-DMA direction changes with a 21-day confirmation trigger (🟢 BUY / 🔴 SELL).
- **`ui/chart_utils.py`** — `launch_price_chart(display_ticker, conid, yf_ticker)` spawns `chart_worker.py` as a subprocess. Triggered by `G` key in all three workspaces.
- **`ui/chart_worker.py`** — Standalone subprocess entry point. Renders price + 200 DMA chart (5Y) via matplotlib/TkAgg in its own main thread. Never imported directly.

### Database Schema (SQLite — `trade_journal.db`)

- **`trades`** — Activity ledger. `side` ∈ {BUY, SELL, TRANSFER_IN, TRANSFER_OUT, SPLIT, OPENING_BALANCE, IBKR_CONFIRMATION}. `external_id` is the de-duplication fingerprint (UNIQUE).
- **`risk_profiles`** — Risk settings per conid. `status` ∈ {ACTIVE, WATCH, CLOSED}. Unique index on `(conid, status='ACTIVE')` and `(conid, status='WATCH')`.
- **`ticker_info`** — Asset Master keyed by `conid`. Populated by the parser; the resolver looks here first.
- **`kids_config`** — Private wealth glide path beneficiary config (manual).

Secondary database **`prices.db`** holds `prices_daily (conid, date PK)` for OHLCV cache.

### Risk Metrics

**ATR Standards:** Institutional timeframes — Daily(14), Weekly(12), Monthly(12), Quarterly(8). Wilder ATR with SMA baseline.

**Volatility Buffer (Fixed Dollar):** Stop percentages are converted to a fixed dollar `atr_value` at entry. As price rises the percentage tightens — this is intentional. Never recompute from a percentage at current price.

**R (% NAV):** `(entry − stop) × qty / NAV`. Normalized to NAV currency via live FX rates from the broker snapshot.

**RR Efficiency:** `(TP − Price) / (Price − Stop)`. Exit signal: < 1.0. Color bands: 🟢 ≥ 1.0, 🟡 ≥ 0.5.

**Exit Milestones & Regime:** Milestones computed in `profit_taking.compute_exit_milestones()`; regime in `profit_taking.enrich_regime()`/`classify_regime()` (step 4 of `get_dashboard_df`). TP and milestones are entry-anchored and use the inception ATR (R-multiple) for both stop types; the live trailing ATR sets only the stop. Full thresholds and trim guidance in `docs/TECHNICAL_DOCS.md` §5.

**Capital-Efficiency Flag (Dead Money):** `Position.is_stale` (set in `calculate_financial_metrics`) flags a holding older than `STALE_MIN_AGE_DAYS` whose price-only `aagr` is below `CAPITAL_HURDLE_PCT`. Orthogonal to the exit ladder; income assets (`AssetRegistry.is_income_asset`) are excluded. Surfaced in the `risk_workspace.py` PLAN panel.

### Presentation Layer (Textual UIs)

All UIs are Textual apps in `ui/`, launched from `main.py`. They are display-only and do not write to the database except `ui/risk_workspace.py`, which persists `risk_profiles` edits via command syntax (e.g., `15 T P:L` = 15% stop, Trailing, Large preset). Scale-In has been removed; entry type is always SINGLE.

### Session Protocol

When asked to "wrap it up":
1. `git diff --stat` / `git log --oneline` — identify all changes since last session log.
2. Create `docs/sessions/YYYY-MM-DD_Brief_Description.md` — sections: Objectives, Technical Changes, Logic & Decisions, Verification, Next Steps.
3. Update this file (CLAUDE.md) for architectural changes only — module additions, schema changes, new invariants. No feature detail or trim percentages.
4. Update `docs/TECHNICAL_DOCS.md` for any user-facing feature additions or changes.
5. Commit session log + any doc changes.
6. Remind user to run backup (`uv run python sync_config.py`).

Use `/wrap-up` to trigger the session wrap-up command.
