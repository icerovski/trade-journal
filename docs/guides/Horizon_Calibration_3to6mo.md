# Horizon Calibration — 3-to-6-Month Holds

An overlay on the **Entry & Stop Selection System**. The base system and the *Stop
Placement Playbook* are silently calibrated to **short swings** (daily ATR, a 14-*bar*
≈3-week micro window, a 0.25×daily-ATR buffer ≈1.3%). On a multi-month thesis that
machinery shakes you out before the trade works. This file retunes every horizon-sensitive
parameter for an average **60–130 trading-day hold** and overrides the parts that are the
wrong tool at this horizon.

> Use this as your personal config. Where it conflicts with the base files, **this wins**.

---

## 1. The timeframe shift — daily → weekly everywhere

The single biggest change: the structural coordinate system moves up one timeframe.

| Base system uses (daily) | At a 3–6mo hold, use (weekly) |
|---|---|
| Daily ATR (e.g. 19.64) | **Weekly ATR** ≈ 2–2.5× daily (≈44 on the same name) |
| 14-bar micro window (~3 wks) | **14–26 *week* range** / multi-month base |
| `GAP_14d` / `HVN_14d` micro-anchors | Major **HVN / gap** on the weekly; ignore 3-week shelves |
| 14-day swing-low AVWAP | **Major AVWAP**: prior major low, YTD, earnings-gap anchor |
| 50/200-DMA | **30-week MA** (≈150d) and 200-DMA as the weekly trend rails |
| 0.25 × daily ATR buffer | **0.25–0.5 × weekly ATR** (≈3–7%, not ~1.3%) |

Rule: if a level lives on a chart you'd never zoom out to over a 6-month hold, it's noise.
Anchor the stop to structure visible on the **weekly**.

---

## 1a. Choosing the ATR period — and why the multiplier must move with it

If you anchor volatility to a **12- or 24-month ATR** (ATR over 12 / 24 *monthly* bars),
read this before using any "× ATR" rule in this file.

**The trap: ATR timeframe and multiplier are coupled.** A 12/24-month ATR measures your
typical *monthly* swing — often **15–25% of price**, far larger than the weekly ATR the §1/§4
multipliers were tuned to. Plugging it into "1.5 × ATR" gives a ~30%+ stop-width cap; into
"0.5 × ATR" gives a ~10% buffer alone. **Keep the long ATR → shrink the multipliers
proportionally.**

**The fix: reason in percent of price, not ATR-multiples.** ATR is only the estimator.
Target these bands directly for a 3–6mo hold (tune from your log), then back out whatever
multiplier your chosen ATR implies:

| Use | Target band (% of price) | If monthly ATR(12/24) ≈ 18% of price → multiplier |
|---|---|---|
| Stop buffer beneath anchor | **3–7%** | ≈ 0.17–0.39 × ATR |
| Total stop width (entry→stop) | **10–18%**, cap ~18–20% | ≈ 0.6–1.0 × ATR (cap ~1.1 ×) |
| Extension gate (above trail anchor) | **15–20%** | ≈ 0.8–1.1 × ATR |

The band is the rule; the multiplier just falls out of whatever ATR you picked.

**The 24-month staleness check (directional).** A 2-year ATR is stable for consistent sizing
but lags regime shifts. The dangerous direction is when **current vol has risen above the
2-year average**: the long ATR then *understates* today's noise, your buffer comes out too
tight, and ordinary moves stop you out. So:

> If recent realized vol (last 1–3 months) is materially above what the 12/24-month ATR
> implies, **widen the buffer toward the recent read.** When recent vol is *below* the long
> average, the long ATR only makes you slightly conservative — harmless. Keep 24-month as the
> stable base; never let it blind you to a vol expansion you're holding through.

A 12/24-month ATR also confirms §2: you are a position trader. Long-term value/trend
structure is home; the daily/14-bar micro machinery does not apply to you at all.

---

## 2. Regime override — your home is NORMAL/value, not MOMENTUM/micro

The MOMENTUM branch (Playbook Scenario B, and the Scenario C edge case) exists to make
stops *tight* so you can size *big* on a fast move. That is the **opposite** of what a
multi-month hold needs — you need room to survive normal pullbacks. So:

- **Default to the NORMAL regime logic (Scenario A)** with weekly value anchors
  (`VAL_6mo/12mo`, 30-week MA, major AVWAP). This is your home.
- **When a name flags MOMENTUM (>10% over VAL_6mo), do NOT take the tight 14-day stop.**
  Read the flag as *"extended — don't chase."* Instead:
  - **wait** for a pullback to a weekly anchor (30-week MA, prior breakout level, value
    reclaim), then enter there with a weekly-structure stop; or
  - if you enter anyway, **use the weekly-structure stop regardless** — accept the wider
    stop and the smaller size it forces (§5). Never let the scanner's micro-stop set your
    size on a multi-month position.
