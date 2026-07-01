# Session — 2026-07-01: Entry & Stop System (Phases 0–8)

## Objectives

Implement `docs/ClaudeCode_Implementation_Instructions.md` — the phased build-out of the
**Entry & Stop Selection System** (`docs/guides/Entry_and_Stop_System.md`) and the
**3-to-6-month horizon calibration** (`docs/guides/Horizon_Calibration_3to6mo.md`). Governing
constraint: **break nothing that works.** Every feature is additive and default-off; with all
defaults, the app must be behaviourally identical to the starting commit. One phase per
review gate.

## Technical Changes

### Phase 0 — Safety net (no functional change)
- **`tests/test_characterization.py`** + **`tests/snapshots/phase0_golden.json`** — a golden-master
  test pinning the core decision paths: `zone_scan.scan_ticker` (all 3 regimes/stop-sources),
  `sizing.compute_position_size` (risk/exposure/option/bond grids), `profit_taking.classify_regime`
  (full truth table), and the exit ladder (`stop_loss.calculate_position_risk` FIXED/TRAILING/
  TP-override + `compute_exit_milestones` stages). No network, no DB writes (HWM monkeypatched).
  Bootstraps on first run, compares thereafter; must stay byte-identical through every later phase.

### Phase 1 — Config extraction (behaviour unchanged)
- **`constants.py`** — extracted the remaining hardcoded literals from the core paths at their
  current values: `DMA_LONG/SHORT_WINDOW`, `TRADING_DAYS_PER_MONTH`, `SCANNER_ATR_WINDOW`,
  `ATR_FALLBACK_MULT`, `REGIME_TREND/NORMAL_MIN_DAYS`, `MILESTONE_M1/M2_MULT`, `ATR_DISCOVERY_INTERVALS`.
- **`core/zone_scan.py`, `core/profit_taking.py`, `core/stop_loss.py`** — literal → reference swaps only.

### Phase 2 — Trade-log schema (additive)
- **`core/trade_log.py`** (new) — `TradeLogEntry` dataclass + `COLUMN_TYPES` as the single schema
  source. Fields cover all of §7 (source, tag, regime, archetype, stop_source, geometry, realized R,
  base-ccy return, vs-benchmark, MAE/MFE) plus `status ∈ {TAKEN, SKIPPED}` for skipped source picks.
- **`db.py`** — `trade_log` table built from `COLUMN_TYPES`; per-column `ALTER` loop = additive
  migration. `add_trade_log_entry` / `get_trade_log_entries` / `update_trade_log_entry`.

### Phase 3 — THESIS/TECHNICAL classification (carry-only)
- **`db.py`** — `risk_profiles.classification` column; `set_position_risk(classification=_KEEP)` write-many.
- **`models.py`** — `RiskProfile.classification`, `Position.classification`.
- **`core/stop_loss.py`** — carries `profile.classification → position.classification`. No exit branch.
- **`ui/risk_workspace.py`** — `C:TH/TE/-` command token (pure `parse_classification`), header chip,
  commit-time `trade_log` write when tagged (`_log_classification`).

### Phase 4 — Entry gates G1–G8 (advisory-first)
- **`core/gates.py`** (new) — pure `ProposedTrade` → `GateResult` (PASS/FAIL/NA + reason) for all
  eight gates incl. G7 theme heat and G8 base-currency; `evaluate_gates` / `gates_summary`.
- **`constants.py`** — gate thresholds (`GATE_G1..G7`).
- **`db.py`** — `gates_mode` setting (default `off`).
- **`ui/risk_workspace.py`** — `_gate_check` on commit (both `Ctrl+J` and Save-All); `off`/`advisory`/
  `blocking`; toggle added to the preset/settings modal.

### Phase 5 — Expectancy analytics (read-only)
- **`core/expectancy.py`** (new) — per-archetype `w / W̄ / L̄ / E[R]`, overall, source-vs-benchmark
  funnel, base-ccy totals; empty-log safe. **`constants.py`** `EXPECTANCY_THRESHOLD_R = 0.20`.
- **`ui/expectancy_report.py`** (new) + **`main.py`** menu option **9** (rich console, read-only).

### Phase 6 — Gap-aware sizing (opt-in)
- **`core/sizing.py`** — `gap_effective_stop` + `compute_position_size_gap` (risks against
  `min(stop, gap_price)` = `max(R₁, R_gap)`; `gap_price=None` ≡ default sizer).
- **`ui/risk_workspace.py`** — `G:<price>` token feeds prospect sizing; header chip.

### Phase 7 — Exit shapes (extend the ladder)
- **`core/exit_shapes.py`** (new) — `LADDER` (default) / `HARD` / `RUNNER` / `THESIS`; `normalize_shape`,
  `suppresses_price_target`, `is_hard_target`, `shape_label`.
