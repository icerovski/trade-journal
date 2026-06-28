# Stop Placement Playbook

A step-by-step walkthrough for getting to a stop. For what each indicator *means*, see
the **Indicator Glossary**; this file is about *how to decide*.

A stop is an **invalidation line**, not a recommendation to enter. It answers one
question: *"At what price is my reason for being in this trade wrong?"* Everything below
is about locating that line from structure, then translating it into a command.

---

## 1. The scanner's decision tree (what menu 8 does for you)

`zone_scan.scan_ticker` resolves a stop in this exact order:

```
1. Is price > 10% above the 6-month VAL?
   ├─ NO  → NORMAL regime  → stop = nearest structural support below price
   │                          (6mo/12mo VAL, or swing-low AVWAP)        [Scenario A]
   └─ YES → MOMENTUM regime → stop = tightest micro-anchor below price
                              (VAL_14d / HVN_14d / AVWAP_14d / GAP_14d)  [Scenario B]
                              minus a 0.25-ATR buffer

2. Did step 1 find nothing below price?
   ├─ Fall back to nearest base support (VAL/AVWAP_low)                 [Scenario C]
   └─ Still nothing? → plain 1-ATR stop, tagged ATR(1) (weak basis)     [Scenario D]
```

The output `stop_source` label tells you *which* branch won. Reading that label is the
whole skill — it tells you the story of the invalidation.

---

## 2. Scenario A — NORMAL regime, price near support

**Signature:** TAG `ZONE`, REGIME `base`. Price is sitting near its longer-term value area.

**Stop:** the nearest VAL (`VAL_6mo` / `VAL_12mo`) or `AVWAP_low` below price, whichever
is closest. A clean break of the value-area low means price has left the range where most
business was done — the thesis (accumulation at value) is wrong.

**How to read it well:** check the **Converging signals** box. The more independent levels
(VAL + a DMA + an AVWAP) stack within 0.25R, the more defensible the stop. A lone level is
thinner support.

**Act:** commit the level as a FIXED stop, e.g. `408.10 F`.

---

## 3. Scenario B — MOMENTUM regime, micro support below price

**Signature:** TAG `ZONE-MOMO`, REGIME `MOMO`. Price has run >10% above its 6-month VAL,
so long-term support would be a 20%+ stop — useless. The scanner drops to the last 14 bars
and finds the tightest of four micro-anchors *below price*, then sits 0.25 ATR under it:

| `stop_source` | The tightest thing under you is… | Exit logic |
|---|---|---|
| `GAP_14d` | an unfilled breakout gap | a clean fill undoes the move |
| `HVN_14d` | a heavy recent volume shelf | price fell through accumulation |
| `VAL_14d` | the recent value-area low | price left the recent shelf |
| `AVWAP_14d` | the swing-low average cost | the leg's buyers are underwater |

**How to read it well:** the label names the *kind* of micro-structure closest beneath
price. All four are "the momentum leg is broken" lines — `GAP_14d` is the tightest/most
specific, `VAL_14d`/`AVWAP_14d` the broadest. A tighter anchor = a smaller stop = a larger
size under the same R budget, but less room for noise.

**Act:** the scanner already gives you the price; commit it (FIXED for a hard line, or
`@price T` to let it trail from a floor).

---

## 4. Scenario C — MOMENTUM regime, but price is sitting ON the low (no micro support)

**This is the case that trips people up — and the one AVGO showed.** When price has just
sold off and closed at the *bottom* of the 14-day window, there is **nothing below it** to
anchor to: the micro VAL, swing-low AVWAP, HVNs and gaps are all *overhead*. `_micro_support`
returns nothing, and the scanner falls all the way back to the long-term VAL — producing a
**−20%-ish stop that you must NOT use.** That number is a *fallback artifact*, not a proposal.

### Worked example — AVGO (cache through 2026-06-26)

```
price        365.02      daily ATR 19.64      regime MOMENTUM (price +25.5% over 6mo VAL)
flagged      False       (only 1 converging signal: DMA200 at 360.49, 0.23R away)

last 14 bars: today's low 363.83 is the LOWEST low in the window
  micro VAL      376.37   → above price ✗
  swing AVWAP    367.51   → above price ✗
  HVN / gap      none below price
=> micro_support: none

scanner fallback → VAL_12mo 291.60  →  −20.1% stop   ← ARTIFACT, do not use
```

