# Open Items

Living checklist of pending work, surfaced on startup by `main.py`.
Tick an item (`- [ ]` → `- [x]`) or delete it when done. Keep it short.

- [x] Launch ZONE SCANNER (option 8) and confirm the Textual panel renders/navigates correctly
- [x] Fix watch-list price-cache gap: WATCH names lack prices.db history (sync covers only open positions) and are silently dropped from the zone scan — fetch on add, or fetch-on-demand in run_scan
- [x] Build one dedicated add-to-watchlist entry point (NOT via the Risk Workspace)
- [x] Momentum stop-tier v2: breakout-gap and high-volume-node micro-anchors

Assessment review follow-ups (Fable_Application_Assessment_Review.md; Must-fixes and Cuts done 2026-07-04):

- [ ] DECIDE the strategic fork: finish gates/calibration wiring (scanner→workspace handoff, calibration in M modal, mode banner, §7 journal capture) vs leave gates off — the Should-fix/Consider items below only matter on the "wire it" path
- [ ] Should-fix: G1 tests against the snapped inception ATR — a tautology; use a fixed named market ATR (daily 14d from discovery) instead
- [ ] Should-fix: reconcile gates with the calibration profile (G1 → ~18% under the 3–6mo lens, or hard-warn when blocking gates meet it)
- [ ] Should-fix: de-duplicate trade_log writes per (conid, open lot) before the journal accumulates rows that poison E[R]
- [ ] Should-fix: de-duplicate identical-price levels in confluence counting (spec §4a minimum viable form)
- [ ] Should-fix: surface "insufficient data" rows in the zone scan instead of silently dropping tickers
- [ ] Consider: one-line mode banner (`gates: off · lens: default`) in risk-workspace and zone-scanner headers
- [ ] Consider: make `calibration_profile` selectable in the M modal (currently a feature with no door)
- [ ] Consider: scanner→workspace handoff key that prefills the command box and threads stop_source/flagged/confluence into the gates
- [ ] Consider: couple C:TH to X:T as an overridable default (one clock per trade, spec §0a)
- [ ] Consider: cheap §1a staleness check — warn when the 14d ATR materially exceeds the profile's long ATR
- [ ] Consider: minimal §7 capture (close-out realized-R backfill prompt + two-keystroke "log skipped pick") so the expectancy report isn't permanently dark
- [ ] README.md is Gemini-era stale (GEMINI Skills section, old prompt notes; docs/GEMINI.md was deleted 2026-07-04) — rewrite or trim to match the current app
