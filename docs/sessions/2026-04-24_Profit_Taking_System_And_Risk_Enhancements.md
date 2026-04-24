# Session: Profit-Taking System & Risk Enhancements

**Date:** 2026-04-23 / 2026-04-24
**Commits:** `6837b24`, `b3ce68f`, `b0102fc`, `7e6c5c6`, `bffd782`, `fb0f6d8`

---

## Objectives

1. Remove Scale-In entry type across the entire system.
2. Improve the sizing table in the Risk Workspace (SL%, P/L@Stop rows).
3. Add a Portfolio Risk aggregate report (menu option 7).
4. Design and implement a profit-taking system with exit stage milestones and trend regime detection.

---

## Technical Changes

### 1. Scale-In Removal

- **`risk_workspace.py`** — Removed all Scale-In UI: ticker badge, `S0`/`S` parser tokens, `hypo_scale_step` / `hypo_entry_type` parameters, SCALE_IN branch in execution plan, Pilot Stop line, `calculate_pilot_entry` call, `target_outlay` / `remaining_cap` references. Input placeholder updated. Drafts dict no longer stores `entry_type` or `scale_step`.
- **`core/risk_engine.py`** — `calculate_pilot_entry` method removed entirely.
- **`services/ui_components.py`** — Visual Glossary and Strategy Lab help text cleaned of all Scale-In references.
- **`db.py`** — Migration added: converts any existing `SCALE_IN` rows to `SINGLE` on startup. DB columns preserved for schema compatibility.
- **`main.py`** — Watch list summary table simplified (removed STRATEGY and STEP columns).
- **`tools/reconstruct_inception_risk.py`** — Hardcoded `entry_type='SINGLE'`, `scale_step=0.5`.

### 2. Sizing Table Enhancements (`6837b24`, `b3ce68f`, `b0102fc`, `7e6c5c6`)

