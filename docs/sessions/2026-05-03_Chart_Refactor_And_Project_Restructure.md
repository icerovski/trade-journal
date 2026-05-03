# 2026-05-03 — Chart Feature, VOO DMA Fix, and Project Restructure

## Objectives
- Add a price + 200 DMA chart accessible from all three workspaces
- Investigate and fix the VOO regime calculation returning blank 200 DMA
- Reduce technical debt: remove Gemini artefacts, trim sync_config, archive old sessions, restructure file layout

## Technical Changes

**Chart feature (`ui/chart_utils.py`, `ui/chart_worker.py`)**
- Added `G` key binding to `ui/dashboard.py`, `ui/risk_workspace.py`, `ui/watch_list_workspace.py`
- `launch_price_chart(display_ticker, conid, yf_ticker)` spawns `chart_worker.py` as an isolated subprocess with `CREATE_NO_WINDOW` — avoids Tk threading restrictions on Python 3.14/Windows
- `chart_worker.py` adds repo root to `sys.path` so `services/` and `core/` imports resolve correctly from `ui/`
- Replaced initial threading approach (caused `RuntimeError: main thread is not in main loop` after 3–4 presses) with subprocess isolation
- Added `matplotlib` dependency to `pyproject.toml`

**VOO 200 DMA fix (`services/price_service.py`, `prices.db`)**
- Root cause: single NULL `close` value on 2026-03-26 in `prices_daily` for conid `136155102` — poisoned all rolling windows ≥50 days
- Fix: deleted the NULL row, re-fetched correct price (593.05) from yfinance, inserted it
- Added `df.dropna(subset=['Close'])` guard in `get_trend_analysis()` — permanent protection against future stray NULLs
- Added `logger.info` for resolved yf_ticker in `enrich_regime()` and `logger.warning` with full traceback for failures — silent `except: pass` replaced

**`sync_config.py` trimmed**
- Removed `GEMINI.md` and `~/.gemini/GEMINI.md` sync entries — only `.env` backed up now
- Removed unused `os` import and `GLOBAL_VAULT` variable

**Project restructure**
- Created `ui/` package: moved `dashboard.py`, `risk_workspace.py`, `watch_list_workspace.py`, `kids_fund_dashboard.py`, `portfolio_risk.py`, `chart_utils.py`, `chart_worker.py`
- Deleted backwards-compat shims `core/risk_engine.py` and `core/portfolio_analytics.py`; redirected all 4 callers to `core/stop_loss.py` and `core/sizing.py` directly
- Removed dead `risk` dependency injection from `PortfolioManager.__init__` (unused `RiskEngine()` instantiation)
- Deleted empty `trade_journal.db` placeholder (0 bytes) from repo root
- Moved `GEMINI.md` → `docs/GEMINI.md`; removed duplicate `doc-manager.skill` from root
- Deleted `course/` (Python learning exercises, not production code) and `tasks/lessons.md`
- Archived 46 of 56 session logs to `OneDrive/archived_sessions/`; kept last 10 in repo
- Deleted `.gemini/` folder — Gemini CLI no longer used
- Added `.ruff_cache/` to `.gitignore`, deleted stale cache

**Claude command**
- Created `.claude/commands/wrap-up.md` — combined Gemini doc-manager and session-logger skills, updated GEMINI.md references to CLAUDE.md

## Logic & Decisions

- **Subprocess over threading for charts:** Python 3.14 on Windows strictly enforces that all Tk operations occur on the thread that created the Tk root. Multiple threads each calling `plt.show()` caused `RuntimeError` after 3–4 presses. A subprocess gives each chart its own main thread — completely isolated from Textual's event loop.
- **`dropna` guard in `get_trend_analysis`:** A single NULL in a 2,500-row price series silently breaks all rolling windows ≥50 days. Defensive `dropna` before rolling computation is the right invariant — sparse NULLs from failed fetches should never propagate to derived metrics.
- **`ui/` package boundary:** All Textual app entry points and rendering utilities moved to `ui/`. `core/` and `services/` remain pure business logic and integrations with no UI dependency — the boundary is now enforced by import structure.
- **Shim removal:** `core/risk_engine.py` and `core/portfolio_analytics.py` were one-line re-exports with no logic. With all callers updated, keeping them added confusion about where the real implementations lived.

## Verification

- 42/42 tests passing after restructure (`uv run python -m pytest tests/ -v`)
- All module imports verified clean after each change
- VOO DMA confirmed: DMA200 = 615.51, direction UP, 99 consecutive days → TREND regime
- Chart subprocess confirmed working (no Tk errors, multiple G keypresses stable)

## Next Steps

- Consider moving `config.py`, `constants.py`, `logger.py`, `models.py`, `db.py`, `data_loader.py` out of root into a `core/` or `config/` sub-grouping (lower priority — root is cleaner now but still has 8 Python modules)
- Investigate other tickers that may have NULL close values in `prices_daily`
- Consider a bulk NULL audit query on `prices.db` as a one-off maintenance task
