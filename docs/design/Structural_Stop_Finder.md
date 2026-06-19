# Structural Stop Finder — Design Note

**Status:** Proposed (not implemented)
**Authored:** 2026-06-19
**Scope:** A decision-support engine that proposes protective-stop levels from Fibonacci ×
moving-average confluence, as a structural alternative to "apply the latest ATR to the
current price" or "pick a profit amount to lock."

---

## 1. Problem

Today a stop is set one of two ways:

- **Volatility-only** — `@price T` / `distance T` places the stop an ATR-derived distance from
  price. Blind to structure: it will sit in empty air, or just *above* a support shelf where it
  is most likely to be tagged.
- **P&L-only** — pick how much profit to lock. Arbitrary; ignores where the market actually
  defends a level.

Neither answers *"which level is the market likely to defend, and is it far enough from price to
be safe?"* This note designs an engine that proposes stops hidden **below structural shelves**
(Fibonacci levels that confluence with long-term moving averages), vetted by volatility and P&L.

## 2. What already exists (reuse, do not reinvent)

- **Moving averages** — `services/price_service.py::get_trend_analysis()` computes 8 MAs per
  ticker (`DMA200/100/50/10`, `EMA200/100/50/10`) plus the 200-DMA trend (direction,
  consecutive days, BUY/SELL signal).
- **Confluence engine** — `core/confluence.py::evaluate_confluence(price, stop, dmas, atr)`
  measures, in **Daily-ATR units**, how close price and stop sit to each MA; flags *zones*
  (`< CONFLUENCE_ATR_THRESHOLD`) and *fortress* overlaps (`< CONFLUENCE_FORTRESS_THRESHOLD`).
  Used today by `ui/watch_list_workspace.py`.
- **OHLCV history** — `prices.db` (`prices_daily`) holds daily High/Low/Close → swing
  highs/lows are computable locally; no new data source.

**Gaps:** (1) no Fibonacci / swing-detection logic anywhere; (2) confluence is *diagnostic* — it
grades a stop you already typed, it never *proposes* one. The generative step is the whole ask.

## 3. Framing — three competing anchors (Stage 1)

Every stop compromises between three anchors; today's tooling uses only the first:

1. **Volatility (ATR)** — "don't get stopped by noise."
2. **Structure (Fib × MA confluence)** — "hide below a level the market defends."
3. **P&L** — "don't give back more than X."

