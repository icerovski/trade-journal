# Session Log — 2026-07-04 (later): Advisory Gates Build & Queue Cleanup

Continuation of the same-day audit-remediation session (see
`2026-07-04_Audit_Remediation_And_Review.md`). Covers commits `e4e2636` → `8fc9cbe`.

## Objectives

- Commit the assessment brief/review to the repo; reorganize `docs/OPEN_ITEMS.md` by real priority.
- Clear the five "Do now" items (live quality fixes not gated on any decision).
- Decide and build the strategic fork: **advisory gates + scanner→workspace handoff**.

## Technical Changes

### Do-now items (`3e83286`)
- **`trade_log` upsert** — `db.find_open_trade_log_id(conid)` (latest TAKEN row with `realized_r IS NULL`); `_log_classification` updates the open row instead of appending. One decision per open lot; a closed-out lot starts a fresh row.
- **§4a independent confluence** — `ZONE_DEDUP_EPS_ATR = 0.05`; `zone_scan._independent_count()` collapses entry signals within ε·ATR of each other for the *flag decision only* (signal list and result schema untouched — golden master stayed byte-identical, as designed).
- **THIN rows** — `build_zone_report` emits an `insufficient_data` stub (with cached bar count) instead of dropping young tickers; scanner renders them dimmed with a detail-panel explanation.
- **Mode banner** — risk-workspace header shows `gates: {mode} · lens: {profile}`; zone-scanner header shows the active lens.
- **Lens door** — `calibration_profile` editable in the `M` modal (validated `default` / `position_3to6mo`).

### Advisory gates fork (`8fc9cbe`)
- **`scan_context` table** (additive; REPLACE per ticker) — regime, flagged, independent confluence count, stop_source/price, DMA200 trail anchor, scan_date. Written by `zone_scan_workspace` after every scan; `db.get_scan_context(ticker, max_age_days)` applies the freshness window.
- **`_gate_check` rewired** — G1 tests the *named* daily 14d discovery ATR (weekly 12w + `GATE_G1_MAX_STOP_PCT_3TO6MO = 0.18` under the 3–6mo lens) via new `ProposedTrade.g1_max_stop_atr/g1_max_stop_pct` overrides; G2/G3/G5 read scan context (fresh within `GATE_CONTEXT_MAX_AGE_DAYS = 7`, else NA); G7 reads Σ open `risk_pct_nav` across other held names. G4 remains NA (no earnings source); G6 remains the cut stub.
- **Handoff** — `c` on a flagged scanner row writes a one-shot `pending_handoff` settings key; the risk workspace consumes it on mount (≤1h old): cursor to the ticker's row, command box prefilled `<stop> F`. Nothing auto-commits.

## Logic & Decisions

- **Fork resolution**: advisory + handoff instead of the binary wire-everything/leave-off. Advisory mode gives the §4 discipline signal on every commit with zero blocking risk; `blocking` waits until the advisory output earns trust. `gates_mode` default stays `off` in code (golden master + `test_default_gates_mode_is_off` untouched) — the user flips his own DB in the `M` modal.
- **DB-mediated handoff, not cross-app choreography**: the scanner and workspace are separate Textual apps, so context rides the `scan_context` table. This is deeper than a prefill key — gates get real G2/G3/G5 inputs on *every* commit after a scan, key pressed or not. Stale context (> 7 days) degrades to NA, never misfires.
- **G1 de-tautologized**: the snapped inception ATR sits near the risk distance by construction, so testing width against it always passed ≈1.0×. A fixed, named market ATR restores the gate's meaning; the lens override keeps it honest at the 3–6mo horizon (spec: weekly ATR arm, ~18% cap).
- **Confluence de-dup scoped to the flag** so the characterization snapshot could not move — the display keeps every level; only "does this earn a zone?" counts independent walls.

## Verification

- Full suite **294 passed** (287 → 294 across the two commits: scan-context persistence/freshness, G1 override arms, trade-log upsert/closed-lot/skipped-row cases, independent-count, THIN stub + sort). Golden master byte-identical throughout.
- Import smoke clean on all touched modules after each commit.

## Next Steps

- **User action**: set `gates_mode = advisory` in the `M` modal (banner confirms), and run a zone scan (menu 8) so commits evaluate against fresh context.
- **§7 expectancy capture** — the remaining substantive decision (realized-R backfill + skipped-pick logging); without it menu 9 stays dark.
- Low queue: `C:TH`→`X:T` coupling, §1a staleness warning, README rewrite.
- Consider observing advisory output for a few weeks before revisiting `blocking`.
