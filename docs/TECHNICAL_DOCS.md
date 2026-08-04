# Technical Documentation: Trade Journal & Risk Management

This document serves as the "Single Source of Truth" for the technical implementations and operational workflows of the system.

---

## 1. Institutional Prospect Simulator & Watch List

The Prospect Simulator allows for the analysis and simulation of potential stock purchases using existing institutional risk frameworks before capital is committed.

> **Adding a name to watch — the dedicated path is the Watch List (menu 6).** Press **`a`**,
> type a symbol, and the app resolves it to a real `conid`, caches ~10y of prices, computes a
> default (Daily TRAILING / Base preset) risk profile, and saves it as a `WATCH` row — making
> it immediately scannable (menu 8) and chartable. The add also records the symbol's real
> pricing currency (so prospect sizing uses the right ccy→NAV fx rate), and **refuses to
> auto-profile a name with under ~15 daily bars** — a shrunken-window "daily ATR" would be
> frozen as the stop distance and inception R unit; set a manual stop in the Risk Workspace
> instead. The Risk Workspace "Discover" field below remains for **ATR / risk research and
> refinement** (and can still persist a `PROSPECT:TICKER` prospect via `CTRL+ENTER`), but new
> names are normally started from menu 6.

### Operational Workflow
1.  **Ticker Discovery**: Within the **Risk Workspace** (Option 2 from the main menu), use the **"Discover Ticker"** input field to research a symbol's ATR volatility and model stops/sizing (refinement, not the primary add path — see the note above).
2.  **Instant Simulation**: Entering a ticker (e.g., `NVDA`, `TSLA`) triggers an automated background process:
    *   **Price Fetching**: Real-time pricing and historical OHLCV data are retrieved via `yfinance`.
    *   **Volatility Analysis**: ATR horizons are calculated across multiple timeframes: 14d (Daily), 12w (Weekly), 12m (Monthly), and 12q (Macro).
    *   **Prospect Anchoring**: For unowned assets (entry price = 0.0), the system automatically assumes a purchase at the **current market price**.
    *   **Standard Unit Sizing**: Metrics like "P/L at Stop" and "Risk (R)" are calculated based on a **Standard Unit** (the maximum shares allowed by the designated Risk and Exposure limits).
    *   **Strategy Modeling**: Users can model "What-If" scenarios in the **Strategy Lab** to see hypothetical stops and targets.
3.  **Institutional Sizing**: The system performs a **Dual-Constraint Audit** against live total NAV:
    *   **Risk Limit**: Ensures potential loss at stop does not exceed the designated Risk Limit (Default: 1.0% of NAV).
    *   **Exposure Limit**: Ensures total market value does not exceed the designated Exposure Limit (Default: 5.0% of NAV).
    *   The most restrictive constraint automatically dictates the recommended share count.
    *   **FX-normalized**: both limits are measured in the NAV currency via the asset's fx rate (broker snapshot for held names; for prospects, the real pricing currency is resolved at add/discover time — held-book rate first, live FX fallback — including pence-quoted listings). A USD stop distance is no longer treated as EUR at par.
4.  **Watch List Persistence**: Pressing `CTRL+ENTER` saves the simulation as a **"Watch List"** profile in the database.
5.  **The "Healing" Bridge**:
    *   Prospects are tracked using a `PROSPECT:TICKER` virtual ID.
    *   Upon purchasing the asset, the next broker sync will discover a real IBKR `conid`.
    *   The system automatically "promotes" the Watch List settings to the live `ACTIVE` position, preserving all original analysis and ATR settings.

### Technical Implementation Details
*   **Data Persistence**: Watch list items are stored in the `risk_profiles` table with a status of `WATCH`.
*   **Database Integrity**: A unique index (`idx_watch_conid`) prevents duplicate prospect entries.
*   **Seamless Integration**: Watch List items are injected into the consolidated dashboard view (flagged as `WATCHLIST`), allowing for performance monitoring against targets before execution.
*   **Account Agnostic**: Cost-basis healing and promotion logic operate at the asset level to handle multi-account environments.

---

## 2. Multi-Account Consolidation & Cost Basis Healing

Institutional-grade accounting logic that ensures a unified portfolio view and accurate cost-basis recovery across multiple entities and account types.

### Operational Workflow
1.  **Unified Portfolio View**: The Dashboard and Risk Workspace automatically consolidate positions with the same `conid` across all accounts into a single row by default.
2.  **Automated Healing**: If a broker snapshot reports a zero cost basis (typical for asset transfers), the system automatically performs a recursive scan of the global trade ledger.
3.  **Manual Ledger Enrichment**: Users can "force heal" a position by entering a manual `TRANSFER_IN` or `BUY` record with correct historical data via Option 2 -> 2. The system will link this history during the next calculation.

### Technical Implementation Details
*   **Weighted Average Cost (WAC)**: Merged positions calculate entry price using the formula: `((Qty1 * Price1 * Mult1) + (Qty2 * Price2 * Mult2)) / (TotalQty * ConsolidtedMult)`.
*   **Inception Anchoring**: Trailing stops and roadmap milestones are anchored to the earliest `date_entry` and original `inception_price` found across all accounts for that asset.
*   **Account-Agnostic Reconciliation**: The `ReconciliationService` implements a multi-stage lookup: it first attempts an exact `(Account:Conid)` match for cost basis, then falls back to a global `Conid` match if entry price remains unknown.
*   **Stability**: Consolidating by `conid` prevents `DuplicateKey` UI crashes in environments where the same asset is held in multiple accounts.

