# Guide: Reading the Entry/Exit Zone Scanner

A hands-on companion for *using* the Zone Scanner (menu option **8**) — how to read
what each row and label is telling you, and how to act on it. For the design
rationale and formulas, see `docs/TECHNICAL_DOCS.md` §7.

> **See also:** [`Indicator_Glossary.md`](Indicator_Glossary.md) is the canonical home for
> every indicator/metric definition (VAL, AVWAP, HVN, the ATRs, R, confluence…). The
> decode tables below are a quick reference; the glossary is the source of truth.
> For *how to pick a stop* across scenarios, see [`Stop_Placement_Playbook.md`](Stop_Placement_Playbook.md).

---

## 1. The mental model

The scanner answers one question per ticker: **"Is price sitting on a cluster of
independent structural levels right now, and if so, where's the invalidation and
how big a position fits my risk budget?"**

It does *not* predict direction. It measures **confluence** — when several
unrelated levels (volume shelves, anchored VWAPs, moving averages) stack up at the
current price, that spot is structurally meaningful. Two or more converging = a
flagged **zone**.

The scan is **read-only**. It never places trades or writes to the database. It's
a decision-support read; you act on it manually elsewhere.

---

## 2. What gets scanned

The universe is the same as the Watch List:

- **Open holdings** (your live positions), and
- **`status='WATCH'` prospects** — names you've added to watch.

If a WATCH name has no cached price history yet, the scan **fetches it on demand**
the first time (a one-off ~10-year daily pull), then caches it. So a freshly-added
prospect shows up on the next scan automatically — no manual price sync needed.
(See §7 for how to add one.)

---

## 3. Reading the results table

Rows are sorted **flagged-first**, then by proximity to the nearest level.

| Column | Meaning |
|---|---|
| **TAG** | `ZONE` (confluence zone), `ZONE-MOMO` (zone in a momentum regime), or `—` (no zone) |
| **TICKER** | the name |
| **REGIME** | `MOMO` (momentum) or `base` (normal) — see §5 |
| **PRICE** | current price |
| **DIST** | percent distance from price to the **nearest** structural level (how close you are to *something*) |
| **SIG** | count of converging entry signals at price (the confluence count) |
| **STOP** | the chosen stop price (only shown when a zone is flagged) |

A **flagged** row (TAG = `ZONE` or `ZONE-MOMO`) means ≥ 2 signals converged and the
scanner has produced a stop, target, and sizing. A `—` row did not clear the
confluence bar — `DIST` still tells you how far the nearest level is, so you can
watch it.

---

## 4. Reading the detail panel

Select a row to expand it. Three boxes:

**Converging signals** — each level sitting near price, e.g.:

```
  DMA50          412.30  (0.18R / 0.45%) ★
  VAL_6mo        408.10  (0.62R / 1.52%)
```

- The number in parentheses is **distance in ATR units (R)** then **percent**.
  Distance is the operative measure — `< 0.25R` is a tight, meaningful zone.
- A **`★`** marks a *fortress* level — exceptionally tight to price/stop.
- More rows + tighter distances = a stronger zone.

**Stop / Target**

```
  Stop:   408.10  (VAL_6mo, −1.5%)
  Target: 455.00  (naked POC)
  Risk/share: 6.50
```

- **Stop** shows the price, the **source label** (decoded in §6 — this is the key
  to "reading the new zones"), and the percent below price.
- **Target** is the next **naked POC** above price if one exists, otherwise the
  **3:1 reward floor** (`price + 3 × risk-per-share`). The tag in parentheses tells
  you which.
- **Risk/share** = price − stop, in the instrument's currency.

**Position size by preset** — share count under each risk preset (Small / Base /
Large), each sized under the dual R%/exposure constraint. Larger preset ⇒ at least
as many shares.

---

## 5. The two regimes

The regime decides **where the stop comes from**.

- **NORMAL (`ZONE`)** — price is near its longer-term support. The stop is the
  nearest true structural support below price (6mo/12mo VAL or the swing-low
  anchored VWAP).
- **MOMENTUM (`ZONE-MOMO`)** — price has run **more than 10% above its 6-month
  VAL**. That longer-term support is now too far below to be a usable stop (a
  20%+ stop). The scanner switches to a **micro-structure** stop from the last
  ~2 weeks of bars, so the invalidation tracks the *current* parabolic leg, not
  ancient support.

