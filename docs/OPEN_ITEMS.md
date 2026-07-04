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
- [ ] Flip `gates_mode` to `advisory` in the M modal (user action — the banner will show it)

## Decide separately — the expectancy loop

- [ ] Minimal §7 capture (close-out realized-R backfill prompt + two-keystroke "log skipped pick") — independent of gates; without it menu 9 stays dark forever

## Low / whenever

- [ ] Couple C:TH to X:T as an overridable default (one clock per trade, spec §0a)
- [ ] Cheap §1a staleness check — warn when the 14d ATR materially exceeds the profile's long ATR (pairs with the M-modal lens switch)
- [ ] README.md rewrite — Gemini-era stale (GEMINI Skills section, old prompt notes; docs/GEMINI.md deleted 2026-07-04)
