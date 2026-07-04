# Open Items

Living checklist of pending work, surfaced on startup by `main.py`.
Tick an item (`- [ ]` → `- [x]`) or delete it when done. Keep it short.

Source: Fable_Application_Assessment_Review.md (Must-fixes and Cuts done 2026-07-04).

## Do now — small, NOT gated on the fork (all done 2026-07-04)

- [x] De-dup `trade_log` writes per (conid, open lot) — `C:`-tagged commits write rows regardless of `gates_mode`, so duplicates poison E[R] the moment tagging starts
- [x] Zone scanner: de-duplicate identical-price levels in confluence counting (spec §4a minimum viable form — VAL==POC currently counts twice)
- [x] Zone scanner: surface "insufficient data" rows instead of silently dropping young tickers
- [x] One-line mode banner (`gates: off · lens: default`) in risk-workspace and zone-scanner headers
- [x] Make `calibration_profile` selectable in the `M` modal — the 3–6mo lens currently has no door

## Fork — DECIDED 2026-07-04: advisory gates + handoff (all built)

- [x] DECIDE the strategic fork: advisory gates + scanner→workspace handoff; `blocking` waits until advisory output earns trust
- [x] G1 tests against a fixed named market ATR (daily 14d; weekly 12w under the 3–6mo lens) — inception-ATR tautology gone
- [x] Gates reconciled with the calibration profile (G1 → 18% cap + weekly ATR under `position_3to6mo`)
- [x] Scanner→workspace handoff: `scan_context` table feeds G2/G3/G5 on every commit; `c` key prefills the command box (one-shot, 1h expiry); G7 wired to open book R%
- [x] Flip `gates_mode` to `advisory` (set directly in settings 2026-07-04; the banner shows it)

## Decide separately — the expectancy loop (done 2026-07-04)

- [x] Minimal §7 capture: menu 9 now backfills realized R on closed lots (ledger-suggested, user-confirmed) and logs skipped picks via `K`

## Low / whenever (done 2026-07-04)

- [x] Couple C:TH to X:T as an overridable default (one clock per trade, spec §0a)
- [x] Cheap §1a staleness check — 14d vs 12w ATR ratio warning under the 3–6mo lens
- [x] README.md rewritten to match the current app (Gemini-era content removed)

Queue clear. Standing observation (not an action item): run gates in `advisory` for a
few weeks and review the FAIL/NA pattern before considering `blocking`.
