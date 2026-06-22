# Session 2026-06-22 — Entry/Exit Zone Scanner

## Objectives

Build the Entry/Exit Zone Framework from `entry_exit_framework_instructions.md`:
a scanner that flags entry/exit price zones for position trades by detecting
where current price sits on a cluster (confluence) of structural levels —
composite volume profile, anchored VWAP, and moving averages — integrated with
the existing dual-constraint sizing and preset framework. Mid-build, the brief
was extended with a **Momentum Regime dynamic stop-tier** to make momentum-flag
entries (shallow pullbacks in parabolic moves) tradeable.

## Technical Changes

New core modules (pure logic, no I/O):
- **`core/volume_profile.py`** — `compute_volume_profile()` (close-weighted
  triangular smear of daily volume into 0.5%-of-price buckets → POC/VAH/VAL,
  ~70% value area); `find_naked_pocs()` (plateau- and edge-aware peak detection,
  prominence-filtered). `_plateau_peaks()` guards the boundary-tie and edge-bucket
  failure modes that hid the dominant shelf.
- **`core/anchored_vwap.py`** — `find_pivots()` (symmetric fractal swing
  detection), `anchored_vwap()` (volume-weighted typical price from an anchor),
  `compute_anchored_vwaps()` (most-recent swing-low + swing-high anchors).
- **`core/zone_scan.py`** — orchestrator `scan_ticker()` / `build_zone_report()`
  with injected `price_loader`; `_wilder_atr()` replicates the stop_loss EWM
  method; `_nearest_support()`; `_micro_support()` for the momentum tier.

Modified:
- **`core/confluence.py`** — rewritten as a generalized engine:
  `evaluate_confluence(price, stop, levels, atr, threshold, fortress)` where
  `levels` is an open dict (DMA/EMA/VAL/VAH/POC/AVWAP). Returns `strength`,
  per-level `levels` detail, named `zones`. Previously orphaned; now the single
  source of truth.
- **`ui/watch_list_workspace.py`** — inline confluence loop replaced with one
  `evaluate_confluence()` call (output byte-identical); import swapped.
- **`ui/zone_scan_workspace.py`** (new) — Textual workspace: results table
  (TAG/TICKER/REGIME/PRICE/DIST/SIG/STOP) + detail panel (signals, stop/target,
  preset sizes), background-threaded scan, daily-bar footer note.
- **`main.py`** — menu option `[8] ZONE SCANNER` + `handle_zone_scanner()`.
- **`constants.py`** — VP/AVWAP/confluence/momentum tunables (see below).

Tooling & tests:
- `tools/validate_volume_profile.py`, `tools/validate_anchored_vwap.py` — manual
  harnesses for eyeballing against TradingView.
- `tests/test_volume_profile.py` (7), `test_anchored_vwap.py` (8),
  `test_confluence.py` (8), `test_zone_scan.py` (12) — 35 new tests.

New constants (`constants.py`): `VP_LOOKBACKS_MONTHS=(6,12)`, `VP_BUCKET_PCT=0.005`,
`VP_VALUE_AREA_PCT=0.70`, `PIVOT_WINDOW=10`, `ZONE_CONFLUENCE_PCT=0.025`,
`ZONE_MIN_CONFLUENCE=2`, `MOMENTUM_VAL_PREMIUM_PCT=0.10`, `MICRO_LOOKBACK_DAYS=14`,
`MICRO_STOP_BUFFER_ATR=0.25`.

## Logic & Decisions

- **Brief was greenfield; ~2/3 already existed.** Mapped each brief module onto
  existing infrastructure and built only the genuinely new parts. Dropped from the
  brief: a second IBKR CSV parser, a separate watchlist file, a YAML config, a
  plain-text CLI, and the 5:1 ratio. Four decisions locked toward
  consistency-with-app: **3:1 reward** (RR_SETUP_FLOOR, not 5:1); **TUI workspace**
  (not CLI); **universe = ACTIVE holdings + status='WATCH'** (not a file); **tunables
  in constants.py** (not YAML).
- **Volume profile is a daily-bar approximation.** Yahoo provides no intraday
  volume-at-price; each daily bar's volume is smeared across its high–low range
  with a triangular weight peaking at the close. Validated vs TradingView: VOO POC
  631.66 (TV) sat between our 6mo (637.39) and 12mo (626.17) — within ~0.9% / <2
  buckets. Acceptable for zone detection (the confluence band is 2.5% wide). Caveat
  footer-flagged everywhere.
- **Confluence in ATR units.** Distances measured in ATR so one threshold works
  across price scales. The scanner expresses the 2.5% band in ATR per ticker
  (`threshold = ZONE_CONFLUENCE_PCT × price / atr`); the watch-list keeps the fixed
  0.25-ATR standard.
- **Stop = nearest invalidating support below price** (tightest of VAL / AVWAP-low),
  falling back to a 1-ATR stop when none exists.
- **Momentum Regime stop-tier.** When `price > VAL_6mo × (1 + 10%)`, the 6mo VAL is
  too distant for a momentum entry (real stops were −17% to −29%). The scanner drops
  to a micro-structure stop from the last 14 bars — the micro-VP VAL and an AVWAP
  anchored to the recent swing low, nearest below price, minus a 0.25-ATR buffer —
  and tags the row `ZONE-MOMO`. A clean break of that level means the parabolic move
  is done. Cut the same stops to −1.7% to −6.1%. Flagging logic unchanged (stop-only
  change); breakout-gap / high-volume-node anchors deferred to v2.
- **NaN guard.** `scan_ticker` checks `math.isfinite()` on price/ATR — a NaN last
  close (e.g. PM) silently passes `<= 0` comparisons and would propagate.

## Verification

- **Full suite: 158 passed** (was 130 at session start; +35 new, less overlap).
- **Volume profile validated** against TradingView (VOO POC within ~0.9%).
- **Live headless end-to-end** through the workspace data path: NAV 2,688,800 EUR,
  34-name universe (holdings + watch), 32 scanned, **20 flagged** — momentum names
  on micro stops (AVGO/GOOGL/BATT → AVWAP_14d, PM → VAL_14d), base names on
  VAL_6mo / AVWAP_low, sizes per preset. PM (prior NaN) now scans on its live price.
- Feature committed: `26e0a2a feat(zones): add entry/exit zone scanner with
  momentum stop-tier`.
- Not yet verified: the interactive Textual panel itself (cannot drive the event
  loop headlessly) — needs a manual launch of option [8].

## Next Steps

- Manually launch `[8] ZONE SCANNER` to confirm panel rendering/navigation.
- **Watch-list price-cache gap:** `handle_sync_prices` syncs only open positions,
  so WATCH names lack `prices.db` history until opened in a workspace and are
  silently dropped from the scan. Add price fetch on add, or fetch-on-demand in
  `run_scan`.
- **Dedicated add-to-watchlist entry point** (separate follow-up): one purpose-built
  way to add a ticker to the watch list, NOT via the Risk Workspace.
- **Momentum stop-tier v2:** breakout-gap and high-volume-node micro-anchors.
