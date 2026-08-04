# Exit Strategy

How the system decides when to take profit and when capital is dead. For indicator
definitions see the **Indicator Glossary**; for *stop placement* see the
**Stop Placement Playbook**.

---

## The strategy in one page

Two independent questions govern every open position:

1. **Should I take profit?** Driven by the **exit ladder** (how much profit, in ATR
   units) crossed with the **trend regime** (is there structural support to keep
   riding). This decides whether to hold, trim, or close.
2. **Is this capital working?** Driven by **capital efficiency** — annualised unrealised
   return vs an opportunity-cost hurdle. Orthogonal to the ladder: a position can be
   perfectly placed on the ladder yet still be dead money tying up the book.

The **stop loss is always the ultimate backstop.** The ladder and regime only decide how
much you bank on the way up; they never widen your risk.

---

## Trend regime

The regime controls how aggressively you take profits. **TREND** requires BOTH:

1. the 200-DMA rising for **≥ 21 consecutive days**, and
2. current price **above** the 200-DMA (not a pullback below the key level).

| Regime | 200-DMA rising days | Price vs DMA | Trim M2 | Trim TP |
|---|---|---|---|---|
| 🟢 **TREND** | ≥ 21 | Above | **Hold** | 20% + raise TP |
| ⚪ **NORMAL** | 10–20, or ≥21 below | Below (pullback) | 33% | 33% or close |
| 🔴 **RANGING** | < 10 or declining | — | 50% | Close all |

- **TREND** — structural support confirmed. *Do not trim at M2* — trimming a confirmed
  compounder cuts the winner. Let the trailing stop run it and bank at the full target.
- **NORMAL** — the trend is developing, or it pulled back below the 200-DMA despite a long
  rise. Standard profit-taking: a third at each milestone, re-evaluate.
- **RANGING** — no structural support; the DMA is flat or falling. Protect gains: half at
  M2, close everything at TP.

**Reversal hysteresis.** DMA direction = sign of (today's DMA − yesterday's). The system
counts consecutive same-direction days; the count resets to ~1 on any reversal. To stop one
counter-trend day crashing a long TREND straight to RANGING, a reversal shorter than **3
days** is treated as *unconfirmed* and the regime is held one notch up at NORMAL. The PLAN
panel labels this "DMA reversed Nd (< 3, unconfirmed) → held at NORMAL".

**Horizon lens (opt-in).** By default every position is judged on the 200-DMA — a slow,
structural clock that barely moves within the lifetime of a short, tight-stopped trade.
Setting **Regime lens = `horizon`** (the `M` settings modal in the Risk Workspace) matches
the lens to the horizon the *stop* declares: a stop about one daily ATR wide → **50-DMA**
(TREND ≥ 10d, NORMAL ≥ 5d); a weekly-ATR stop → **100-DMA** (15d/7d); a wide monthly-ATR
conviction stop → the 200-DMA table above, unchanged. Time is a function of risk — the
tighter the stop, the faster the clock the trade is judged on. A non-default lens is named
in the regime string, e.g. `BUY (12d, DMA50)`.

---

## Exit stages

Milestones form a uniform ladder anchored to **entry** for BOTH stop types:
**M1 = entry + 1×R, M2 = entry + 2×R, TP = entry + 3×R**, where R is the **inception ATR**
(the original risk taken at entry). Profit is therefore measured in R-multiples. For a
trailing stop the live ATR only sets where the *stop* sits — it does not move the reward
ladder (which would otherwise drift away as volatility expands and mislabel a healthy winner).

| Stage | Trigger | Action |
|---|---|---|
| PRE-M1 | price < entry + 1×ATR | Hold — the stop is the only exit |
| **M1** | price ≥ entry + 1×ATR | Move stop to entry (risk-free) |
| **M2** | price ≥ entry + 2×ATR | Trim by regime (TREND = hold) |
| **TP** | price ≥ entry + 3×ATR | Larger trim by regime |

**What to do at each stage:**

- **PRE-M1** — not yet one full ATR of profit. Do nothing; the stop is the only exit.
- **M1** — one ATR banked. Move the stop to entry. Do not sell. The position is now
  risk-free — break-even at worst. House money.
- **M2** — two ATRs banked. TREND = hold (no trim), NORMAL = trim ~33%, RANGING = trim ~50%.
  Share counts are in the PLAN section. The stop and TP still govern the rest.
- **TP** — three ATRs from entry. RANGING: close everything. TREND: take a 20% slice and
  raise the TP to chase the larger move. NORMAL: close ~33%, keep a runner if you still like
  it. In all cases the trailing stop remains the ultimate exit.

---

## RR is informational — there is no efficiency-floor exit

**RR = (TP − price) ÷ (price − stop)** is shown as a quality read, **not** an exit trigger.
A deep stop drags RR low on geometry alone, so a sub-1.0 RR is not a sell signal. Exits are
driven by the **stop** and a **RANGING regime**, never by RR. (The former sub-1.0
"efficiency floor" that forced a FIXED-stop exit was removed — commit `5b2f9ff`.)

When a `TP:n` override is active the PLAN panel shows a **TARGET** line flagging the forward
RR against the 3:1 setup floor (`RR_SETUP_FLOOR`) — again, a flag to read, not an order to
act. PLAN-strip RR color bands: 🟢 ≥ 2.0, 🟡 ≥ 1.0, 🔴 < 1.0.

---

## Capital efficiency (dead money)

Independent of the ladder — it asks whether the capital is earning its keep. A position is
flagged **STALE** when BOTH hold:

- held **≥ 180 days** (below this, annualised return is too noisy to judge), and
- annualised unrealised return (**AAGR**) **< 8%** (the opportunity-cost hurdle).

It is **not** an automatic exit — it is a prompt to review the thesis or redeploy into
something working harder. The PLAN panel always shows "Capital: ±x% AAGR over Nd" and adds a
"⏳ STALE … review or redeploy" nudge when triggered (suppressed on a stop breach, where exit
already dominates). Bonds and bills are excluded — price-only AAGR would understate a
coupon-earning hold. (Thresholds live in `constants.py`.)

---

## Dashboard EXIT column

| Marker | Meaning |
|---|---|
| *blank* | PRE-M1 — no action required |
| `M1` | Move stop to entry price — no trimming |
| `M2·T/N/R` | Trim due — T = hold, N = 33%, R = 50% |
| `TP·T/N/R` | Full target hit — T = 20% + raise TP, N = 33%, R = close all |

Regime suffix: T = Trend, N = Normal, R = Ranging. Full breakdown with share counts is in
the Risk Workspace PLAN section.