---

## 3. Customizable Conviction Limits (Risk & Exposure)

Allows for per-position Risk-at-Stop and Exposure limits, moving the system from a "one-size-fits-all" model to a "conviction-weighted" capital allocation model.

### Operational Workflow
1.  **Syntax**: Within the **Strategy Lab**, use the following flags to set custom limits:
    *   `R:X.X`: Custom Risk limit (e.g., `R:0.5` for 0.5% max risk. Default: 1.0%).
    *   `E:X.X`: Custom Exposure limit (e.g., `E:10.0` for 10% max exposure. Default: 5.0%).
    *   Example: `15 T S R:1.0 E:7.5` (15% Trailing, Scale-In, 1% Risk, 7.5% Exposure).
2.  **Dynamic Auditing**: The **Risk Audit** panel automatically scales its recommendations based on these limits. "Room to add" will be restricted by whichever limit is hit first.
3.  **Visual Status**: Metric colors (Green/Yellow/Red) in the Grid and Sidebar automatically adjust their thresholds based on the specific limits assigned to the position.

### Technical Implementation Details
*   **Database Persistence**: Custom limits are stored in the `max_r_pct` and `max_exp_pct` columns of the `risk_profiles` table.
*   **Fallback Logic**: Default institutional standards (**1.0% Risk / 5.0% Exposure**) are applied if no custom limits are provided.
*   **Risk Engine Integration**: The `audit_position_risk` and `calculate_pilot_entry` methods accept dynamic limit parameters, ensuring that roadmap quantity targets and action signals (Add/Trim) are always aligned with the position's specific conviction profile.

---

## 4. Stop Loss Philosophy: Fixed Dollar vs. Constant Percentage

The system implements an institutional "Volatility Buffer" approach to stop loss management, prioritizing statistical breathing room over static percentage targets.

### Operational Logic
1.  **Fixed Dollar (Volatility Buffer)**: When a stop loss is assigned (e.g., "15% Fixed"), the system performs a one-time calculation to determine the absolute dollar distance (e.g., $15.00). 
    *   This dollar amount is stored as the `atr_value`.
    *   Subsequent monitoring subtracts this fixed amount from the **Stop Base** (Entry Price or High-Water Mark).
2.  **Trailing Dynamics**: As the price of an asset increases, the **Exit Price** moves up by the same fixed dollar amount.
    *   **Result**: The **SL %** (percentage distance to stop) naturally decreases as the price rises.
    *   **Rationale**: This effectively "tightens" the stop in percentage terms while maintaining a consistent risk-unit ($) buffer. It prevents "giving back" excessive profits by keeping the stop anchored to the asset's original volatility profile rather than allowing the dollar risk to expand as the position grows in value.

### Technical Implementation Details
*   **Storage**: The calculated dollar distance is persisted in the `atr_value` column of the `risk_profiles` table.
*   **Monitoring**: The `RiskEngine.calculate_position_risk` method uses this fixed `atr_value` to derive the `sl_price` and `tp_price` during every dashboard refresh.
*   **Manual Re-anchoring**: If a user wishes to "reset" the stop to a constant percentage after a significant price move, they must manually re-enter the percentage in the **Strategy Lab** (e.g., `15 T`), which triggers a new dollar calculation based on the current (higher) price.

### Live P/L at Stop (Breach Degradation)

The **P/L STOP** column normally shows the *planned* outcome — the profit or loss you would realise if the position exits cleanly at the stop price: `(stop − entry) × qty × multiplier`. But a stop is not a guarantee of fill: gaps, illiquidity, or simple failure to act can carry price *below* the stop, where the realisable exit is worse than planned.

The **Live P/L at Stop** tracks this. It is the P/L at the effective exit price, defined as:

```
effective P/L = (min(stop, current_price) − entry) × qty × multiplier
```

*   **Price at or above the stop**: `min(stop, current) = stop`, so the figure equals the planned stop-out. No visual change.
*   **Price below the stop (BREACH)**: `min` follows the live price down, so the figure degrades past the plan and keeps falling with the price. The column shows the live value with the original planned figure in parentheses — e.g. `-100 (-50)` — so the slippage past plan is visible at a glance.
*   **Price reclaims the stop**: the figure snaps back to the planned value. Nothing is persisted; it is recomputed every refresh.
*   **Trailing stops**: new highs ratchet the stop up via the high-water mark (the Ratchet Rule), which lifts the *planned* value on its own. The breach logic above sits on top of that — together: P/L rises as price makes new highs, and falls once price breaks below the (ratcheted) stop.

### Technical Implementation Details — Live P/L
*   **Fields**: `Position.risk_val` holds the planned stop-out (unchanged — still feeds the portfolio stop-out aggregate in `core/sizing.py`); `Position.risk_val_live` holds the breach-aware figure. Both are set in `calculate_position_risk` step 5.
*   **Display**: `ui/risk_workspace.py` renders the `live (planned)` form in the P/L STOP column only while breached; `ui/dashboard.py` mirrors it in the position detail panel as `live (was planned)`.
*   **Scope**: The Strategy Lab's hypothetical P/L still shows the *planned* what-if value, since it models a stop you have not yet hit.