- **Scenario C (mid-air, nothing below) is still NO new trade** — even more so here. A
  3–6mo entry needs a defended weekly level beneath it; mid-air after a drop has none.

---

## 3. Recalibrated stop anchors (tightest → loosest, weekly)

1. **Weekly breakout level / gap floor** of the base you're trading.
2. **Prior weekly swing low** of the current leg — the obvious "lower low = broken".
3. **30-week MA** (rising) — the classic position-trade trend rail; 200-DMA as last line.
4. **`VAL_6mo` / `VAL_12mo`** — the broad "left the value range" line.

Add a **0.25–0.5 × weekly-ATR** buffer beneath the chosen level. Expect resulting stops of
roughly **10–18%** off entry — that is *normal* at this horizon, not a red flag.

---

## 4. Recalibrated gates (overrides §4 of the base system)

| Gate | Base default (short swing) | **3–6mo override** |
|---|---|---|
| G1 width | `R₁ ≤ 1.5 ATRd` and `≤ 8%` | `R₁ ≤ 1.5 × **ATR-weekly**` and `≤ **~18%**` |
| G2 basis | ≥2 confluent within 0.25 ATRd | ≥2 confluent within **0.5 × ATR-weekly**, on the **weekly** |
| G4 event | no entry within 5d of earnings | timing rule unchanged, **but gap risk is now a sizing input, not avoidable** (§6) |
| G5 extension | not > 2 ATRd above trail anchor | not > **2 × ATR-weekly** above the **30-week MA** |
| time stop | N bars | **N weeks**, tied to your catalyst window (§7) |

G6 (liquidity) and G7 (portfolio heat) are unchanged in form but **bind harder**: longer
holds overlap in time and across market cycles, so correlated drawdown risk is larger. Keep
the heat cap strict.

---

## 5. The sizing consequence — this is arithmetic, not preference

Same risk budget, wider stop → **smaller size**:

```
risk_budget$ = f × NAV          (f unchanged, e.g. 0.25%–1.0%)
qty          = risk_budget$ / R₁
```

If R₁ widens from ~8% to ~16% of price, **qty halves** for identical dollar risk. So a
3–6mo program naturally holds **fewer, higher-conviction names**, each with room to breathe.
Do not "fix" the smaller size by tightening the stop back to a daily level — that just
reintroduces the shakeout you're trying to avoid. A right-sized small position that survives
the thesis beats a big one stopped out in week one.

---

## 6. Earnings & gaps are unavoidable — price them in from day one

Over 3–6 months you will hold through 1–2 reports. You can't dodge it, so **size off the
gap, not the level**:

```
R_gap = entry − plausible_post-earnings_gap_price
qty   = risk_budget$ / R_gap        (use the larger of R₁ and R_gap)
```

If pricing in a realistic gap makes the position uneconomically small, that's the signal the
name is too volatile to hold through events at your risk budget — pass, or wait for a
post-earnings entry where the gap is behind you (an earnings-gap AVWAP is a strong anchor).

---

## 7. Management at this horizon

- **Trail on the weekly, late.** Keep the initial structural stop fixed (`P F`) while the
  thesis is "weekly level holds." Only switch to trailing (`@P T`) after real progress, and
  trail beneath the **rising 30-week MA or weekly swing lows** — never daily structure.
- **Never react to daily noise.** A 5–8% intraweek dip in an intact weekly uptrend is signal
  of nothing. Decisions are made on **weekly closes**.
- **Time stop in weeks.** If the catalyst window passes and price has made no structural
  progress in N weeks (e.g. 8–12), the capital is dead — exit on opportunity cost even if the
  price stop is untouched. This matters more than the price stop on long holds.
- **Migrate stops up only to new weekly structure;** never widen a live stop.

---

## 8. AVGO re-run at a 3–6mo horizon

Same cache (price 365.02, daily ATR 19.64, +25.5% over VAL_6mo, sitting on the lows):

- **Regime override (§2):** flagged MOMENTUM = *extended, don't chase*. Mid-air after a drop
  = no defended weekly level below → **NO new trade. Wait for a pullback to weekly structure**
  (30-week MA / value reclaim) or a base to form.
- **If already held:** the live invalidation is a buffer under the nearest **weekly** rail
  — e.g. 0.25–0.5 × weekly ATR beneath the 200-DMA/30-week MA, a stop in the low-to-mid 300s,
  *not* a daily 357. Reassess on the weekly close, not the daily.

---

## 9. Quick card (overrides the base card)

1. Work off the **weekly**. Daily levels are noise.
2. Default NORMAL/value. MOMENTUM flag = "extended, wait for a weekly pullback."
3. Stop = weekly anchor (swing low / 30-wk MA / VAL) + 0.25–0.5 weekly-ATR buffer (~10–18%).
4. Size = `f×NAV / R₁`, and re-check against `R_gap` for earnings. Expect smaller positions.
5. Fewer, higher-conviction names; portfolio heat cap binds hard.
6. Manage on weekly closes; trail late off the 30-week MA; time-stop in weeks.
