# Open Items

Living checklist of pending work, surfaced on startup by `main.py`.
Tick an item (`- [ ]` → `- [x]`) or delete it when done. Keep it short.

- [x] Launch ZONE SCANNER (option 8) and confirm the Textual panel renders/navigates correctly
- [x] Fix watch-list price-cache gap: WATCH names lack prices.db history (sync covers only open positions) and are silently dropped from the zone scan — fetch on add, or fetch-on-demand in run_scan
- [x] Build one dedicated add-to-watchlist entry point (NOT via the Risk Workspace)
- [x] Momentum stop-tier v2: breakout-gap and high-volume-node micro-anchors
- [x] Horizon-aware regime lens: the trim-driving regime is hardcoded to the 200-DMA (21d confirmation) regardless of the trade's horizon. Key the lens off the stop's volatility horizon instead — stop distance in daily-ATR multiples → Daily≈tight → 50-DMA/10d; Weekly → 100-DMA/15d; Monthly+ → 200-DMA/21d (today's behaviour). Mirrors the inception-ATR snapping already done for the milestone ladder; classification (C:) stays carried-only. Default-off behind the `regime_lens` setting (`M` modal); characterization snapshot unchanged.
- [x] Complete the Entry & Stop System §7 logging loop — DONE: `SRC:`/`THM:` commit tokens (risk workspace), Watch List `L`-key skipped-pick logging, `benchmark_ticker` setting (SPY) cached as `BENCHMARK:<ticker>` in prices.db, and `core/outcome_backfill.py` (realized R + MAE/MFE + vs-benchmark, auto-run on menu 9). `realized_return_base` deliberately left NULL (needs an FX-at-exit source — future item).
