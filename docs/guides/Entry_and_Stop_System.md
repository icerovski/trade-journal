# Entry & Stop Selection System

A unified framework for choosing **entry and stop together**. It keeps the structural-stop
engine from the *Stop Placement Playbook* intact and wraps it in the four things a stop
engine alone cannot provide: an **entry framework**, **hard no-trade gates**, an
**expectancy test**, and a **logging loop** that validates the parameters over time.

> Read alongside the Playbook (stop mechanics) and the Indicator Glossary (what each level
> *means*). This file is about turning structure into a **decision** — including the
> decision *not* to trade.

---

## 0. The one idea everything hangs on

A trade is a single object, not a stop bolted onto an arbitrary entry:

```
TRADE = (location, trigger, stop, target, size)
```

These are **not independent**. Entry minus stop *is* your risk unit **R₁** (initial risk
per share), and R₁ drives size, expectancy, and whether the trade is worth taking at all.

> A perfect structural stop on an edgeless entry still loses money. The Playbook answers
> *"where am I wrong?"*. This system also answers *"where/when do I get in, and is the
> trade worth taking?"* — using the **same structural vocabulary** so entries and stops
> share one coordinate system.

**Terminology fix (do this first).** The Playbook overloads "R". Split it:

| Symbol | Meaning | Used for |
|---|---|---|
| `ATR` | average true range (state the period, e.g. ATR14-daily) | distances, buffers |
| `R₁` | initial risk per share = `entry − stop` | the trade's risk unit |
| `R%` | portfolio risk = `R₁ × qty / NAV` | sizing & heat |

Never write "0.23R away" again — write "0.23 ATR away". Reserve R for risk-per-share.

---

## 0a. Idea sourcing & edge validation (the funnel above the entry)

The system is only as good as the ideas entering it. An external pick — newsletter, screen,
tip — is **one input, not a verdict**, and its edge is unproven until *you* measure it.

1. **One source is a single point of failure, and an unverified one.** Treat any external
   pick as a *candidate* that must pass your own fixed checklist (or a second, uncorrelated
   source) before it becomes a trade. This matters most when the source is a subscription
   publisher: its business incentive is engagement and renewals, not your returns.

2. **Classify every idea as THESIS or TECHNICAL at entry** — they are managed on different
   clocks, and blending them is the most common quiet loss:

   | | THESIS trade | TECHNICAL trade |
   |---|---|---|
   | Why you're in | a fundamental case (often slow, multi-year) | a structural setup (§2) |
   | Invalidation (stop) | the *fundamental* reason is gone | the structural stop (§3) |
   | Drawdown tolerance | wider — size for it (§6) | tight — per gate G1 (§4) |
   | Exit | thesis met/broken; trail a runner (§5a) | target / structure (§5a) |

   The trap: holding a multi-year fundamental thesis but exiting on a 15% technical wobble
   that never invalidated the thesis — a realized loss on noise, then it works without you.
   **One clock per trade.**

3. **Benchmark the source itself.** Log *every* pick the source emits — taken or not — with
   date and price, and track it against a simple index. After ~20–30 picks you'll know
   whether the source adds edge over just buying the benchmark, **net of its cost**
   (`subscription ÷ NAV` = the % you must beat before breaking even). If it can't clear that
   hurdle, the *funnel* is the problem, not your execution — and no entry/exit tuning fixes a
   bad funnel.

---

## 1. New-entry vs. manage-existing (decide this before anything else)

The Playbook silently mixes two jobs that need different logic.

- **NEW ENTRY** — you are deciding whether to open. The bar is high: you need a defended
  *location*, a confirmed *trigger*, a tight *stop*, and you must clear every gate in §4.
  If any fails → **no trade**.
- **MANAGE EXISTING** — you already hold; the question is only *where is the live
  invalidation now*. Here "mid-air, nothing below" is a real problem you must solve
  (tighten to nearest structure or exit) — but it is **never** a reason to *open*.

Everything below is split along this line. **Scenario C of the Playbook is a
manage-existing situation that should never become a new entry.**

---

## 2. The entry side (the missing half)

Entries reuse the Playbook's regimes and anchors, so the stop is built into the setup.

### Location archetypes

| Regime | Archetype | Where you enter | Paired stop (Playbook) |
|---|---|---|---|
| NORMAL/base | **Value reclaim** | reaction/reclaim at `VAL_6mo/12mo` after a flush | Scenario A — under that VAL |
| NORMAL/base | **Range-low accumulation** | near base low that is holding | Scenario A — under base |
| MOMENTUM | **Continuation pullback** | first controlled pullback into a micro-anchor (`GAP/HVN/VAL_14d/AVWAP_14d`) that **holds** | Scenario B — 0.25 ATR under the holding anchor |
| MOMENTUM | **Breakout retest** | retest of the breakout level (often a gap floor / HVN) | Scenario B — under the gap floor |
| — | **Mid-air after a drop** | *do not enter* | n/a — this is Scenario C, **no trade** |

