# Technical Documentation: Trade Journal & Risk Management

This document serves as the "Single Source of Truth" for the technical implementations and operational workflows of the system.

---

## 1. Institutional Prospect Simulator & Watch List

The Prospect Simulator allows for the analysis and simulation of potential stock purchases using existing institutional risk frameworks before capital is committed.

### Operational Workflow
1.  **Ticker Discovery**: Within the **Risk Workspace** (Option 2 -> 1 from main menu), use the **"Discover Ticker"** input field.
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

### Exit Stages

Milestones are anchored to `entry_price + N × R`, where `R` is the **inception ATR** (the ATR/risk unit at first entry) for **both** stop types. The ladder is uniform — M1=+1R, M2=+2R, TP=+3R from entry — and measures profit in *R-multiples*. Falls back to `entry − final_sl` if inception_atr is unavailable.

How `R` is sourced differs by stop type, because the two take different inputs. For **TRAILING** the user supplies an ATR *distance* directly, and that distance is `R`. For **FIXED** the user supplies a stop *price*, not a distance, so there is no ATR to read — the commit path snaps the **risk distance `entry − stop`** to the nearest of the four discovery-timeframe ATRs (daily/weekly/monthly/quarterly) and stores that as `R`. This makes the ladder run on the volatility horizon that matches how the stop was sized: a deliberately deep stop (e.g. a leveraged ETF) lands on quarterly, so its milestones sit far enough out that the ladder doesn't fire on noise. The earlier behaviour — hardcoding the *daily* ATR for every FIXED stop — mis-scaled the ladder on deep stops (UDOW: daily ATR 1.86 vs a 21.5-point stop tripped M1 at a +2.8% gain).

For TRAILING stops the ladder deliberately uses the **inception ATR, not the live trailing distance**. The live ATR governs only where the *stop* sits; using it for the reward ladder made the milestones drift away as volatility expanded (e.g. AVGO: live ATR 88 vs inception 57 pushed M1 to entry+88 ≈ 449, mislabelling a +33% winner as an early stage). The TP is also **entry-anchored, not stop-anchored** — anchoring to the ratcheted stop made it collide with M2 at inception.

**TP override (`risk_profiles.tp_atr_mult`).** Once a winner runs past the default +3R the ladder is maxed out. A per-position override extends the *top rung* to any multiple of the **same frozen inception ATR** (`TP = entry + tp_atr_mult × inception_ATR`); M1/M2 stay at +1R/+2R. Because it is anchored to the frozen ATR, the target stays put when the live stop ATR is later tightened — editing the stop never moves it. `NULL` = the default `TP_ATR_MULTIPLE` (3R). Set it from the risk workspace with `TP:n` (see below); the engine reads it in `calculate_position_risk`, and `compute_exit_milestones` warns if an override lands at/below M2 (< 2R, a non-monotonic ladder).

**Setting the target — `TP:n` command.** Four input forms, all resolved to a multiple of the inception ATR by `resolve_tp_mult`: `TP:4`/`TP:4R` (R-multiple), `TP:+35%` (gain as % of entry ÷ ATR), `TP:$60K`/`TP:$60000` (absolute profit ÷ qty ÷ ATR; needs a share count), and `TP:-` (clear → default 3R). When an override is active the audit panel shows a **TARGET** line with the **forward** reward:risk `(target − price)/(price − stop)`, flagged `⚠ below 3:1` when it falls under `RR_SETUP_FLOOR` (3.0) — the honest "what am I paid to keep holding from here" check (it reads low for a run-up winner whose stop already sits above entry, which is expected once entry risk is gone).

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
- **`core/profit_taking.py`** — `enrich_regime(positions, mapper)` sets `trend_regime`, `regime_dma`, `regime_dma_signal`, `regime_dma_days`, `regime_dma200` on each position via the 200-DMA consecutive-rising-days signal (TREND gated on price > 200-DMA). `TRIM_MATRIX` holds the `(stage, regime) → (fraction, rationale)` guidance. Called as step 4 in `portfolio_manager.get_dashboard_df()`.
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

Precedence, strict order: **breach → urgent RR-floor exit → exit-stage ladder → sizing add/trim → hold.** At an exit stage the ladder governs and any exposure headroom is reported but muted ("3.4% exposure room exists, but no adds at target"). This is enforced in both the panel verdict and the table **ACTION** column, so the row and the panel can never disagree.

### Single source of truth

`risk_workspace._exit_recommendation(stage, regime, qty, entry, sl, tp, cur_p, rr, stop_type)` is a **pure function** returning the structured exit directive `{verb, color, headline, shares, pct, restore_sl, urgent, reason}` (or `None` when no stage). It encodes M1 (make risk-free, never sell), the FIXED-only RR efficiency floor (§5), and the `TRIM_MATRIX`. It drives **all three** consumers — the panel verdict line, the detailed exit-guidance prose, and the table ACTION cell — so the headline action and its justification cannot drift. `_trim_shares()` is the shared whole-share rounding (never rounds a genuine trim to zero, never exceeds holdings).

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

A zone is flagged when **two or more** structural levels converge within the confluence band of the current price.

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
