# Open Items

Living checklist of pending work, surfaced on startup by `main.py`.
Tick an item (`- [ ]` → `- [x]`) or delete it when done. Keep it short.

Source: Fable_Application_Assessment_Review.md (Must-fixes and Cuts done 2026-07-04).

## Do now — small, NOT gated on the fork

- [ ] De-dup `trade_log` writes per (conid, open lot) — `C:`-tagged commits write rows regardless of `gates_mode`, so duplicates poison E[R] the moment tagging starts
- [ ] Zone scanner: de-duplicate identical-price levels in confluence counting (spec §4a minimum viable form — VAL==POC currently counts twice)
- [ ] Zone scanner: surface "insufficient data" rows instead of silently dropping young tickers
- [ ] One-line mode banner (`gates: off · lens: default`) in risk-workspace and zone-scanner headers
- [ ] Make `calibration_profile` selectable in the `M` modal — the 3–6mo lens currently has no door

## Fork-gated — decide first

- [ ] DECIDE the strategic fork: recommendation is advisory gates + scanner→workspace handoff (not binary wire-everything/leave-off); `blocking` waits until advisory output earns trust
- [ ] (if wired) G1 must test against a fixed named market ATR (daily 14d from discovery) — testing the snapped inception ATR is a tautology
- [ ] (if wired) Reconcile gates with the calibration profile (G1 → ~18% under the 3–6mo lens, or hard-warn when blocking gates meet it)
- [ ] (if wired) Scanner→workspace handoff key: prefill the command box, thread stop_source/flagged/confluence into ProposedTrade (wakes G2/G3 for free)

## Decide separately — the expectancy loop

- [ ] Minimal §7 capture (close-out realized-R backfill prompt + two-keystroke "log skipped pick") — independent of gates; without it menu 9 stays dark forever

## Low / whenever

- [ ] Couple C:TH to X:T as an overridable default (one clock per trade, spec §0a)
- [ ] Cheap §1a staleness check — warn when the 14d ATR materially exceeds the profile's long ATR (pairs with the M-modal lens switch)
- [ ] README.md rewrite — Gemini-era stale (GEMINI Skills section, old prompt notes; docs/GEMINI.md deleted 2026-07-04)
