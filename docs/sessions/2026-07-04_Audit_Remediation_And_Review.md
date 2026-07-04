# Session Log — 2026-07-04: Audit Remediation & Multi-Agent Review

## Objectives

- Act on the application assessment (`Fable_Application_Assessment_Review.md`, produced earlier the same day): fix both **Must-fix** findings, implement the four accepted **Cut** decisions, and complete the doc-hygiene pass.
- Run `/code-review` at xhigh effort (10 finder angles → verification → sweep) over the uncommitted diff before commit; fix every confirmed finding.

## Technical Changes

### Must-fix #1 — FX-normalized sizing
- `core/sizing.py` — `compute_position_size()` / `compute_position_size_gap()` gained `fx_rate` (asset ccy → NAV ccy, same convention as `audit_position_risk`; degenerate rates — 0 / None / NaN / negative — degrade to 1.0 instead of crashing) and `exposure_price` (pins the exposure leg to a different reference, used by the workspace's current-price exposure semantics). Defaults reproduce prior behaviour exactly.
- `core/zone_scan.py` — `scan_ticker()` / `build_zone_report()` thread `fx_rate`; `ui/zone_scan_workspace.py` passes each position's rate and `nav_ccy`.
- `core/stop_loss.py` — `get_atr_discovery_data()` / `_compute_atr_rows()` gained `fx_rate`; prospect sizing and `pl_pct_nav` convert to base currency (`pl_at_stop` stays in the asset currency by design).
- `ui/risk_workspace.py` — inline sizer deleted, replaced by the shared `compute_position_size_gap(…, exposure_price=cur_p_d)`; `hypo_r` / `modeled_nav_pct` use a finite-positive-guarded fx local.
- **Prospect FX provenance** — new additive `risk_profiles.ccy` column (NULL = legacy → USD assumed). The watch-list add flow records the symbol's real pricing currency via `services/market_data_service.fetch_ticker_currency()` (case-preserving: `GBp` pence ≠ `GBP` pounds). `core/portfolio_manager.resolve_prospect_fx()` is the single resolver: held-book donor (finite, > 0) first → live `fetch_fx_rate` (TTL-cached ~15 min, failures not cached) → logged 1.0 fallback. Minor-unit codes (`GBp`/`GBX`/`ZAc`) resolve via their major unit × 0.01. The ad-hoc Discover flow resolves currency in its worker thread; the phantom is created with an empty ccy placeholder so a guess is never trusted as an answer.

### Must-fix #2 — thin-history ATR guard
- `models.ATRDiscoveryRow.window_shrunk` (additive, default False) — set by `_compute_atr_rows()` whenever history can't fill the timeframe's full ATR window.
- `core/stop_loss.snap_inception_atr()` — the single FIXED-snap rule (excludes shrunken rows); `ui/risk_workspace.py` and `tools/migrate_fixed_inception_atr.py` share it **by identity** (asserted in tests).
- Discovery tables mark shrunken rows with `⚠`; if the exclusion moves the snap to a different timeframe than the nearest displayed one, the workspace notifies (deduped per row — `on_strategy_change` fires per keystroke).
- All-shrunk or no-discovery FIXED commits anchor `R` to `entry − stop` — a `None` draft value previously degraded to `atr_value` in `db.set_position_risk`, i.e. the stop **price**, as the frozen R unit.
- Two previously unguarded snap sites closed: `ui/watch_list_workspace.py` add flow refuses tickers with < 15 daily bars; `tools/reconstruct_inception_risk.py` requires a full ATR window and skips otherwise (also no longer stores a 0.0 ATR / entry-price stop on 2-bar history).

### Cuts (assessment recs 16–19, all accepted)
- **G6 liquidity** → permanent NA stub in `core/gates.py`; `GATE_G6_ADV_FRACTION` and the `adv`/`slippage_*` `ProposedTrade` fields deleted. A test pins that G6 can never block.
- **G7 theme dimension** → `g7_portfolio_heat()` evaluates portfolio heat only; `theme`/`theme_heat_pct` fields deleted.
- **RUNNER** → `X:R` and stored `RUNNER` values normalize to `LADDER` outright (alias parsing kept; the "Scale+runner" chip is gone; `shape_label` no longer has a RUNNER row).
- **TP:$** → the `$`/`K` branch removed from `resolve_tp_mult` (tokens still captured by the regex and rejected with a warning so they can't leak into the quantity parse); the now-vestigial `qty` parameter dropped.

### Doc hygiene & cleanup
- Dead `urgent` key/branches removed from `_exit_recommendation` and consumers; stale "urgent RR-exit" precedence comment fixed.
- `docs/TECHNICAL_DOCS.md` — §1 menu path + FX note + watch-add guard, §5 TP forms + thin-history guard, §6 precedence, §10 shapes/gates deviations, §11 honest calibration status (inert %-bands named as metadata; no UI door).
- `docs/guides/Strategy_Lab_Syntax.md` — `C:` / `X:` / `G:` documented; TP table updated. `Entry_and_Stop_System.md` §4/§5a and `Horizon_Calibration_3to6mo.md` carry implementation-status notes (G6 stub, G7 portfolio-heat only, RUNNER = default).
- `docs/GEMINI.md` deleted; README's broken pointer fixed (full README rewrite queued). `docs/OPEN_ITEMS.md` now carries the remaining review queue (strategic fork + Should-fix/Consider items).

### Review fixes beyond the plan (found by the xhigh sweep against the same-day fix wave)
- `GBp` → `GBP` upper-casing would have made LSE prospect FX wrong by 100× — currency codes are now case-preserved end to end (service, DB, resolver).
- The no-discovery FIXED commit path could still freeze the stop price as R — closed.
- NaN donor rates, per-keystroke toast spam, migrate-tool misdiagnosis on all-shrunk rows, redundant metadata fetch/ccy overwrite for resolved prospects, per-refresh blocking FX fetches — all fixed.

## Logic & Decisions

- **FX convention**: multiply asset-ccy amounts by `fx_rate` to reach the NAV currency; prices stay in the asset currency and only NAV-relative caps convert. All new parameters default to values that keep `tests/test_characterization.py` byte-identical (independently confirmed during review).
- **Currency provenance over guessing**: a prospect has no broker snapshot row, so its currency is captured once from yfinance metadata at add/discover time and persisted — the previous hardcoded `ccy='USD'` made the fx borrow *wrong-currency* for any non-USD name. Legacy NULL rows keep the historical USD assumption.
- **Never freeze a garbage R unit**: shrunken-window ATRs are excluded everywhere (one shared rule, identity-tested), and a missing inception ATR anchors to `entry − stop` (the ladder's own documented fallback) rather than flowing NULL into `db.set_position_risk`, whose NULL→`atr_value` degrade turns a FIXED stop *price* into the R unit.
- **Review process**: the sweep phase caught two severe defects introduced by the same-session fix wave (pence 100×, no-discovery NULL path) — the verify-then-sweep loop is what made same-day remediation safe to commit.
- `settings.local.json`: the review narrowed a broad `PowerShell(git *)` permission to enumerated read-only rules; the user subsequently re-added the wildcard deliberately — user's call, left in place.

## Verification

- Full suite **282 passed** (265 at session start; +9 fx/ATR-guard tests net of the 4 cut-related removals, plus review-fix tests). Golden master unchanged.
- Hand-verified worked example: EUR NAV / USD stock at EUR/USD 1.08 → risk-capped size grows exactly 8% (1000 → 1080 on the reference fixture), reproducing the assessment's 707→764-share example mechanism.
- Pence scaling: `GBp` prospect against EUR NAV resolves to 0.01 × the GBP rate (donor and live paths).
- `/code-review` xhigh: 15 findings filed via ReportFindings, every one `outcome=fixed`; import smoke tests clean on all touched modules.

## Next Steps

- **Strategic fork** (top of OPEN_ITEMS): finish gates/calibration wiring (scanner→workspace handoff, calibration in the `M` modal, mode banner, §7 journal capture) vs leave gates off. The Should-fix/Consider queue hangs on this decision.
- `Fable_Application_Assessment_Brief.md` / `_Review.md` remain untracked at repo root — decide: commit, or archive to the OneDrive vault.
- README rewrite (Gemini-era staleness) — queued in OPEN_ITEMS.
- Legacy WATCH rows carry NULL ccy (USD assumed) — backfill only if a non-USD name is ever watched.
