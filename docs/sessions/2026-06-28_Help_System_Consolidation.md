# Session — 2026-06-28: Help System Consolidation & Doc-Code Reconciliation

## Objectives

1. Add hover value readout to the price chart (menu 2 → `G`).
2. Produce a single canonical home for all indicator/metric definitions.
3. Write a detailed, scenario-based stop-placement walkthrough.
4. Audit every guide against current code; fix drift.
5. Resolve the architectural cause of the drift: in-app F1 help was hardcoded Python
   strings that could not be kept in sync mechanically.

## Technical Changes

### Chart hover (`ui/chart_worker.py`)
- Added `_attach_hover(fig, ax, close, dma200)`: a snapping crosshair + tooltip wired to
  `motion_notify_event`. Reports date / Price / 200 DMA at the nearest trading day; `200 DMA`
  degrades to `n/a` for the first 199 bars. Tooltip flips to the left half (`set_ha`,
  `set_position`) past 60% width so it never spills off the right edge. Pure matplotlib — no
  new dependency.

### Help system — single source of truth (the architectural change)
- **`services/ui_components.py`** — `HelpScreen` refactored from ~330 lines of hardcoded Rich
  markup to a `HELP_FILES` table that renders `docs/guides/*.md` + `TECHNICAL_DOCS.md` via the
  Textual `Markdown` widget. Paths resolve from `_ROOT` (repo root via `Path(__file__)`), not
  CWD. The `.md` files are now the sole source; F1 updates automatically when a guide is edited.
- **New `docs/guides/Indicator_Glossary.md`** — canonical definitions: ATR family (inception vs
  trailing), Volume Profile (POC/VAH/VAL/HVN/naked POC), AVWAP, DMAs, R/R%/HCM, RR, confluence,
  both regime systems, the four momentum micro-anchors, exit ladder, STALE/AAGR, presets, table
  icons, plus a `constants.py` appendix. Constant values verified live against source.
- **New `docs/guides/Stop_Placement_Playbook.md`** — scanner decision tree + Scenarios A–D, with
  the AVGO case (MOMENTUM regime, price on the 14-day low → no micro support → −20% VAL fallback
  is an artifact, anchor to 200-DMA instead) worked end-to-end with real numbers.
- **New `docs/guides/Strategy_Lab_Syntax.md`** — converted from the F1 "Strategy Lab" string.
- **New `docs/guides/Exit_Strategy.md`** — converted from the F1 "Exit Strategy" string.
- **`docs/guides/Zone_Scanner_Guide.md`** — added cross-links to the glossary/playbook as canonical.
- **`docs/TECHNICAL_DOCS.md` §1** — documented the dedicated watch-add path (menu 6 → `a`); reframed
  the Risk Workspace "Discover" field as ATR/risk research.

### Doc-code reconciliation (removed-feature still live in code)
- **`ui/dashboard.py`** — deleted the M2/TP `0 < rr < 1.0` efficiency-floor override block (and the
  now-unused `rr`/`cur_p` locals) in `_exit_milestones_panel`; the legend's `⚠ RR<1 — exit` line
  replaced with an "RR informational" note. Corrected a separate stale legend value: M2·TREND said
  "sell 15%" but `TRIM_MATRIX[('M2','TREND')]` is `0.0` (hold).
- **`core/profit_taking.py`** — `TRIM_MATRIX[('TP','NORMAL')]` rationale no longer states the
  efficiency floor "overrides… exit entirely".
- **`ui/risk_workspace.py:61`** — matching TP·NORMAL description softened off the RR>1.0 condition.
- **`CLAUDE.md`** — ATR "Quarterly(8)" → "Quarterly(12)" (`stop_loss.py:261`); "SMA baseline" →
  "EWM `com=window-1`, SMA-seeded"; RR bands "🟢 ≥ 1.0, 🟡 ≥ 0.5" → "🟢 ≥ 2.0, 🟡 ≥ 1.0, 🔴 < 1.0"
  (`risk_workspace.py:1001`).

## Logic & Decisions

- **Why files over strings.** The F1 help drifted (efficiency-floor copy, stale preset table, old
  watch-add flow) precisely because it lived as Python string literals divorced from the docs.
  Making `docs/guides/*.md` the single source — rendered both as files and in F1 — removes the
  divergence by construction. Chosen over patching the strings in place (which preserves the drift).
- **Efficiency floor was removed in logic but not everywhere in UI.** Commit `5b2f9ff` dropped the
  sub-1.0 RR exit floor; `profit_taking.py`/`risk_workspace.py` already treat RR as informational,
  but `dashboard.py` (menu 3) still actively rendered an "Exit all" directive. The two surfaces now
  agree: exits are driven by the stop and a RANGING regime, never by RR.
- **RR bands corrected to code, not to CLAUDE.md.** Three different RR bands existed across F1 string
  (>3.0/1.0–3.0), CLAUDE.md (≥1.0/≥0.5), and code (≥2.0/≥1.0). Code (`risk_workspace.py:1001`) is
  authoritative; docs were aligned to it.
- **Preset table.** Shipped presets (`db.py:139-141`) are S 0.30R/1.5E, B 0.60R/3.0E, L 1.00R/5.0E —
  a constant 20% crossover (R÷E). The old F1 table's E3/4/5 values were pre-migration.
- **ATR discovery is Quarterly window 12, not 8** (`stop_loss.py:261`, label `12q`).
- **AVGO read.** MOMENTUM regime triggered (+25.5% over 6mo VAL) but the row did not flag and
  `_micro_support` returned nothing because today's low (363.83) was the lowest in the 14-day window
  — all micro-structure was overhead. The scanner's VAL_12mo fallback (−20.1%) is a "no support
  below" artifact, not a proposal. Documented as Scenario C.

## Verification

- `uv run python -m pytest tests/ -q` — **166 passed**.
- Chart hover: headless simulation via `motion_notify_event` confirmed correct date/price/DMA
  values, `n/a` in the pre-200-bar region, hide-on-leave, and left-flip past 60% width.
- `HelpScreen`: headless Textual `run_test` pilot mounted all 6 Markdown tabs and cycled them
  without error; all six source files load (no "Not found").
- `dashboard._exit_milestones_panel`: smoke-tested across all stage/regime combinations — renders
  cleanly, no "Efficiency floor" text remains; `ast.parse` confirms no dangling references to the
  removed locals.

## Next Steps

- Visual confirmation of chart hover under the live TkAgg backend (menu 2 → `G`).
- Optional: extend the same hover to any other matplotlib surfaces if desired.
- Consider whether the `dashboard.py` M2/TREND `pct=0.0` path should suppress the "Sell ~1 sh (0%)"
  line entirely (currently `max(1, int(qty*0))` forces 1 share) — minor display artifact, not fixed
  this session.
- Commit the working-tree code changes (chart hover, help refactor, doc-code fixes) — this session
  logs and commits docs; the code changes remain staged for review per the incremental workflow.