**Key unification:** the condition that makes the *stop* undefinable in Playbook
Scenario C — no micro-support below price — is the *same* condition that makes the *entry*
untradeable. There is no defended level beneath price to enter against, so there is no
trade. Scenario C stops being a stop-placement puzzle and becomes a one-line entry rule:
**no shelf below = no new trade; wait for the re-flag.**

### Trigger (separate from location)

Location says *where*; trigger says *when to commit*. Pick the trigger up front so entry
price — and therefore R₁ — is deterministic:

- **Reaction trigger** (default for pullbacks/reclaims): require evidence the anchor held —
  a reversal/reclaim bar closing back above the level. Do not catch the falling knife.
- **Strength trigger** (breakouts): break-and-hold above the micro pivot on the retest.

Write the entry price as a rule, not a hope: e.g. "enter on a close back above HVN_14d
(412.30); abort if it closes below." Now `R₁ = entry − stop` is fixed before you act.

---

## 3. Building the joint entry/stop

1. Identify the **location** (§2) and confirm the **regime** (Playbook §1).
2. Let the scanner propose the **stop** (Playbook A/B). Read the `stop_source` label.
3. Define the **trigger** and the resulting **entry price**.
4. Compute `R₁ = entry − stop`, `R% = R₁ × qty / NAV`, and `stop_width_ATR = R₁ / ATR`.
5. Run the **gates** (§4). Then the **expectancy test** (§5). Only then size and commit.

---

## 4. Hard gates — produce a real "NO TRADE"

A trade must clear **all** gates. Failing a gate is not a penalty on size; it is a stop
sign. Defaults below are *starting points to be tuned from your log* (§7), not laws.

| # | Gate | Default rule | Why |
|---|---|---|---|
| G1 | **Stop-width** | `R₁ ≤ 1.5 × ATR` **and** `R₁/entry ≤ 8%` | A wide structural stop means wrong location or mid-air — not a license to risk more. |
| G2 | **Basis quality** | `stop_source` ∈ tight set **and** ≥2 *independent* confluent levels within 0.25 ATR | One lone level (or `ATR(1)`, Scenario D) is thin. See §4a on independence. |
| G3 | **Not a fallback artifact** | reject any MOMO row that is **unflagged** with a double-digit `VAL_*` stop | This is Scenario C — no trade, by §2. |
| G4 | **Event** | no new entry within N days of earnings/known catalyst (default N=5); if holding through, **pre-size for the gap, not the level** (§6) | Structural stops don't survive gaps. |
| G5 | **Extension** | don't initiate if price is > Z ATR above the anchor you'd trail from (default Z=2) | Chasing; nothing to enter against. |
| G6 | **Liquidity** | `size ≤ a × ADV` and modeled slippage ≤ slippage budget | A stop you can't exit at is not a stop. |
| G7 | **Portfolio & theme heat** | `Σ R%` over **correlated names *and* over each theme** ≤ heat cap (default 3× single-trade cap). One-source picks cluster by theme — count the theme, not the trade. | 10 names on one macro theme are one bet, not ten; your "1% per trade" is then 10% on one view. |
| G8 | **Currency** | measure `R%` and exposure in your **base currency**, not the asset's. Decide per book: ignore, cap, or hedge USD/EUR. | A USD-stop says nothing about your EUR/BGN risk; FX can swing 10–15%/yr. |

### 4a. The independence check (don't fake confluence)

VAL, a DMA, and an AVWAP that all sit at the same price after a consolidation are often
**one** signal counted three times. Count two levels as independent only if they come from
*different mechanisms* (e.g. a volume node **and** a trend MA **and** an anchored cost
basis) and would not move together if the consolidation reshaped. Otherwise count them as
one.

---

## 5. Expectancy — replace the dead RR metric

The Playbook is right that geometric RR is "informational only." Replace it with an
**expectancy estimate per archetype**, built from your own logged trades (§7):

```
E[R] = w · W̄  −  (1 − w) · L̄
```

where `w` = win rate, `W̄` = average win in R₁, `L̄` = average loss in R₁ (≈1 for clean
stops, >1 when gaps slip you). **Only take trades from archetypes with `E[R]` above your
threshold** (e.g. > +0.20R after costs). Until you have a log, treat every archetype as
*unproven* and trade starter size only.

