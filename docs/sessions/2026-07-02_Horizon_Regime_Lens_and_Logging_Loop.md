# 2026-07-02 — Horizon-Aware Regime Lens & §7 Logging Loop

## Objectives

Two independent additive builds, both opt-in and default-off:

1. **F1 documentation audit** — bring the Strategy Lab and Operating Rhythm help tabs up to date with every command token the software actually accepts, and add a missing "how to run the system" guide (cadence, opening/monitoring/closing walkthroughs).
2. **Horizon-aware regime lens** — the trim-driving trend regime was hardcoded to the 200-DMA for every position regardless of the trade's actual horizon. Re-derive the regime lens from the stop's own volatility horizon instead.
3. **Entry & Stop System §7 logging loop** — close the last open item: source/theme capture on taken trades, a skipped-source-pick logging path, a benchmark price series, and automated realized-R/MAE/MFE backfill. The `trade_log` schema and expectancy report (menu 9) already existed; only 6 fields auto-wrote on a classified commit.

## Technical Changes

### Documentation (F1 help)

- `docs/guides/Strategy_Lab_Syntax.md` — added the `C:`/`X:`/`G:` trade-character section (classification, exit shape, gap-aware sizing), the `M` settings modal section (presets, action threshold, entry gates G1–G8), an expanded Controls key-binding table, and — later in the session — the `SRC:`/`THM:` journal tokens.
- `docs/guides/Operating_Rhythm.md` (new) — screen-to-question map, daily/weekly/monthly cadence, and full open/monitor/close position walkthroughs. Registered as the first F1 tab in `services/ui_components.py:16` (`HELP_FILES`).
- `docs/guides/Exit_Strategy.md` — documented the horizon regime lens alongside the existing 200-DMA table.
- `docs/TECHNICAL_DOCS.md` §5, §10, §11 — regime lens mechanics, `SRC:`/`THM:` syntax, and the automated backfill section.

### Horizon-aware regime lens (default-off — `regime_lens` setting)