- **`db.py`** — `risk_profiles.exit_shape`; `set_position_risk(exit_shape=_KEEP)`.
- **`models.py`** — `RiskProfile.exit_shape`, `Position.exit_shape`.
- **`core/stop_loss.py`** — carries the shape; THESIS drops `tp_price` (stop governs the exit).
- **`ui/risk_workspace.py`** — `_exit_recommendation(exit_shape=…)`: HARD → full exit at TP; `X:H/R/T/-`
  token; both call sites (table + panel) pass the shape; header chip.

### Phase 8 — Horizon calibration profile (non-default)
- **`core/calibration.py`** (new) — `CalibrationProfile`; `DEFAULT_CALIBRATION` (mirrors today's daily
  constants) and `POSITION_3TO6MO` (weekly lens, longer ATR, wider buffers/bands, 30-week-MA anchor,
  MOMENTUM override); `get_calibration`.
- **`constants.py`** — `CAL_3TO6MO_*` band constants.
- **`core/zone_scan.py`** — `scan_ticker(calibration=None)` overrides horizon knobs; the MOMENTUM branch
  is gated on `use_micro_momentum_stop`, so the 3–6mo lens falls back to weekly value anchors.
- **`db.py`** — `calibration_profile` setting (default `default`); **`ui/zone_scan_workspace.py`** loads and
  passes it through `build_zone_report`.

## Logic & Decisions

- **Golden master is the contract.** Every phase re-ran `test_characterization.py`; it stayed
  byte-identical from Phase 0 to Phase 8, which is the mechanical proof that "defaults reproduce
  today's behaviour." Any drift would fail loudly.
- **`constants.py`, not a new `entry_config.py`, for Phase 1.** The app already has one config
  location; a second would defeat "one config location" and force app-wide import churn. The richer
  profile structure was introduced in Phase 8 (`core/calibration.py`) where it is actually needed.
- **`_KEEP` sentinel** reused for `classification` and `exit_shape` write-many semantics (matches the
  existing `tp_atr_mult` pattern): pass a value to set, `""`/`None` to clear, omit to leave untouched.
- **NA is first-class in the gates.** A gate with missing inputs returns NA and never blocks; only an
  explicit FAIL blocks in `blocking` mode, so partial context degrades gracefully.
- **THESIS exit = drop the target, not add logic.** Setting `tp_price=None` routes every downstream
  metric (up_pct, reward_val, rr, exit_stage) to its existing no-target branch — the exit becomes
  stop/thesis only, with no new branching.
- **No time stop, enforced.** No shape or profile carries a time/hold/age field (asserted by test).
  The calibration profile changes the *lens* only ("two roles of time").
- **Gap-aware sizing reuses the dual-constraint sizer** via `effective_stop = min(stop, gap_price)`,
  which is exactly "use the larger of R₁ and R_gap"; the exposure clamp is untouched.
- **3–6mo ATR is a daily-bar approximation.** The scanner works on daily bars, so the doc's long/weekly
  ATR is approximated by a longer daily window (`CAL_3TO6MO_ATR_WINDOW = 60`) rather than faked as true
  weekly resampling — flagged for a later scanner change. The %-bands and 30-week-MA anchor ship as
  advisory profile metadata.
- **Human-judgment items surfaced, not automated** (per the docs' split): source qualification,
  location/trigger/archetype selection, conviction sizing, and `plausible_gap_price` (the `G:` input).

## Verification

- **Full suite: 265 passed** (from 166 at session start; +99 across 8 new test files).
- **Golden master byte-identical** through all phases — no core path moved with defaults unchanged.
- Import smoke-checks passed for `ui.risk_workspace`, `ui.expectancy_report`, `ui.zone_scan_workspace`,
  and `main` after each wiring change.
- Trade-log additive migration proven: a legacy table missing the new columns migrates in place; old
  rows load (new fields NULL) and remain saveable.

## Next Steps

- Commit the 8 phases (messages proposed per-phase during the session; code currently uncommitted).
- Update `docs/TECHNICAL_DOCS.md` / F1 guides for the new commands (`C:` `X:` `G:` tokens, `gates_mode`,
  Expectancy menu 9, calibration profile) — partially done this session (see §10–§11).
- Richer gate wiring: feed `stop_source` / `flagged` / `confluence_count` / earnings / ADV / theme heat
  into the Risk Workspace `ProposedTrade` so G2–G7 evaluate there instead of returning NA.
- True weekly resampling in the scanner for the 3–6mo lens (replace the daily-window ATR approximation).
- Formalise the full §7 logging loop (de-dup commit-time writes; capture skipped picks from the flow).