**Thesis:** the best stop is the **structural level that also satisfies the volatility and P&L
vetoes** — i.e. find the strongest Fib+MA shelf below price, accept it only if it is ≥ ~1 ATR
below price (noise can't tag it) and still locks acceptable profit; otherwise step to the next
shelf or fall back to ATR. **ATR stops being the target and becomes a spacing/veto check.**

## 4. Swing selection (Stage 2)

A retracement needs a **swing high** and **swing low**.

- **Swing HIGH = high-water mark** (`max_since_entry` / `highest_high_since`). Already tracked,
  and already what the trailing stop references. Low controversy.
- **Swing LOW** is the hard, subjective part. Candidate anchors:

  | Anchor | Source | Pro | Con |
  |---|---|---|---|
  | Position entry | `entry_price` | trivial | your event, not market structure |
  | Recent pivot low | fractal scan of OHLCV | true structure | which pivot? sensitivity `k` decides all |
  | Last 200-DMA touch | scan Close vs rolling DMA200 | auto-ties Fib to the MA | leg can be long; deep Fibs far below |
  | Lookback-window low | lowest low over N months | robust | arbitrary window |

  Pivot detection = Williams fractal: a bar lower than the `k` bars each side. **`k` is the one
  knob that controls everything** — small `k` → minor swings → stops too tight; large `k` →
  major swings → deep stops that give back profit. No universally correct `k`.

**Decision: multi-anchor with a hard agreement filter.** Do not bet on one swing. Compute Fib
ladders from ~3 independent anchors and reward where levels from *different* swings AND an MA
stack up. Agreement across independent methods replaces the impossible "which swing is right"
choice. Output is *fewer, higher-conviction* candidates — **not** a busier list — **provided**
the filter is enforced (see §5).

**Risk named explicitly — "confluence theater":** with enough lines (8 MAs × 3 swings × 6
levels) every price is near *something*. Manufactured confluence is worse than none. Multi-anchor
is only acceptable with three disciplines bolted on:

1. Agreement must span method **types** (Fib-from-swing-A + a *different* swing's Fib or an MA) —
   not two naturally-close MAs.
2. **Cap inputs** — ~3 swing anchors + long-term MAs (200/100/50), not all 8.
3. **Minimum strength to display** — below it, say *"no structural shelf — fall back to ATR."*

## 5. Scoring the Fib × MA confluence (Stage 3)

**Lines (kept lean):**

| Family | Lines | Base weight |
|---|---|---|
| Fib swing A (major leg) | 38.2 / 50 / 61.8 / 78.6 % | golden (50, 61.8) = 1.0, else 0.5 |
| Fib swing B (minor leg) | same | same |
| Fib swing C (200-DMA-touch leg) | same | same |
| MAs | DMA200 / DMA100 / DMA50 | 1.0 / 0.7 / 0.5 |

Only lines **below** current price matter (protective stop on a long).

**Cluster** lines into a *zone* when within `CONFLUENCE_ATR_THRESHOLD` (~0.25 Daily ATR); within
`CONFLUENCE_FORTRESS_THRESHOLD` (~0.1 ATR) earns a *fortress* flag. Reuses the existing constants.

**Score (the agreement filter as math):**

```
families(Z)  = distinct line-families present in the zone
GATE:          discard Z unless families(Z) >= 2          # discipline #1: cross-type agreement
strength(Z)  = sum over families of ( best base-weight in that family )   # NOT raw line count
tightness(Z) = x1.5 if fortress else x1.0
score(Z)     = strength(Z) * tightness(Z)
DISPLAY GATE:  hide Z unless score >= MIN_SCORE            # discipline #3
```

`strength = sum of the best line per family` is what kills confluence theater — five bunched MAs
still contribute only their single best weight. Diversity of *independent* methods is the only
path to a high score. If no zone clears the gates → *"no structural shelf; fall back to ATR."*

**Stop placement — hide *under* the shelf:**

```
stop_candidate = min(line prices in Z) - PAD ,   PAD ~= 0.15 * ATR
```

**Worked example** (price 688, Daily ATR ≈ 10):

| Zone | Lines | families | fortress | score | → stop |
|---|---|---|---|---|---|
| ~640 | 61.8% (A) + 38.2% (B) + DMA100 | 3 | yes | (1.0+0.5+0.7)×1.5 = **3.3** | 638.5 |
| ~655 | 50% (A) + DMA50 | 2 | yes | (1.0+0.5)×1.5 = **2.25** | 653.5 |
| ~620 | DMA200 only | 1 | — | **discarded** (gate) | — |

Output: ranked candidate list `[640 (3.3), 655 (2.25)]`, each with constituent lines, ATR-distance
and implied stop — **scored by structural conviction, with no safety check yet.**

## 6. Selection rule + guardrails (Stage 4)

Three vetoes bound a **valid band**:

| Veto | Rule | Rejects | Anchor |
|---|---|---|---|
| Spacing | `stop <= price - MIN_ATR_GAP*ATR` (1.0–1.5) | too close (noise tags it) | ATR |
| Give-back | `(price - stop) <= MAX_GIVEBACK` | too deep (hands back gain) | P&L |
| Reward (3:1) | `(target - price)/(price - stop) >= 3` | too deep (breaks 3:1) | Stage-1 thesis |

Spacing pushes from the tight side; give-back and 3:1 from the deep side. Survivors sit in a band:
not closer than ~1 ATR, not deep enough to break 3:1 or give-back tolerance.

**Loop back to the `TP:N:1` command:** the Reward veto behaves differently by mode —

- **Fixed target:** deeper stop → lower forward RR → 3:1 is a hard depth floor.
- **Re-anchor (`TP:3:1`):** the target moves up to restore 3:1 against any stop → 3:1 satisfied
  by construction; **give-back becomes the only depth cap.** Tell: a very deep shelf forces the
  re-anchored target implausibly far (e.g. +8R) — the implausibility is itself the "too deep"
  signal.

**Worked continuation** (target 787 = the 3:1 setup): deepest stop allowed by fixed 3:1 =
`688 - (787-688)/3 = 655`.

| Mode | Valid shelves | Winner | Command |
|---|---|---|---|
| Fixed target | only **655** | 655 (locks $128/sh) | `@653 T` |
| Re-anchor | **640** & 655 | **640** (stronger 3.3) — target → `688+3×48 = 832` | `@638 T TP:3:1` |

The structural answer (640) is only usable if the target re-anchors — and the engine says so and
hands you the exact command.

**Selection:**

```
candidates = shelves passing ALL three vetoes
if empty:  -> fall back to pure ATR spacing, and SAY WHY
else:      -> pick STRONGEST in the band; tie-break toward the TIGHTER (more profit locked)
              surface the rest as alternatives ("looser, deeper, last line of defense")
```

Strongest-in-band (not tightest) because the point of going structural is *conviction the level
holds*; the give-back veto already prevents "strongest" from meaning "absurdly deep." The
**fallback is a first-class answer**: *"Nearest shelf 4.8 ATR below — gives back too much; using a
1.5-ATR stop at 673 instead."* That explanation is exactly what "just apply the ATR" lacks today.

**Output per candidate:** stop price, command string (`@price T [TP:3:1]`), constituent lines,
ATR-distance, profit locked, give-back, resulting forward RR / re-anchored target, score.

## 7. Implementation plan (Stage 5)

Build pure core + tests first, validate on live VOO in a script, then wire UI. **No DB writes —
read + display only.**

| New / changed | Responsibility | Pure? |
|---|---|---|
| `core/swings.py` | `find_pivots(highs, lows, k)` → swing points (fractal) | yes |
| `core/fib_confluence.py` | `propose_stops(...)` — Stage 3–4 engine + `cluster_levels()` + `StopCandidate` | yes |
| `core/confluence.py` | factor shared clustering / reuse ATR thresholds | yes |
| `services/price_service.py` | `last_dma_touch()` + `get_stop_candidates()` orchestration (assembles inputs, calls pure engine) | I/O seam |
| `ui/risk_workspace.py` | "STOP CANDIDATES" DataTable in the discovery panel; optional key to pre-fill the command box | UI |
| `constants.py` | the dials below | — |

**Data flow:**

```
prices.db OHLCV -> find_pivots(k_small, k_large) ----┐
last 200-DMA touch leg -------------------------------+-> propose_stops() -> ranked candidates -> panel
get_trend_analysis -> DMAs (200/100/50) -------------+        (pure)
ATR discovery -> Daily ATR ---------------------------┘
```

The pure engine never fetches — handed swings, DMAs, ATR, position scalars. Makes the Stage-4
example a clean offline unit test.

**Phases (each reviewable):**

1. `core/swings.py` + tests (pivot detection on synthetic series).
2. `core/fib_confluence.py` + tests — clustering, vetoes, selection, the fixed-vs-re-anchor split
   (640/655 example as a fixture).
3. Script validation on live VOO before any UI.
4. UI panel.

**Constants to add (tunable defaults):**

```
FIB_LEVELS            = [0.382, 0.5, 0.618, 0.786]
SWING_K_SMALL / LARGE = 5 / 15
STOP_MIN_ATR_GAP      = 1.0            # spacing veto
STOP_MAX_GIVEBACK_ATR = <tbd>         # give-back veto (ATR vs % of open profit — see open Qs)
STOP_MIN_SCORE        = 1.5           # display gate
STOP_PAD_ATR          = 0.15          # hide-below-shelf pad
# base weights reuse CONFLUENCE_ATR_THRESHOLD / CONFLUENCE_FORTRESS_THRESHOLD
```

**Effort / risk:** Phases 1–2 are the real work but fully testable offline. Phase 4 mirrors the
existing discovery tables. **Biggest risk: swing-detection robustness** — garbage swings →
garbage Fibs; the multi-anchor agreement filter is the hedge, and Phase 3 (live eyeballing on
several positions) gates trust. This is **decision support, not an oracle**; the fallback-to-ATR
path keeps it honest when structure is absent.

## 8. Open decisions (needed before Phase 2)

1. **Give-back veto units** — cap depth by ATR distance (≤ N ATR) or by % of open profit
   (don't give back > X%)? The latter matches the "lock some profit" framing.
2. **Default mode** — fixed-target or re-anchor (`TP:3:1`)? Re-anchor matches the existing
   workflow but sends targets further out.
3. **Spacing gap** — `STOP_MIN_ATR_GAP` = 1.0 or 1.5 ATR? 1.5 is safer but rejects more shelves.

## 9. Related

- `core/confluence.py`, `ui/watch_list_workspace.py` — existing confluence (Daily-ATR distances).
- `TP:N:1` command (`ui/risk_workspace.py::resolve_tp_ratio`) — the re-anchor target this engine
  drives; see `docs/sessions/2026-06-17_Extendable_TakeProfit_Target.md`.
- `core/stop_loss.py` — volatility-buffer stop mechanics and the ATR discovery tables.