---

## 5. Profit-Taking System: Exit Stages & Trend Regime

A staged exit framework that avoids premature profit-taking in strong trends while protecting gains in ranging or deteriorating markets.

### Trend Regime

Market structure is classified per position using the 200-DMA consecutive rising-days count. Additional signals can be layered into `_enrich_regime()` as strategy evolves.

**Signal — 200-DMA Direction**

Daily DMA change = `(today's close − close 200 days ago) / 200`. Because it averages 200 sessions, a single bad day barely moves it. The signal counts how many consecutive days the DMA has moved in the same direction without reversal.

**Reversal hysteresis.** The consecutive-day count resets to ~1 on any direction reversal, so without dampening a single counter-trend day would crash a long TREND straight to RANGING. A DMA reversal must persist `REGIME_REVERSAL_CONFIRM_DAYS` (default 3) before it demotes the regime to RANGING; until then the position is held one notch up at **NORMAL** (unconfirmed reversal). This is stateless — it reads the live down-run length rather than persisting prior regime. The `risk_workspace.py` regime verdict labels this case explicitly ("DMA reversed Nd (< K, unconfirmed) → held at NORMAL").

**Regime classification:**

| Regime | 200-DMA Rising Days | Trim M2 | Trim TP |
|--------|---------------------|---------|---------|
| TREND  | ≥ 21                | Hold (0%) | 20%     |
| NORMAL | 10 – 20             | 33%     | 33% or close |
| RANGING | < 10 or declining  | 50%     | Close all |

In a confirmed TREND the M2 trim is **0% (hold)** by design: trimming a confirmed compounder cuts the winner against the trend-following mandate. The trailing stop is the exit mechanism and profits are banked at TP. A `TRIM_MATRIX` fraction of `0.0` renders a "Hold — no trim" directive instead of a sell.

**Horizon lens (opt-in — `regime_lens` setting).** The table above reads the 200-DMA for every position regardless of the trade's horizon, which mis-clocks short trades: a tight-stopped leveraged-ETF trade lives for weeks, and the 200-DMA barely moves within its lifetime. With `regime_lens = horizon` (Presets/Settings modal `M`; default `default` = today's behaviour), each position's regime is instead judged on a DMA matched to **the horizon its stop declares** — the frozen inception ATR measured in daily-ATR14 multiples (`select_regime_lens`):

| Risk unit ÷ daily ATR14 | Lens | TREND ≥ | NORMAL ≥ |
|---|---|---|---|
| ≤ 1.6 (≈ daily-ATR stop) | 50-DMA | 10d | 5d |
| ≤ 3.4 (≈ weekly-ATR stop) | 100-DMA | 15d | 7d |
| wider, or missing data | 200-DMA | 21d | 10d (unchanged) |

This mirrors the inception-ATR snapping the milestone ladder already does — the ladder and the regime then run on the same clock, both derived from the stop. TREND is gated on price being above the *lens* DMA; reversal hysteresis (3d) is shared. The `RegimeDMA` string names a non-default lens (e.g. `BUY (12d, DMA50)`), and `Position.regime_lens` carries the window. Classification (`C:`) stays carried-only — the lens keys off stop geometry, not the tag. Bands are tunables in `constants.REGIME_LENS_BANDS` (§8 governance: validate from the log).

### Exit Stages

Milestones are anchored to `entry_price + N × R`, where `R` is the **inception ATR** (the ATR/risk unit at first entry) for **both** stop types. The ladder is uniform — M1=+1R, M2=+2R, TP=+3R from entry — and measures profit in *R-multiples*. Falls back to `entry − final_sl` if inception_atr is unavailable.

How `R` is sourced differs by stop type, because the two take different inputs. For **TRAILING** the user supplies an ATR *distance* directly, and that distance is `R`. For **FIXED** the user supplies a stop *price*, not a distance, so there is no ATR to read — the commit path snaps the **risk distance `entry − stop`** to the nearest of the four discovery-timeframe ATRs (daily/weekly/monthly/quarterly) and stores that as `R`. **Thin-history guard:** a timeframe whose history can't fill its full ATR window is marked `⚠` in the discovery tables and excluded from the snap (its value keeps the label only nominally); if the exclusion moves the snap to a different timeframe than the nearest displayed one, the workspace says so. When *no* trustworthy ATR exists (young listing, or discovery unavailable), `R` anchors to the raw `entry − stop` distance instead — a shrunken-window ATR or the stop price itself is never frozen as the R unit. This makes the ladder run on the volatility horizon that matches how the stop was sized: a deliberately deep stop (e.g. a leveraged ETF) lands on quarterly, so its milestones sit far enough out that the ladder doesn't fire on noise. The earlier behaviour — hardcoding the *daily* ATR for every FIXED stop — mis-scaled the ladder on deep stops (UDOW: daily ATR 1.86 vs a 21.5-point stop tripped M1 at a +2.8% gain).

For TRAILING stops the ladder deliberately uses the **inception ATR, not the live trailing distance**. The live ATR governs only where the *stop* sits; using it for the reward ladder made the milestones drift away as volatility expanded (e.g. AVGO: live ATR 88 vs inception 57 pushed M1 to entry+88 ≈ 449, mislabelling a +33% winner as an early stage). The TP is also **entry-anchored, not stop-anchored** — anchoring to the ratcheted stop made it collide with M2 at inception.

