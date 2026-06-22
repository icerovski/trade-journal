# Open Items

Living checklist of pending work, surfaced on startup by `main.py`.
Tick an item (`- [ ]` → `- [x]`) or delete it when done. Keep it short.

- [ ] Launch ZONE SCANNER (option 8) and confirm the Textual panel renders/navigates correctly
- [ ] Fix watch-list price-cache gap: WATCH names lack prices.db history (sync covers only open positions) and are silently dropped from the zone scan — fetch on add, or fetch-on-demand in run_scan
- [ ] Build one dedicated add-to-watchlist entry point (NOT via the Risk Workspace)
- [ ] Momentum stop-tier v2: breakout-gap and high-volume-node micro-anchors