This is the line between a *risk-control tool* (what the Playbook is) and a *strategy*
(what you're building): the stop tells you the size of a loss; expectancy tells you whether
to be in the trade at all.

---

## 5a. Targets, profit-taking & the right tail

Position-trading P&L is **right-tail-driven**: a few large winners pay for many small
losers. A fixed profit target truncates exactly those winners and quietly destroys the edge.
Design the exit to *keep* the tail, and decide its shape **at entry**, alongside the stop.

- **Scale out, don't cap out.** Take partial profit at a structural objective (prior high /
  measured move / next major value-area high) — enough to de-risk the position to "free" —
  then let a **runner** ride behind a structural trailing stop (weekly swing lows / 30-week
  MA). The runner is where trend-following actually earns.
- **Hard targets only for TECHNICAL trades.** A defined technical setup can have a defined
  objective. A **THESIS** trade should *not* carry a guessed-at-entry price target — exit it
  on thesis (met or broken), not on a number you invented before the move existed.
- **Don't let RR geometry sell your winners.** A deep-stopped winner reads low on paper RR
  (Glossary §6) — that's an artifact of geometry, not a reason to dump the tail.
- **Time stop, not just price stop.** If a THESIS hasn't progressed in N weeks (tie N to the
  catalyst window), the capital is dead — recycle it even with the price stop intact. On
  long holds this governs returns more than the price stop does.

**Rule of thumb:** entry, stop, and exit are *one* decision. If you can't state the exit
shape (target / scale-out+runner / thesis-exit) when you set the stop, you're not ready to
enter.

---

## 6. Sizing & gap-aware risk

**Fixed-fractional risk:**

```
risk_budget$ = f × NAV          (f capped per trade, e.g. 0.25%–1.0%)
qty          = risk_budget$ / R₁
```

then clamp `qty` by the exposure cap (G6) and portfolio heat (G7). Keep the Playbook's
size sanity-check: if a tight stop balloons `qty` past your exposure cap, it's a lottery
ticket — cut size, don't widen the stop.

**Gap-aware sizing (G4 names held through events):** assume the stop slips to the expected
gap, not the level. Size off `R_gap = entry − plausible_gap_price`, not `R₁`. If that makes
the trade too small to bother, that's the event gate working.

---

## 7. Logging loop — what makes it "professional grade"

Every trade, log: ticker, date, **source** (and: would you have taken it independently?),
**theme**, **THESIS/TECHNICAL tag**, regime, archetype, `stop_source`, flagged y/n,
confluence count, entry, stop, `R₁`, `R%`, ATR period/value, event-adjacent y/n,
**realized R**, **realized return in base currency** (FX-adjusted), result **vs benchmark
over the same window**, and **MAE/MFE** (worst/best excursion in R before exit).

Also log *every source pick you skipped* with its date and price — that's how you benchmark
the funnel (§0a), not just your execution.

This log is the only thing that lets you (a) estimate `E[R]` in §5 and (b) **validate the
magic numbers** the Playbook asserts. Run these reviews periodically:

| Question the log answers | Decision it drives |
|---|---|
| Does the **source** beat the benchmark, net of cost? | Keep / drop / demote it to one screen (§0a). |
| Are **winners capped** before the runner runs? | Loosen targets; scale out + trail (§5a). |
| Is **base-currency** return diverging from asset return? | Cap or hedge FX (G8). |
| Do *flagged* setups out-expectancy *unflagged*? | Tighten/relax G2. |
| Is the 0.25-ATR buffer hit by noise then reversing? | Buffer too tight — widen it. |
| Is the 10% regime line splitting similar trades? | Soften the discontinuity (§8). |
| Are losses averaging >1R (slippage/gaps)? | Tighten G4; raise costs in §5. |

---

## 8. Parameter governance — treat constants as hypotheses

Every number is a tunable, not a law. Track them explicitly and review against §7.

| Parameter | Default | Status / how to validate |
|---|---|---|
| Momentum threshold | +10% over VAL_6mo | Sharp discontinuity — prefer a 8–12% **blend band** over a hard switch, or confirm via log that trades near the line behave alike. |
| Micro window | 14 bars | Test 10/14/21; pick by stability of stop hit-rate, not in-sample fit. |
| Stop buffer | 0.25 ATR | Tune from MAE: smallest buffer that isn't tagged by noise pre-reversal. |
| Confluence band | 0.25 ATR | Tie to typical noise (e.g. 0.5× median bar range). |
| G1 width cap | 1.5 ATR / 8% | Set so the worst-case clustered drawdown stays within mandate. |
| ATR period | state it | Fix one (e.g. ATR14-daily) and use it everywhere; never mix. |

