# Session — 2026-06-04 · Exit Strategy Review & Hardening

## Objectives

Review the exit-strategy layer (`profit_taking`, `stop_loss`, the `risk_workspace` PLAN
panel) for code-quality and finance/risk-management soundness, then act on the findings:
fix correctness bugs, implement the approved strategy refinements, add test coverage, and
update all documentation including the F1 in-app help.

## Technical Changes

### Correctness fixes
- **TRAILING TP anchoring** (`core/stop_loss.py`) — TP was anchored to the ratcheted stop
  (`final_sl + 3×ATR`), which at inception equals M2 (`stop = entry − ATR ⇒ stop+3·ATR =
  entry+2·ATR`). Now entry-anchored for both stop types, giving a uniform ladder
  (M1/M2/TP = entry + 1/2/3×ATR). Constant comment in `constants.py` updated.
- **Divergent RR display** (`ui/risk_workspace.py`) — the audit panel computed efficiency
  from `stop + 3×ATR` while the exit-stage floor used `pos.tp_price` (`entry + 3×ATR`),
  showing two different RR numbers. Both now use `active_entry + TP_ATR_MULTIPLE×ATR`.
- **Fractional over-trim** (`ui/risk_workspace.py`) — `max(1, int(qty*pct))` could suggest
  selling 1 whole unit of a sub-1-unit lot and never clamped to holdings. Now rounds,
  clamps to holdings, and preserves fractional figures for bond/option lots.
- **Silent no-op** (`core/profit_taking.py`) — `compute_exit_milestones` now logs a debug
  line when `exit_stage` cannot be set (missing price/TP) instead of silently returning.
- **Console logging crash** (`logger.py`) — the console `StreamHandler` inherited the
  legacy Windows code page (cp1251), so any non-encodable character (the 🚀 milestone
  marker, em-dashes, accented ticker names) raised `UnicodeEncodeError` in `emit`. Added
  `_ensure_utf8_console()` to reconfigure stdout/stderr to UTF-8 with `backslashreplace`,
  degrading unencodable characters instead of crashing. The file handler was already UTF-8.

### Post-review fixes (live-data findings)
- **Milestone/TP drift on TRAILING stops** (`core/stop_loss.py`) — milestones and TP for
  trailing stops used the *live* ATR, so as volatility expanded the ladder drifted away
  from price (AVGO: live ATR 88 vs inception 57 pushed M1 to entry+88 ≈ 449, mislabelling
  a +33% winner as M1). Now both stop types anchor the ladder/TP to the **inception ATR**
  (the original R unit); the live ATR governs only the stop. The panel efficiency RR uses
  the same R unit so it stays consistent with `pos.rr_ratio`. AVGO now reads M2/TREND.
- **AAGR display** (`ui/risk_workspace.py`) — relabelled the PLAN metric to `Return: ±x%
  total · ±y%/yr · Nd`. Total return (always meaningful) leads; the annualised figure is
  tagged `prelim` and dimmed below the 180-day horizon, where it is wild extrapolation
  (a 2-month winner annualises to absurd %). Line now shows for any real holding (qty>0).

### Strategy refinements (approved via Q&A)
- **Q1 — No M2 trim in TREND** — `TRIM_MATRIX[('M2','TREND')]` → `0.0` (hold). A `0.0`
  fraction renders a "Hold — no trim" directive; the trailing stop runs the winner and
  profit is banked at TP. Other cells unchanged.
- **Q2 — Capital-efficiency / dead-money flag** — `Position.is_stale` set in
  `calculate_financial_metrics`: `age_days ≥ STALE_MIN_AGE_DAYS (180)` AND
  `aagr < CAPITAL_HURDLE_PCT (8%)`. Surfaced in the PLAN panel as a `Capital: ±x% AAGR
  over Nd` metric plus a `⏳ STALE` nudge (suppressed on breach). Price-only AAGR; income
  assets excluded via new `AssetRegistry.is_income_asset`.
- **Q3 — Prioritize exit in RANGING** — when the RR<1.0 efficiency floor fires in RANGING,
  the only directive is full exit (tighten-and-hold withheld). TREND/NORMAL keep both.
- **Q4 — Regime reversal hysteresis** — extracted the pure `classify_regime()` function;
  an unconfirmed DMA reversal (down-run < `REGIME_REVERSAL_CONFIRM_DAYS = 3`) holds the
  regime at NORMAL instead of crashing to RANGING. Added `Position.regime_dma_direction`
  so the UI verdict stays accurate.

### Tests
- New `tests/test_profit_taking.py` (33 tests): regime classification + hysteresis table,
  milestone ladder anchoring and stage classification, entry-anchored TP regression for
  both stop types (DB write monkeypatched), TRIM_MATRIX cells, and the stale flag incl.
  income-asset exclusion.

### Documentation
- `docs/TECHNICAL_DOCS.md` §5 — corrected TP anchoring/trigger, M2-in-TREND hold,
  hysteresis, the capital-efficiency flag, income exclusion, and stale module references.
- `services/ui_components.py` — F1 help "Exit Strategy" tab rewritten end-to-end (strategy
  overview, regime + hysteresis, uniform ladder, regime-aware efficiency floor, dead-money
  section, dashboard legend); fixed the trailing-TP line in the "Strategy Lab" tab.
- `CLAUDE.md` — updated `profit_taking` module note and the Risk Metrics section.

## Logic & Decisions

- TP entry-anchoring chosen over stop-anchoring because milestone semantics are inherently
  entry-relative ("earned N ATRs from entry"); trend-based TP extension remains a manual
  TP-stage action, not an automatic moving target.
- Hysteresis implemented as a stateless reversal-confirmation buffer, not asymmetric
  day-count thresholds: the consecutive-day count resets to ~1 on reversal, so a "drop at
  <18d" band would never fire — the real whipsaw is the single-reversal-day jump.
- Dead-money flag kept price-only per decision, but bonds/bills excluded to avoid false
  positives where coupon dominates total return.

## Verification

- `uv run python -m pytest tests/ -q` → **75 passed** (42 existing + 33 new).
- Regime hysteresis decision table and stale-flag boundaries verified inline.
- Logger fix confirmed: `log_system_milestone('… 🚀 — em-dash, café')` now logs cleanly
  with no `UnicodeEncodeError`.

## Next Steps

- Optional: extend AAGR to total-return (dividends/coupons) and lift the bond exclusion.
- Optional: surface the STALE flag on the main dashboard grid (currently PLAN-panel only).