**How to handle it:**

1. **Discard the −20% fallback.** It only means "no micro support exists below price right
   now," not "put your stop 20% down."
2. **Anchor to the nearest real level instead.** Here that is the **200-DMA at 360.49**
   (−1.2%, 0.23R below) — the lone converging signal and the structural decision line. A
   sensible invalidation sits a buffer beneath it: **~355–358** (0.25–0.5 × ATR ≈ 5–10 pts
   under 360.49, or just under today's low 363.83). A clean break of the 200-DMA is the
   "thesis broken" line.
3. **Or wait for the scan to re-flag.** If price bounces and builds a shelf above the lows,
   rescan (`r`): the micro tier will then have a `VAL_14d` / `AVWAP_14d` / `HVN_14d` *below*
   price and hand you a tight `ZONE-MOMO` stop with real confluence. Right now AVGO is
   mid-air after a drop — no shelf beneath it yet.

**Rule of thumb:** a MOMENTUM row that is **not flagged** and whose stop reads a long-term
`VAL_*` at a double-digit percent is the scanner telling you *"I have nothing tight here —
place the stop yourself off the nearest level, or wait."*

---

## 5. Scenario D — no structural support at all

**Signature:** `stop_source = ATR(1)`. No VAL or AVWAP sits below price in any lookback, so
the scanner uses a plain 1-ATR stop just so the row can still be sized. Treat it as the
**weakest** basis — there's no structure defending it. Prefer to wait for price to build
support, or place a discretionary level yourself.

---

## 6. Choosing a stop yourself (when you override the scanner)

The scanner proposes; you decide. Good discretionary anchors, tightest to loosest:

- **A breakout gap floor** or **HVN** just below price — tight, structurally defended.
- **The swing-low** of the current leg — the obvious "lower low = broken".
- **A key moving average** (50-DMA in an uptrend, 200-DMA as the last line) — the AVGO case.
- **The value-area low** of the relevant lookback — the broad "left the range" line.

Always add a small buffer (~0.25 ATR) so normal noise doesn't shake you out at the exact
level. Then sanity-check the resulting **R% NAV** and **size** — a stop so tight that the
size balloons past your exposure cap isn't a stop, it's a lottery ticket.

---

## 7. Translating a stop into a Risk Workspace command

Once you have a price, commit it in the **Risk Workspace** (menu 2). Syntax (full reference
in the **Strategy Lab** help / guide):

| You want… | Command | Notes |
|---|---|---|
| A hard line at price P | `P F` | FIXED stop; never moves automatically |
| A trailing floor at price P | `@P T` | sets ATR distance = current HIGH − P, then trails |
| A trailing buffer of $X | `X T` | stop = HIGH − X, trails up |
| A trailing buffer of n% | `n% T` | stop = HIGH − n% of HIGH |
| Stop + size preset | `P F P:B` | adds Base preset (R/E caps) |
| Stop + re-anchor target | `@P T TP:3:1` | floor at P AND target 3:1 above price |

`ENTER` models it (nothing saved); `CTRL+ENTER` commits.

### What the stop drives once set
- **R (% NAV)** = `(entry − stop) × qty / NAV` — your downside if it fills.
- **RR** = `(TP − price) / (price − stop)` — informational only; a deep stop reads low on
  geometry alone and is *not* a reason to exit (see Glossary §6).
- **Exit ladder** — M1/M2/TP are anchored to entry and the **inception ATR**, independent of
  where you place the live stop. For a FIXED stop, the inception ATR is snapped to the
  discovery timeframe nearest `entry − stop`, so the ladder matches the stop's horizon.

---

## 8. Quick checklist

1. Run menu 8; read the **TAG / REGIME** for the name.
2. Read the **`stop_source`** label — it names the invalidation (Scenarios A/B).
3. **Flagged** with a tight source → use it. **Not flagged**, or a double-digit `VAL_*`
   fallback in MOMO → Scenario C: place the stop off the nearest level yourself, or wait.
4. Add a ~0.25-ATR buffer below your chosen level.
5. Check the resulting **R% and size** fit your budget.
6. Commit in the Risk Workspace (`P F` / `@P T`), `CTRL+ENTER`.