If a parameter can't be justified from first principles *or* from the log, it's a guess —
flag it as such rather than letting it masquerade as structure.

---

## 9. The integrated decision flow

```
SOURCE A CANDIDATE
 ├─ External pick? → must pass your own checklist / 2nd source (§0a). Else drop.
 └─ Tag THESIS or TECHNICAL — this decides which stop/exit clock applies.

NEW ENTRY?
 ├─ Identify location archetype (§2). None defended → NO TRADE.
 ├─ Confirm regime (Playbook §1).
 ├─ Scanner proposes stop (Playbook A/B); read stop_source.
 │    └─ Unflagged MOMO + double-digit VAL_* fallback → Scenario C → NO TRADE (wait).
 ├─ Define trigger → entry price → R₁, R%, stop_width_ATR.
 ├─ Decide the EXIT SHAPE now (§5a): target / scale-out+runner / thesis-exit.
 ├─ GATES G1–G8 (§4). Any fail → NO TRADE (or starter only where allowed).
 ├─ Expectancy E[R] for this archetype > threshold (§5)? No → NO TRADE.
 ├─ Size (§6), clamp by exposure, portfolio & theme heat, base-currency.
 └─ Commit in Risk Workspace (Playbook §7): `P F` or `@P T`, CTRL+ENTER. Log it (§7).

MANAGE EXISTING?
 ├─ Re-run scanner. Tight structural source below → migrate stop UP to it (never down).
 ├─ Mid-air / Scenario C → tighten to nearest real structure (e.g. DMA − buffer) or exit.
 ├─ THESIS trade → check fundamental invalidation, not the technical wobble.
 ├─ Thesis-by-time check: no progress by N weeks → time-stop exit.
 ├─ At a structural objective → scale out, trail the runner (§5a).
 └─ Never widen a live stop. Move it only to new structure.
```

---

## 10. Worked re-run — AVGO under this system

Same cache (price 365.02, ATR 19.64, MOMENTUM +25.5%, today's low is the 14-bar low, only
the 200-DMA at 360.49 below):

- **Location:** mid-air after a drop, no micro-anchor below price → **no defended entry**.
- **Stop:** scanner falls to `VAL_12mo` (−20%) — Scenario C fallback artifact.
- **G2 basis:** one lone level (200-DMA). Fails (need ≥2 independent).
- **G3 fallback:** unflagged MOMO + double-digit VAL_* → fails.

**Verdict (new entry): NO TRADE — wait for the re-flag.** If a shelf builds above the lows,
rescan; the micro tier returns a `HVN_14d/VAL_14d/AVWAP_14d` below price, G2/G3 can clear,
and you get a tight `ZONE-MOMO` stop with real confluence.

**If you already held AVGO:** this is manage-existing — tighten the live invalidation to a
buffer under the 200-DMA (~355–358, i.e. 0.25–0.5 ATR below 360.49 or just under the 363.83
low) or exit. That is the *only* context in which the ~357 number is correct — and it is
never an entry signal.

---

## 11. Pre-trade decision sheet

Twelve things resolve before you commit — but only the **[decide]** rows are real judgment.
**[auto]** rows compute themselves; **[gate]** rows are pass/fail and any failure kills the
trade. So the actual thinking per trade is the six [decide] rows; the rest protects you from
the decision you might rationalize.

| # | What you settle | Type |
|---|---|---|
| 1 | **Idea qualified** — passed your own screen / 2nd source (§0a) | gate |
| 2 | **THESIS or TECHNICAL** — sets every stop/exit clock below | decide |
| 3 | **Location** — a defended level to enter *against* (none → no trade) | decide → gate |
| 4 | **Trigger + entry price** — the event that commits you (§2) | decide |
| 5 | **Stop** — the invalidation line: structural, or *fundamental* for THESIS | decide |
| 6 | **Target shape** — hard target / scale-out + runner / thesis-exit (§5a) | decide |
| 7 | **Time stop** — weeks you'll give it before recycling the capital (§5a) | decide |
| 8 | **Risk budget** — your 0.4 / 0.7 / 1%, tied to conviction, not feel | decide |
| 9 | `R₁ = entry − stop`; `qty = (risk% × NAV) / R₁` — gap-size if held through earnings | auto |
| 10 | **Gates G1–G8** — width, basis, chase, liquidity, **theme heat**, **currency** (§4) | gate |
| 11 | **Expectancy** of this setup > threshold, from your log (§5) | gate |
| 12 | **Commit** (`P F` / `@P T`) and **log it — including picks you skipped** | commit |

> Rows **5 and 6 are two separate decisions**: the stop (where you're wrong) and the target
> (how you bank being right) are set independently — never let one imply the other.
