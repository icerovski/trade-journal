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

For TRAILING stops the ladder deliberately uses the **inception ATR, not the live trailing distance**. The live ATR governs only where the *stop* sits; using it for the reward ladder made the milestones drift away as volatility expanded (e.g. AVGO: live ATR 88 vs inception 57 pushed M1 to entry+88 ≈ 449, mislabelling a +33% winner as an early stage). The TP is also **entry-anchored, not stop-anchored** — anchoring to the ratcheted stop made it collide with M2 at inception. In a confirmed trend the TP is extended manually via the TP-stage guidance, not automatically.

| Stage  | Trigger                    | Action                         |
|--------|---------------------------|-------------------------------|
| PRE-M1 | price < entry + 1×ATR     | Hold — position not yet earned |
| M1     | price ≥ entry + 1×ATR     | Raise stop to entry (free position) |
| M2     | price ≥ entry + 2×ATR     | Partial trim by regime         |
| TP     | price ≥ entry + 3×ATR     | Larger trim by regime; extend target in TREND |

**Efficiency Floor (overrides all stages):** If RR (Efficiency) drops below 1.0 at any time, exit all remaining shares. This fires when price reverses toward the stop from the TP zone — remaining reward no longer justifies open risk.

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
- **`risk_workspace.py`** — PLAN section shows full regime calculation breakdown: raw ATRs, ratio with threshold verdict, 200-DMA level vs current price, DMA signal with consecutive-day count, combined regime verdict, milestone ladder (✓ passed, ◄ current, dim future), and trim action with share count.

### Portfolio Risk Report (Menu Option 7)

- **`core/portfolio_analytics.py`** — Pure computation module. Inputs: enriched positions DataFrame. Outputs: `total_stop_out` (Σ Risk_Val × FXRate in NAV currency), `total_r_pct` (Σ risk_pct_nav), `total_e_pct` (Σ NavPct), `headroom`, `pct_budget_used`, HHI concentration index, currency breakdown, breached tickers, unmanaged positions list.
- **`portfolio_risk.py`** — Rich console display: panel header with NAV/count/breach flags, AGGREGATE RISK table, CONCENTRATION (top-5 by exposure and risk), CURRENCY EXPOSURE table, unmanaged positions warning.