- `constants.py` — `REGIME_LENS_BANDS`: `(max risk-unit/dailyATR ratio, DMA window, TREND days, NORMAL days)` rows — `≤1.6 → 50-DMA/10d/5d`, `≤3.4 → 100-DMA/15d/7d`, else 200-DMA/21d/10d (unchanged).
- `services/price_service.py` — `_series_trend()` extracted (generic consecutive-direction-day counter, was inline 200-DMA-only logic); `_wilder_atr_daily()` added; `get_trend_analysis()` now also returns `dma_trends` (per-window 50/100/200 trend) and `atr14_daily`. `dma200_trend` return shape unchanged.
- `core/profit_taking.py` — `classify_regime()` gained `trend_min_days`/`normal_min_days` kwargs (defaults reproduce today's 21d/10d exactly); new pure `select_regime_lens(risk_unit, atr_daily)` picks the DMA window from `REGIME_LENS_BANDS`; `enrich_regime(positions, mapper, lens_mode)` — `lens_mode="horizon"` selects the lens per position from `inception_atr`, gates TREND on price vs. the *lens* DMA (not always the 200), and names a non-default lens in the display string (`BUY (12d, DMA50)`).
- `core/portfolio_manager.py` — reads the `regime_lens` setting and passes `lens_mode` through to `enrich_regime`.
- `models.py` — `Position.regime_lens: int = 200` carries the window used.
- `ui/risk_workspace.py` — "Regime lens (default/horizon)" row in the `M` settings modal (`PresetMatrixScreen`), validated and persisted alongside `gates_mode`.
- `tests/test_regime_lens.py` (new) — band selection, edge inclusivity, missing-data fallback, and a default-arguments guard proving `classify_regime()` unchanged.

### §7 logging loop

- `ui/risk_workspace.py` — new `SRC:`/`THM:` command tokens (parsed before the F/T check since `THM` contains a `T`); carried into the draft dict. `_log_classification()` renamed in spirit (still same function) to fire on **either** `C:` or `SRC:` (previously classification-only), and now also computes/stores `r1 = entry − stop` — the unit the backfill needs later.
- `ui/watch_list_workspace.py` — new `LogSkippedPickScreen` modal + `L` binding (`action_log_skipped`): writes a `SKIPPED` `trade_log` row (ticker, source, theme required/optional, today's date, best-available price via analysis cache → `PriceService.latest_close`). Works for tickers not currently on the watch list.
- `db.py` — new settings defaults `regime_lens` (`default`) and `benchmark_ticker` (`SPY`); new `get_trades_for_conid(conid)` read helper (chronological raw trade rows, dict form) for the backfill's ledger replay.
- `core/outcome_backfill.py` (new) — pure core + thin I/O runner:
  - `find_close_after(trades, after_date)` — replays raw trades chronologically mirroring `LedgerEngine._apply_trade` sign conventions (abs qty, side-driven, `OPENING_BALANCE` resets the lot, `SPLIT` is a signed delta); returns `(close_date, qty-weighted exit price)` for the first zero-crossing strictly after the log date, or `None` if still open. A split landing inside the measurement window aborts (`None`) rather than computing on mismatched pre/post-split prices.
  - `compute_excursions(ohlc_df, entry, r1)` — MAE/MFE in R units from cached daily bars, floored at 0.
  - `window_return(close_df, start, end)` — simple close-to-close return over a window (nearest available dates).
  - `run_backfill()` — for TAKEN rows with `realized_r is None`: resolves the close, computes `realized_r`, `mae_r`, `mfe_r`, `result_vs_benchmark`; for SKIPPED rows: refreshes `result_vs_benchmark` to date on every run. Returns a `{closed, skipped, open, unresolved}` summary. `realized_return_base` intentionally left `NULL` (no FX-at-exit source recorded).
- `main.py` — `handle_expectancy()` (menu option 9) now runs `run_backfill()` before rendering the report and prints the summary; failures are caught and logged, report still renders.
- `tests/test_outcome_backfill.py` (new) — `find_close_after` (simple round trip, still-open, qty-weighted multi-fill exit, prior-lot exclusion, split-in-window abort, TRANSFER_OUT close, empty ledger), `compute_excursions` (R-unit math, floor at zero, missing-data, case-insensitive columns), `window_return` (windowed, open-ended, out-of-range, empty).

## Logic & Decisions

**Regime lens keys off the stop, not the classification tag.** Initial framing was "TECHNICAL trades should use a shorter DMA than THESIS trades." User corrected this: classification is risk-led, not time-led — a leveraged ETF (SOXL-style, held weeks) gets a tight stop near the daily ATR; a low-vol conviction thesis (DXJF-style, held 6–9 months) gets a stop many ATRs wide. **Time is a function of risk**, and the stop already encodes it. This mirrors the FIXED-stop inception-ATR snapping already done for the milestone ladder (§ prior session) — same principle, now applied to the regime. `C:`/`X:` remain carried-only; nothing new branches on the classification tag.

**Band edges at √5 and √21.** A stop distance of 1 daily-ATR unit is "tactical"; √5 ≈ 2.24 daily-ATR units approximates a stop sized off the weekly ATR (weekly variance ≈ 5× daily under a random-walk assumption); √21 ≈ 4.58 approximates a monthly-ATR stop. Bands: `≤1.6→50-DMA`, `≤3.4→100-DMA`, else 200-DMA. Confirmation-day thresholds scale roughly `window/10` (200→21d becomes 50→10d, 100→15d) — a hypothesis, flagged as a §8-governance tunable in `constants.py`, not a law.

**Missing data always falls back to the structural 200-DMA lens** — never a crash, never an unexplained regime. This preserves the default-off contract: `lens_mode="default"` (or any missing `inception_atr`/`atr14_daily`) reproduces today's classification bit-for-bit.

**`_log_classification` fires on `SRC:` OR `C:`, not `C:` alone.** The original Phase-3 gate was classification-only. Widening it to include source-tagged (but unclassified) commits was necessary — otherwise a `SRC:ZACKS` commit with no `C:` tag would silently write nothing, breaking the funnel promise that *every* taken trade from a tracked source gets logged.

**`find_close_after` deliberately excludes prior lots.** A round-trip that closed *before* the log's entry date must not be misread as this trade's exit — reset-on-zero means each lot is independent, and the replay walks forward from zero every time qty crosses back through the threshold, only recording sells that occur strictly after `after_date`.

**Split-in-window aborts rather than approximates.** A stock split between entry and exit invalidates the raw price comparison (a pre-split $50 entry vs. a post-split $25 low is not a real 50% drawdown). Rather than attempt a split-adjustment, `find_close_after` returns `None` for that row — it stays `unresolved` and visible in the backfill summary rather than silently producing a wrong R.

**`realized_return_base` is not backfilled.** No FX-at-exit rate is recorded anywhere in the ledger; using today's live FX rate to compute a historical base-currency return would fabricate data that could pollute the §7 currency review. Left `NULL` and flagged in memory/CLAUDE.md as a follow-up needing an FX-at-exit source.

## Verification

- `uv run python -m pytest tests/ -q` — **293 passed** (265 baseline + 28 new: 12 in `tests/test_regime_lens.py`, 16 in `tests/test_outcome_backfill.py`), including `tests/test_characterization.py` (golden master over `scan_ticker`/sizing/`classify_regime`/exit ladder) — confirms all new defaults reproduce prior behaviour exactly.
- Smoke import check: `ui.watch_list_workspace`, `ui.risk_workspace`, `core.outcome_backfill`, `main` all import cleanly.
- No manual UI walkthrough performed this session (backend/logic + docs only; no frontend rendering change beyond new modal/key binding).

## Next Steps

- Manually verify the `L` key skipped-pick modal and `M` modal's new Regime lens field render/behave correctly in the live Textual UI (not yet manually clicked through).
- Consider an FX-at-exit capture mechanism (e.g. store `fx_rate` on the closing `SELL`/`TRANSFER_OUT` trade row) to unlock `realized_return_base` backfill.
- Accumulate ~20–30 logged picks per source before the §0a funnel verdict (source vs. benchmark) becomes statistically meaningful.
- Regime-lens band edges (`REGIME_LENS_BANDS`) and confirmation-day scaling are hypotheses — revisit per §8 governance once enough horizon-lens trades have closed to validate against `mae_r`/stop hit-rate.