**TP override (`risk_profiles.tp_atr_mult`).** Once a winner runs past the default +3R the ladder is maxed out. A per-position override extends the *top rung* to any multiple of the **same frozen inception ATR** (`TP = entry + tp_atr_mult × inception_ATR`); M1/M2 stay at +1R/+2R. Because it is anchored to the frozen ATR, the target stays put when the live stop ATR is later tightened — editing the stop never moves it. `NULL` = the default `TP_ATR_MULTIPLE` (3R). Set it from the risk workspace with `TP:n` (see below); the engine reads it in `calculate_position_risk`, and `compute_exit_milestones` warns if an override lands at/below M2 (< 2R, a non-monotonic ladder).

**Setting the target — `TP:n` command.** Three fixed input forms, all resolved to a multiple of the inception ATR by `resolve_tp_mult`: `TP:4`/`TP:4R` (R-multiple), `TP:+35%` (gain as % of entry ÷ ATR), and `TP:-` (clear → default 3R); plus the ratio form `TP:N:1` (forward reward:risk vs the modeled stop, resolved by `resolve_tp_ratio` once the stop is known). The absolute-$ form (`TP:$60K`) was removed (assessment review, 2026-07-04) — four ways to express one number was three too many, and `TP:nR`/`TP:N:1` carry the real use cases; `$`/`K` tokens are now rejected with a warning. When an override is active the audit panel shows a **TARGET** line with the **forward** reward:risk `(target − price)/(price − stop)`, flagged `⚠ below 3:1` when it falls under `RR_SETUP_FLOOR` (3.0) — the honest "what am I paid to keep holding from here" check (it reads low for a run-up winner whose stop already sits above entry, which is expected once entry risk is gone).

| Stage  | Trigger                    | Action                         |
|--------|---------------------------|-------------------------------|
| PRE-M1 | price < entry + 1×ATR     | Hold — position not yet earned |
| M1     | price ≥ entry + 1×ATR     | Raise stop to entry (free position) |
| M2     | price ≥ entry + 2×ATR     | Partial trim by regime         |
| TP     | price ≥ entry + 3×ATR     | Larger trim by regime; extend target in TREND |

**RR (Efficiency) is informational only — it does not trigger an exit.** RR `(TP − price)/(price − stop)` is shown in the PLAN panel as a "what am I paid to keep holding from here" read, but no longer forces a sell. The previous **efficiency floor** (a sub-1.0 RR at M2/TP on a FIXED stop forced an exit, or a stop raise to `2·P − TP`) was removed: on a deliberately deep stop the large `price − stop` denominator drags RR below 1.0 even when the position is perfectly healthy, so the floor fired on the stop geometry rather than on a real loss of edge. Raising the stop as price advances lifts RR back above 1.0 on its own.

Exits are instead driven by the **stop** (a breach *is* the exit) and the **regime** — RANGING trims are heavy (M2 = 50%, TP = 100% via the `TRIM_MATRIX`), so a position that loses its trend is still wound down. This applies uniformly to FIXED and TRAILING stops; stop type no longer changes the directive.

### Capital-Efficiency Flag (Dead Money)

Orthogonal to the ATR exit ladder — it answers "is this capital working?", not "should I take profit?". A position is flagged **STALE** when both hold:
- `age_days ≥ STALE_MIN_AGE_DAYS` (default 180 — below this, annualised return is too noisy/extrapolated to judge), **and**
- `aagr < CAPITAL_HURDLE_PCT` (default 8% — the opportunity-cost hurdle).

`aagr` is the existing annualised **unrealised** return (price-only, entry vs current) from `Position.calculate_financial_metrics()`; the flag is set there as `is_stale`. The `risk_workspace.py` PLAN panel always shows the `Capital: ±x% AAGR over Nd` metric line, and appends a `⏳ STALE … review or redeploy` nudge (suppressed on a stop breach, where the exit directive dominates). Thresholds live in `constants.py`.

**Income-asset exclusion:** Bonds/bills (`AssetRegistry.is_income_asset`, i.e. `PERCENT_OF_PAR_ASSETS`) are never flagged STALE — price-only AAGR ignores coupon and would mislabel a coupon-earning hold as dead money. Revisit if/when AAGR becomes total-return.

### Technical Implementation