- **Renamed `LIM` column → `INFO`** for clarity.
- **Added `SL%` row**: distance from stop to base price as a percentage.
  - TRAILING: `effective_atr / max_since_entry × 100` (ATR as % of HWM — matches the portfolio grid formula).
  - FIXED: per-column formula (`entry − stop) / entry`, `(cur_p − stop) / cur_p`, `(new_entry − stop) / new_entry`.
- **Replaced `Buf%` row with `P/L@Stop` row**: buffer % cannot be affected by a sizing transaction (neither input changes), so it was dropped. P/L@Stop shows `(stop − entry) × qty × multiplier` for each column — colored green (locked profit) or red (loss at stop).
- **`Buf%` BALANCE column**: previously showed same value as BAL-BEG (mathematically correct but confusing) — resolved by dropping the row entirely.

### 3. Portfolio Risk Report — Menu Option 7 (`bffd782`)

- **`core/portfolio_analytics.py`** (new): Pure computation module. Takes the enriched positions DataFrame and returns aggregate metrics: `total_stop_out` (Σ Risk_Val × FXRate in NAV currency), `total_r_pct` (Σ risk_pct_nav), `total_e_pct` (Σ NavPct), `total_budget` (Σ MaxRPct), `headroom`, `pct_budget_used`, HHI concentration index, currency breakdown, breached tickers, unmanaged positions list.
- **`portfolio_risk.py`** (new): Rich console display. Sections: Panel header with NAV/count/breach flags, AGGREGATE RISK table, CONCENTRATION (top-5 by exposure and risk side-by-side via `Columns`), CURRENCY EXPOSURE table, unmanaged positions warning.
- **`main.py`** — Added `[7] PORTFOLIO RISK` menu entry and `handle_portfolio_risk()` handler.

### 4. Profit-Taking System (`fb0f6d8`)

#### Exit Stages — `core/risk_engine.py` (section 8 of `calculate_position_risk`)

Milestones anchored to `entry_price + N × ATR_distance`:
- FIXED stop: `atr_dist = inception_atr` (falls back to `entry − final_sl`)
- TRAILING stop: `atr_dist = atr` (live dollar trail width)

| Stage | Trigger | Action |
|---|---|---|
| PRE-M1 | price < entry + 1×ATR | Hold |
| M1 | price ≥ entry + 1×ATR | Raise stop to entry |
| M2 | price ≥ entry + 2×ATR | Partial trim by regime |
| TP | price ≥ stop + 3×ATR | Larger trim by regime |

#### Trend Regime — `core/portfolio_manager._enrich_regime` (step 4 of `get_dashboard_df`)

Two signals:
1. **Q/W ATR ratio** = `quarterly_atr / weekly_atr` (Wilder 12-period, from `prices.db`). Neutral baseline ≈ 3.5 (√13 scaling). > 4.5 = additive weekly moves (trending). < 3.0 = canceling weekly moves (choppy).
2. **200-DMA direction**: counts consecutive days the DMA itself moved in the same direction. Change per day = `(today − close_200d_ago) / 200` — robust to single bad sessions. BUY fires at ≥ 21 consecutive rising days.

| Regime | Q/W Ratio | 200-DMA | Trim M2 | Trim TP |
|---|---|---|---|---|
| TREND | > 4.5 | BUY ≥ 21d | 15% | 20% |
| NORMAL | 3.0–4.5 | BUY ≥ 21d | 33% | 33% or close |
| RANGING | < 3.0 OR | Not BUY | 50% | Close all |

RANGING fires if either condition fails.

#### New `Position` fields (`models.py`)

`exit_stage`, `m1_price`, `m2_price`, `trend_regime`, `regime_ratio`, `regime_dma`, `regime_weekly_atr`, `regime_quarterly_atr`, `regime_dma200`.

#### Display

- **Risk Workspace PLAN section** (`risk_workspace._exit_guidance_str`): full calculation breakdown — raw ATRs, ratio with threshold verdict, 200-DMA level vs current price, DMA signal with consecutive-day count, combined verdict, milestone ladder (✓ passed, ◄ current, dim future), trim action with share count.
- **Dashboard** (`dashboard.py`): EXIT column showing `M2·T`, `TP·N` etc. for actionable stages; EXIT MILESTONES in sidebar with M1/M2 prices and share count guidance.
- **F1 Help → Exit Strategy tab** (`services/ui_components.py`): regime and stage reference tables, plain-language explanations below each.

---

## Logic & Decisions

**Why remove Scale-In?** The complexity of multi-stage scale-in roadmaps added UI and calculation overhead without a clear gain in practice. Single-target sizing against dual constraints (R% + E%) is sufficient and cleaner to audit.

**Why `inception_atr` for FIXED stop milestones?** The FIXED stop stores a price, not a distance. `inception_atr` is the ATR at entry — the original risk unit — making milestones consistent with what was accepted at trade initiation.

**Why Q/W ATR ratio rather than daily/weekly?** The user manages positions using quarterly ATR for stops, so regime detection on the same timeframe is more internally consistent. The quarterly/weekly pair also captures whether weekly moves are additive across the quarter, which is a more meaningful trend signal than whether daily moves are additive within a week.

**Why the DMA counts consecutive days of the DMA's own movement, not price above DMA?** The DMA's direction is a more stable signal — a single bad session barely moves a 200-period average. The 21-day confirmation prevents false signals during recoveries.

**Why RANGING fires on either condition failing?** The DMA is the dominant structural signal. A high ATR ratio in a stock with a declining or flat 200-DMA indicates volatility without direction — that is a RANGING environment regardless of momentum.

---

## Verification

- All new `Position` fields confirmed present in `to_dict()` output.
- `_compute_regime_atr()` returns correct Wilder ATR from test DataFrame.
- `_exit_guidance_str()` renders correct milestone ladder, regime breakdown, and trim guidance for a simulated M2/TREND position.
- `ui_components.py` parses cleanly (UTF-8 confirmed).
- All 42 existing tests unaffected.

---

## Next Steps

- Phase 2 portfolio analytics: portfolio beta vs SPY, historical VaR, correlation matrix, stress scenarios.
- Runner tracking: detect whether a position has already been partially trimmed to refine trim share count.
- Consider extending TP target to `stop + 3×weekly ATR` in TREND regime as an automated option.
