# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (requires uv)
uv sync

# Run the application
python main.py

# Run all tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_ledger_engine.py -v

# Run a specific test
python -m pytest tests/test_ledger_engine.py::TestLedgerEngine::test_reset_on_zero -v
```

No linting configuration is set up; no ruff/flake8/mypy config exists.

## Architecture

### Three-Tier Storage (Never Mix)

| Layer | Location | Contents |
|---|---|---|
| Code repo | `C:\repos\trade-journal` | Pure logic, no secrets |
| Config vault | OneDrive `Documents\Logos\.repos\trade-journal` | `.env`, `GEMINI.md`, ticker mappings |
| Data hub | OneDrive `Accounts\HTC_EOOD\TradeJournalData` | `trade_journal.db`, `prices.db`, CSVs, logs |

`DB_PATH`, `PRICES_DB_PATH`, and all data directories resolve from `DATA_PATH` in `.env`. On startup, `sync_config.smart_sync()` syncs `.env` and `GEMINI.md` from OneDrive. On exit, it backs them up.

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
                                              core/portfolio_manager.py (e
                                              nrichment pipeline)
                                           ┌──────────────┬──────────────┬──────────────┐
                                      dashboard.py  risk_workspace.py  watch_list_workspace.py  kids_fund_dashboard.py
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
- **`core/risk_engine.py`** — `audit_position_risk()` returns GREEN/YELLOW/RED with budget remnants. `calculate_pilot_entry()` computes the 3-stage scale-in roadmap.
- **`services/ibkr_parser.py`** — CSV interpretation. External ID fingerprint = `TransactionID-AccountID-Side` for de-duplication. Updates `ticker_info` (Asset Master) during ingestion.
- **`services/ticker_mapper.py`** — IBKR → Yahoo Finance symbol resolution. Priority: DB conid lookup → YF ISIN search → heuristics (exchange suffixes `.DE`, `.L`, `.AS`).

### Database Schema (SQLite — `trade_journal.db`)

- **`trades`** — Activity ledger. `side` ∈ {BUY, SELL, TRANSFER_IN, TRANSFER_OUT, SPLIT, OPENING_BALANCE, IBKR_CONFIRMATION}. `external_id` is the de-duplication fingerprint (UNIQUE).
- **`risk_profiles`** — Risk settings per conid. `status` ∈ {ACTIVE, WATCH, CLOSED}. Unique index on `(conid, status='ACTIVE')` and `(conid, status='WATCH')`.
- **`ticker_info`** — Asset Master keyed by `conid`. Populated by the parser; the resolver looks here first.
- **`kids_config`** — Private wealth glide path beneficiary config (manual).

Secondary database **`prices.db`** holds `prices_daily (conid, date PK)` for OHLCV cache.

### Presentation Layer (Textual UIs)

All UIs are Textual apps launched from `main.py`. They are display-only and do not write to the database except `risk_workspace.py`, which persists `risk_profiles` edits via a command syntax (e.g., `15 T S 0.5` = 15% stop, Trailing stop type, Scale-In entry, 0.5× ATR steps).

### `GEMINI.md`

`GEMINI.md` in the repo root is a 11 KB persistent technical manifesto that is synced to/from OneDrive. It is project documentation, not AI-specific. Do not delete or truncate it.