- **`core/stop_loss.py`** — `calculate_position_risk()` sets `tp_price` (entry-anchored, §3) and calls `profit_taking.compute_exit_milestones()` (§8), which computes `m1_price`, `m2_price`, `exit_stage`. Fields stored on the `Position` object.
- **`core/profit_taking.py`** — `enrich_regime(positions, mapper, lens_mode="default")` sets `trend_regime`, `regime_dma`, `regime_dma_signal`, `regime_dma_days`, `regime_dma200`, `regime_lens` on each position via the DMA consecutive-rising-days signal (TREND gated on price > lens DMA; lens = 200-DMA unless `regime_lens = horizon`, which picks 50/100/200 per the stop's ATR horizon via `select_regime_lens`). `TRIM_MATRIX` holds the `(stage, regime) → (fraction, rationale)` guidance. Called as step 4 in `portfolio_manager.get_dashboard_df()`.
- **`dashboard.py`** — EXIT column in main grid; EXIT MILESTONES sidebar panel with M1/M2 prices and trim share counts.
- **`risk_workspace.py`** — the exit ladder is one input to the reconciled verdict that leads the asset context window (see §6). The full regime-calculation breakdown (raw ATRs, 200-DMA level vs current price, DMA signal with consecutive-day count, combined regime verdict) and the trim-action prose now live in that panel's demoted **DETAILS** block; the milestone ladder (✓ passed, ◄ current, dim future) sits in the top metric strip.

### Portfolio Risk Report (Menu Option 7)

- **`core/portfolio_analytics.py`** — Pure computation module. Inputs: enriched positions DataFrame. Outputs: `total_stop_out` (Σ Risk_Val × FXRate in NAV currency), `total_r_pct` (Σ risk_pct_nav), `total_e_pct` (Σ NavPct), `headroom`, `pct_budget_used`, HHI concentration index, currency breakdown, breached tickers, unmanaged positions list.
- **`portfolio_risk.py`** — Rich console display: panel header with NAV/count/breach flags, AGGREGATE RISK table, CONCENTRATION (top-5 by exposure and risk), CURRENCY EXPOSURE table, unmanaged positions warning.

---

## 6. Reconciled Verdict & the Asset Context Window

Every open position is judged on **three independent axes**, and the risk workspace reconciles them into a *single* directive rather than showing them raw:

| Axis | Question | Source |
|---|---|---|
| **Exposure / sizing** | Do I have capital room to add? | `audit_position_risk` → `adjustment` (the tighter of the R and exposure constraints) |
| **Risk (R %)** | Is my downside within budget? | same audit |
| **Exit ladder** | A winner at its target — bank or run? | `profit_taking` stage × regime (§5) |

These axes are orthogonal *inputs* but must collapse to one action. Left unreconciled they contradict each other: raising the exposure limit opens sizing room, so the ACTION column would say "+44.7% ADD" while the exit ladder — which is independent of exposure — still says "trim at TP". The ★ in the table is purely a *target marker* (`current ≥ tp_price`); it cannot move with exposure.

### The reconciliation fundamental

> Exposure headroom sizes a **new or early** position. It is never licence to add to a winner that has reached a profit-taking stage.

Precedence, strict order: **breach → exit-stage ladder → sizing add/trim → hold.** (The former "urgent RR-floor exit" tier was removed with the RR efficiency floor — RR is informational only; see §5.) At an exit stage the ladder governs and any exposure headroom is reported but muted ("3.4% exposure room exists, but no adds at target"). This is enforced in both the panel verdict and the table **ACTION** column, so the row and the panel can never disagree.

### Single source of truth

`risk_workspace._exit_recommendation(stage, regime, qty, entry, sl, tp, cur_p, rr, stop_type)` is a **pure function** returning the structured exit directive `{verb, color, headline, shares, pct, restore_sl, reason}` (or `None` when no stage). It encodes M1 (make risk-free, never sell), the exit-shape hooks (§10), and the `TRIM_MATRIX`; RR is not an input to any directive (§5). It drives **all three** consumers — the panel verdict line, the detailed exit-guidance prose, and the table ACTION cell — so the headline action and its justification cannot drift. `_trim_shares()` is the shared whole-share rounding (never rounds a genuine trim to zero, never exceeds holdings).

### Panel layout (verdict-led)

The asset context window (`#position-context`, built in `refresh_risk_checklist`) is ordered by decision weight:

1. **▶ VERDICT** — the one reconciled directive + a one-line rationale (and a `⏳ STALE` nudge when applicable).
2. **Metric strip** — `R · Exp · RR · stop-buffer` on a single line, then the **M1/M2/TP ladder** (`_ladder_str`).
3. **Sizing-impact table** — the `INFO / BAL-BEG / ADD / BALANCE` projection, shown only when there is a real add/trim or an active `+N / -N / BE` model (gated on `net_action ≠ 0`).
4. **DETAILS** — demoted diagnostics: capital-efficiency line, inception stop/ATR with vol delta, R-compliance remediation, and the full regime-calculation breakdown + exit prose.

The verdict is modeling-aware: an explicit `+N / -N` or a `BE` goal-seek overrides the system directive so the panel reflects the user's what-if.

## 7. Entry/Exit Zone Scanner (Menu Option 8)

The Zone Scanner finds where current price sits on a cluster of independent structural levels and converts a flagged zone into a stop and position size. It scans the same universe as the Watch List: open holdings plus `status='WATCH'` prospects.

### Operational Workflow

Launch with menu option **8**. The scan runs across the universe and lists each ticker, sorted flagged-first then by proximity to the nearest level. Select a row to see the full breakdown.

- **TAG** — `ZONE` (a confluence zone), `ZONE-MOMO` (zone in a momentum regime), or `—` (no zone).
- **Detail panel** — the converging signals (each with its ATR-distance and a `★` for fortress-tight levels), the chosen stop and its source, the target, and the share count under each risk preset (Small / Base / Large).

A zone is flagged when **two or more independent** structural levels converge within the confluence band of the current price. Independence is the §4a minimum check: levels sitting within 0.05 ATR of *each other* (e.g. VAL and POC landing on the same volume-profile bucket) count as **one** signal, not two — the signal list still shows every level, but the flag can't be earned by the same wall counted twice.

A ticker with too little price history for the scan window is shown as a dimmed **THIN** row (with its cached bar count in the detail panel) instead of being silently dropped from the report. The scanner header shows the active horizon lens (`lens: default`).

Every scan also **persists each ticker's structural context** (regime, flagged, independent confluence count, stop source, 200-DMA anchor) so the Risk Workspace entry gates evaluate on real scan inputs at commit time — no re-typing, no manual threading. Pressing **`c`** on a flagged row hands the zone off: the next Risk Workspace launch jumps to that ticker and prefills the command box with the scanner's stop as a FIXED price (review it, add `P:/C:/X:` tokens, nothing is committed automatically; the handoff expires after an hour).

### The Signals

For each ticker the scanner computes:

- **Composite Volume Profile** (6-month and 12-month) — POC (point of control), VAH/VAL (value-area bounds holding ~70% of volume), and naked POCs (unretested high-volume shelves). This is a **daily-bar approximation**, not a tick-derived profile — Yahoo Finance exposes no intraday volume-at-price. Each day's volume is smeared across its high-low range weighted toward the close. A footer notes this in the panel.
- **Anchored VWAP** — from the most recent swing low (support) and swing high (resistance).
- **Moving Averages** — 50-day and 200-day.

### Momentum Regime: Dynamic Stop-Tier

For names running far above their longer-term support, a 6-month VAL stop is too distant for a momentum-flag entry (a 20%+ stop). When price is more than the configured premium above the 6-month VAL, the ticker enters a **Momentum Regime**:

- The stop drops to **micro-structure** from the last ~2 weeks of bars. Four anchor types are considered below price and the **tightest** (nearest below price) wins, placed a small ATR buffer beneath it:
    - **`VAL_14d`** — the micro volume-profile value-area low.
    - **`HVN_14d`** — the nearest **high-volume node** below price (a heavy volume shelf; tighter and more precise than the VAL edge).
    - **`AVWAP_14d`** — an AVWAP anchored to the most recent swing low *inside* the window.
    - **`GAP_14d`** — the **floor of the most recent breakout gap** (the pre-gap high; only gaps ≥ 0.5 ATR count). A clean fill of the gap undoes the move that started the leg.
- The row is tagged **`ZONE-MOMO`** and the winning stop source is shown (e.g. `stop=206.15 (HVN_14d)`).
- A clean break of that micro level means the parabolic move is broken — the exit signal.

  > The `HVN` and `GAP` anchors are the **v2** stop-tier additions. The `VAL`/`HVN`/`GAP` thresholds are tuned by `MICRO_STOP_BUFFER_ATR`, `HVN_MIN_PROMINENCE`, and `GAP_MIN_ATR` in `constants.py`. Operator-facing reading guide: `docs/guides/Zone_Scanner_Guide.md`.

Names not extended above their 6-month VAL stay in the normal regime (`ZONE`) and use their true structural support.

### Technical Implementation Details

- Confluence is measured in **ATR units**; the percent confluence band is converted to ATR per ticker so one threshold works across price scales.
- The stop is the nearest invalidating support below price (tightest of VAL / anchored-VWAP), or the momentum micro-structure in a momentum regime (tightest of micro VAL / high-volume node / swing-low AVWAP / breakout-gap floor); targets follow the existing reward framework (next naked POC, else the 3:1 reward floor).
- Position size is computed under all three presets via the existing dual R%/exposure-constraint sizer; NAV comes from the broker snapshot.
- Engine: `core/zone_scan.py` (orchestrator), `core/volume_profile.py`, `core/anchored_vwap.py`, `core/confluence.py`. UI: `ui/zone_scan_workspace.py`. The scan is read-only — it never writes to the database.

---

## 8. Price Chart & Interactive Hover (`G` key)

Pressing **`G`** in any of the three workspaces (Risk, Watch List, Zone Scanner) launches a 5-year Price + 200-DMA chart for the highlighted position. The chart runs as a standalone subprocess (`ui/chart_worker.py`), so it has its own window and does not block the terminal UI.

### Interactive Readout

Move the cursor across the chart to read off exact values:

- A dashed vertical **crosshair** snaps to the nearest trading day under the cursor, with a dot on the price line.
- A **tooltip** shows that day's **date**, **Price**, and **200 DMA**. The 200 DMA reads `n/a` for the first 199 bars, where it is not yet defined.
- The tooltip flips to the left of the cursor in the right ~40% of the chart, so it never spills off the right edge.

The readout is sourced directly from the same series that are plotted, so the displayed values always match the lines. Implementation: `chart_worker._attach_hover` (pure matplotlib `motion_notify_event` — no extra dependency).

---

## 9. In-App Help & Guides (`F1`)

The **`F1` Help Desk** (Risk Workspace and Dashboard) is a tabbed reference rendered directly from the project's Markdown guides — there is no separate, hand-maintained help copy. Editing a guide updates the in-app help automatically.

- Tabs (in order): **User Guide** (`docs/guides/User_Guide.md`), **Glossary** (`Indicator_Glossary.md`), **Stop Playbook** (`Stop_Placement_Playbook.md`), **Entry & Stops** (`Entry_and_Stop_System.md`), **Exit Strategy** (`Exit_Strategy.md`), **Zone Scanner** (`Zone_Scanner_Guide.md`), **Horizon 3-6mo** (`Horizon_Calibration_3to6mo.md`), **Strategy Lab** (`Strategy_Lab_Syntax.md`), and **Technical** (this document).
- `docs/guides/User_Guide.md` is the **task-level operating manual** — the front-door tab: screen index, key bindings, and how-to walkthroughs for the full trade lifecycle (new entry, add-on-dip, profit-taking, stop-out, earnings gap what-if, portfolio heat reduction, raise-cash order, journal capture). It owns procedure only; strategy rationale stays in the strategy guides it cross-references.
- `docs/guides/Indicator_Glossary.md` is the **canonical home** for every indicator and metric definition (ATRs, volume profile, AVWAP, R / RR, confluence, regimes, the momentum micro-anchors, presets). Other surfaces reference it rather than restating definitions.
- `docs/guides/Stop_Placement_Playbook.md` is the scenario-by-scenario walkthrough for arriving at a stop, including the momentum "price sitting on the low" case where the scanner cannot offer a tight stop.
- Source/rendering: `services/ui_components.py` (`HelpScreen`, `HELP_FILES`).

---

## 10. Entry & Stop System — Pre-Trade Controls (Risk Workspace)

The Risk Workspace Strategy Lab command line carries optional per-trade controls from the **Entry & Stop Selection System**. All are **additive and default-off** — a command that uses none of them behaves exactly as before.

Full syntax: `VALUE [F/T] [P:S/B/L] [R:x] [E:x] [TP:n] [C:TH/TE] [G:gap] [X:H/T] [SRC:name] [THM:theme]`

- **`C:` — Trade classification (THESIS / TECHNICAL).** `C:TH` tags the trade THESIS, `C:TE` TECHNICAL, `C:-` clears it. The tag is carried on the position and shown as a chip in the panel header. It is **information only** — no exit logic branches on it. A classified commit also writes to the decision journal (`trade_log`) — **one row per open lot**: re-committing the same position updates its open row rather than appending a duplicate (duplicates would double-count the lot in the expectancy report); once the lot's outcome is backfilled, the next commit starts a fresh row. **§0a coupling:** `C:TH` with no explicit `X:` token (and no stored non-default shape) auto-applies the **thesis-exit** shape — one clock per trade, no guessed-at-entry price target. Override any time with `X:L` or `X:H`.
- **`SRC:` / `THM:` — Idea source and theme (§0a, §7).** Single uppercase tokens (`SRC:ZACKS THM:SEMIS`) that ride the commit into the decision journal — journal-only, never stored on the risk profile. A commit carrying `SRC:` or `C:` writes the journal row (date, source, theme, classification, entry, stop, R₁); the outcome fields are backfilled automatically when the position closes (§11).
- **`X:` — Exit shape (§5a).** How the trade is *banked*, decided at entry alongside the stop. Two shapes beyond the default:
    - `X:H` **Hard target** — a defined objective (TECHNICAL): bank the full position at the target, no runner.
    - `X:T` **Thesis exit** — **no price target**: the position carries no TP and is exited on the stop or a broken thesis only.
    - `X:-` reverts to the default ladder — which already *is* scale-out-plus-runner (partial at the objective, runner behind the trailing stop). `X:R` remains accepted as a legacy alias of that default (it was never behaviourally distinct and is no longer presented as a shape). The chosen shape shows as a chip in the panel header. **There is no time stop** — no shape forces an exit on elapsed time.
- **`G:` — Gap-aware sizing (§6).** `G:340` supplies a plausible post-event gap price. For a prospect, sizing then risks against the **larger** of R₁ and `R_gap = entry − gap_price` (i.e. the lower of the stop and the gap price), which shrinks the size for names held through an event. Omitting `G:` keeps the standard fixed-fractional size. A `GAP-SIZED @ …` chip shows while modelling.

### Entry Gates (advisory-first)

On commit, the workspace can run the **eight entry gates** (G1 stop-width, G2 basis quality, G3 fallback-artifact, G4 event, G5 extension, G6 liquidity, G7 portfolio heat, G8 base-currency). Each returns **PASS / FAIL / NA** with a reason; a gate whose inputs are unavailable returns NA and never blocks. Two spec deviations (assessment review, 2026-07-04): **G6 is a permanent NA stub** — no ADV/slippage source feeds this book and none is worth building; **G7 evaluates portfolio heat only** — the spec's theme dimension is cut until themes exist somewhere in the app.

**Where the gate inputs come from (advisory build):**

- **G1** tests the stop width against a fixed, *named* market ATR from the discovery cache — the daily **14d** ATR by default, the weekly **12w** ATR with a wider ~18% cap under the `position_3to6mo` lens (so the lens's own correct wide stops are never rejected). It never tests against the snapped inception ATR, which sits near the risk distance by construction.
- **G2 / G3 / G5** read the ticker's **structural context from the latest zone scan** (stop source, flagged status, independent confluence count, regime, 200-DMA trail anchor), persisted automatically every time the Zone Scanner runs. Context older than ~a week is treated as absent — stale structure degrades the gates to NA, it never misfires.
- **G7** reads the book's existing open R% across the other stopped positions.
- **G4** stays NA (no earnings-calendar source); **G6** is the cut stub.

Practical flow: run the Zone Scanner (menu 8) first, then commit in the Risk Workspace — with `gates_mode = advisory`, every commit gets a PASS/FAIL/NA read on real inputs, and a FAIL is a warning, never a block.

Controlled by the **`gates_mode`** setting, edited in the preset/settings modal (`M`):

- **`off`** (default) — no gate evaluation; commit behaviour unchanged.
- **`advisory`** — failing gates are surfaced as a warning, but the commit proceeds.
- **`blocking`** — a commit with any failing gate is blocked.

The active mode and calibration lens are always visible in the workspace header (`gates: off · lens: default`), so the current configuration never has to be remembered.

Thresholds live in `constants.py` (`GATE_*`) and are meant to be tuned from the log. Engine: `core/gates.py`.

---

## 11. Expectancy Report (Menu Option 9) & Horizon Calibration

### Expectancy Report

Menu option **9** renders the decision journal (`trade_log`) and is also its **capture point** (§7). Before the report renders, `core/outcome_backfill.py` runs an **automated pass** — filling realized R, MAE/MFE, and result-vs-benchmark on closed lots and refreshing skipped picks against the benchmark to date. The report itself is a pure read; after it renders, a small action loop offers manual journal writes for anything the automated pass could not settle:

- **`B` — backfill closed lots.** Open journal rows whose position has since closed are listed with a **ledger-suggested realized R** — `(qty-weighted average SELL price − entry) / R₁` from the `trades` table. Enter accepts the suggestion, a typed value overrides it, `s` skips. Nothing is written unconfirmed; rows without usable geometry fall back to manual input.
- **`K` — log a skipped source pick** (§0a): ticker, source (defaults to Stansberry), optional note; the entry price is auto-resolved from Yahoo when possible so the funnel benchmark has an anchor. Works even when the journal is empty — this is how it stops being dark.

- **By archetype** — win rate, average win / average loss (in R), and **E[R] = w·W̄ − (1 − w)·L̄**. Each archetype is flagged *proven* / *unproven* against the `EXPECTANCY_THRESHOLD_R` (+0.20R); an `ALL` row aggregates.
- **Source vs benchmark** — for each source: trades taken vs **skipped picks**, average realized R, average result-vs-benchmark, and average base-currency return. This answers the funnel question: does the source add edge, net of cost?
- **Base-currency return** — total and average realized return in the book's base currency over closed trades.

Empty and short logs are handled gracefully. Engine: `core/expectancy.py`; view: `ui/expectancy_report.py`.

**Automated outcome backfill (`core/outcome_backfill.py`).** Opening the report first runs the backfill that closes the §7 loop, so the journal's outcome fields never depend on manual entry:

- **Closed TAKEN rows** (`realized_r` NULL): the position's close is detected from the `trades` ledger — the first quantity zero-crossing after the log date, mirroring `LedgerEngine` sign conventions (reset-on-zero re-entries and prior lots are excluded; a **split inside the window bails out** rather than compute a wrong R). Exit price = qty-weighted average of the close-out sells. Writes `realized_r = (exit − entry)/R₁`, `mae_r`/`mfe_r` (worst/best excursion in R from cached daily bars), and `result_vs_benchmark` (pick return − benchmark return over the same window).
- **SKIPPED rows**: `result_vs_benchmark` is refreshed *to date* on every run — the funnel verdict for picks not taken.
- **Benchmark**: the `benchmark_ticker` setting (default `SPY`), cached in `prices.db` under the pseudo-conid `BENCHMARK:<ticker>`.
- `realized_return_base` is deliberately **not** backfilled: the FX rate at exit is not recorded, and today's rate would fabricate history. NULL until an FX-at-exit source exists.

Unresolvable rows (still open, missing entry/stop/conid, mid-window split) are counted and left untouched — never guessed. A summary line prints before the report.

**Feeding the journal.** Taken trades: commit with `SRC:`/`C:` in the Strategy Lab (§10). Skipped picks: the Watch List **`L` key** opens a small form (ticker prefilled from the selected row, source required, theme optional) and writes a `SKIPPED` row with today's date and the best available price — the pick need not be on the watch list.

### Horizon Calibration Lens

The Zone Scanner reads a **`calibration_profile`** setting that selects the horizon lens:

- **`default`** — today's short-swing calibration (daily structure). Unchanged.
- **`position_3to6mo`** — the 3-to-6-month position lens. What it changes in the scan today: a longer-horizon ATR (approximated as a longer *daily* window — true weekly resampling is deferred), longer volume-profile lookbacks, a wider confluence band, and the **MOMENTUM override** — a momentum flag is read as *"extended, wait for a weekly pullback"*, so the scanner uses the weekly value anchors instead of a tight micro-stop. The profile also *records* the spec's percent bands (buffer ~3–7% of price, stop width ~10–18%) and the 30-week-MA anchor, but these are **not yet enforced** anywhere — they are metadata awaiting wiring.

The profile changes the **lens** (timeframe / smoothing) only; it adds no time stop. Switch it in the Risk Workspace **preset/settings modal (`M`)** — the `calibration_profile` row next to the gates row (values: `default` / `position_3to6mo`). The active lens is always visible in the risk-workspace and zone-scanner headers (`gates: off · lens: default`). Engine: `core/calibration.py` (`CalibrationProfile`, `get_calibration`).

**§1a staleness check (lens only):** when ATR discovery loads under `position_3to6mo` and the daily 14d ATR exceeds ~0.7× the weekly 12w ATR (the normal ratio is ~0.45 by √5 time-scaling), the workspace warns that short-term volatility has left the weekly baseline behind — re-scan the structure before trusting lens-scale stops.