`ZONE-MOMO` is not a stronger or weaker signal than `ZONE` — it's a **statement
about stop placement**. It says: *"this is extended; the stop is tight and tied to
the recent micro-structure, and a clean break of it means the momentum leg is
broken."*

---

## 6. Decoding the STOP source label

This is the heart of reading the zones. The label after the stop price tells you
**which level the invalidation is anchored to**. The scanner always picks the
**tightest qualifying support below price** (the one that gives the smallest stop),
then places the stop a small ATR buffer (0.25 × daily ATR) beneath it.

### Normal regime (`ZONE`)

| Label | Anchor |
|---|---|
| `VAL_6mo` / `VAL_12mo` | value-area low of the 6- or 12-month volume profile |
| `AVWAP_low` | anchored VWAP from the most recent swing low |
| `ATR(1)` | **fallback** — no structural support below price was found, so a plain 1-ATR stop. Treat as a weaker basis. |

### Momentum regime (`ZONE-MOMO`)

All four are computed from the last **14 bars** and the tightest below price wins:

| Label | Anchor | What a break of it means |
|---|---|---|
| `VAL_14d` | micro volume-profile value-area low | price has left the recent volume shelf |
| `HVN_14d` | nearest **high-volume node** below price — a heavy shelf where volume stacked (tighter/more precise than the VAL edge) | price has fallen through where recent volume accumulated |
| `AVWAP_14d` | anchored VWAP from the swing low *inside* the 14-day window | the average buyer of this leg is now underwater |
| `GAP_14d` | the **floor of the most recent breakout gap** (the pre-gap high) — only gaps ≥ 0.5 ATR count | the breakout gap has been filled — the move that started the leg is undone |

**How to read which one won:** the label names the *type* of recent structure that
is closest beneath price. `GAP_14d` says the tightest thing under you is an unfilled
breakout gap — a clean fill is your exit. `HVN_14d` says it's a volume shelf.
`AVWAP_14d`/`VAL_14d` say it's the recent value/average-cost structure. All four are
"momentum is broken" lines; the label just tells you *what kind* of line and where.

> The `GAP` and `HVN` anchors are the **v2** additions. Before v2 the momentum stop
> only ever read `VAL_14d` or `AVWAP_14d`; if you see `GAP_14d` or `HVN_14d`, that's
> the new tier choosing a tighter, more specific micro-anchor.

---

## 7. Getting a name onto the scan (Watch List → add)

To scan a prospect you don't yet hold, add it to the Watch List:

1. Launch the **Watch List** (menu option **6**).
2. Press **`a`**. A modal asks for a ticker symbol; type it and press Enter.
3. The app resolves the symbol, pulls its price history, computes a default
   (Daily TRAILING / Base preset) risk profile, and saves it as a `WATCH`
   prospect. It appears in the list immediately.

Because that step caches the price history, the name is **immediately scannable**
in the Zone Scanner (and chartable). You refine the stop later in the Risk
Workspace, or just let the scanner propose one.

This is the dedicated add path — you no longer go through the Risk Workspace to
start watching a name.

---

## 8. Caveats to keep in mind

- **Daily-bar approximation.** The volume profile (POC/VAH/VAL, HVNs, naked POCs)
  is reconstructed from *daily* OHLCV — Yahoo Finance exposes no intraday
  volume-at-price. Each day's volume is smeared across its high-low range, weighted
  toward the close. It is an estimate of where volume traded, **not** a tick-derived
  profile. The panel footer notes this. Don't treat a node as a precise price.
- **Display-only.** Nothing here is persisted or ordered. The sizes are *what would
  fit*, not committed positions.
- **The stop is an invalidation, not a recommendation to enter.** A flagged zone is
  a *location*; whether to act is your call.

---

## 9. Quick reference

| Want to… | Do this |
|---|---|
| Run the scan | Menu **8** |
| See a name's full breakdown | Select its row |
| Rescan | Press **`r`** |
| Add a name to be scanned | Menu **6** → **`a`** → type symbol |
| Understand the stop | Read the source label (§6) |
| Judge zone strength | Count signals (SIG) + read their ATR distances; tighter = stronger |
| Know if it's extended | TAG `ZONE-MOMO` / REGIME `MOMO` |
