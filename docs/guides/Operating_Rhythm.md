# Operating Rhythm — running the system, not just owning it

The other guides explain what each metric *means*. This one says **which screen to open
when, what question to ask it, and what to do with the answer** — the cadence that turns
a toolbox into a process. It also walks the full life of a position: open → monitor → close.

> Rule zero: the system's default output is **"do nothing."** Most sessions should end
> with zero trades and zero edits. The screens exist to surface the exception, not to
> give you something to do.

---

## 1. The screens — one question each

| # | Screen | The question it answers | Cadence |
|---|---|---|---|
| 1 | SYNC ALL | "Is my data current?" | every session, first |
| 3 | DASHBOARD | "Is anything flagged that needs my attention?" | every session |
| 2 | RISK WORKSPACE | "Where is my invalidation, and is every position compliant?" | weekly + per trade |
| 6 | WATCH LIST | "Are any candidates entering a buyable zone?" | weekly |
| 8 | ZONE SCANNER | "Where are the structural entry/stop levels *right now*?" | weekly + per trade |
| 7 | PORTFOLIO RISK | "What do I lose if everything stops out? Am I concentrated?" | weekly |
| 9 | EXPECTANCY | "Which setups/sources actually make money?" | monthly |
| 5 | MAINTENANCE | "Does the ledger reconcile?" | when something looks wrong |

---

## 2. The cadence

### Every session (5–10 min)
1. **`1` SYNC ALL** — fresh trades, prices, FX.
2. **`3` DASHBOARD** — scan for exceptions only: positions near their stop, EXIT-column
   stage changes, 🔴 regime flips, stale-money flags.
3. Nothing flagged → **close the app.** That is the correct outcome.

### Weekly (the real session, ~30–45 min)
1. **`2` RISK WORKSPACE** — walk every ACTIVE position:
   - Compliance: any YELLOW/RED R%? Use the restore paths (raise stop / trim N shares).
   - **Stop migration:** re-run the scanner read per name — new structure *above* the
     current stop → migrate the stop UP to it. Never down (§9 of the Entry & Stop System).
   - PLAN strip: exit stage, regime, milestones — anything at M1/M2/TP → §5 below.
2. **`8` ZONE SCANNER** — one pass over the universe (holdings + WATCH). Note names
   that turned `ZONE`/`ZONE-MOMO` with tight flagged stops — those are candidates.
3. **`6` WATCH LIST** — confluence distances < 0.25 ATR and 🟢 trend triggers →
   promote to the opening checklist (§4). Passing on a source's pick this week?
   Log it (`L` key) — a skipped pick is funnel data (§0a), not a non-event.
4. **`7` PORTFOLIO RISK** — total R%, stop-out loss, HHI, FX split. Over heat → the
   *next* trade is a NO, regardless of its own quality (gate G7 thinking).

### Monthly (~30 min)
1. **`9` EXPECTANCY** — per-archetype E[R], source-vs-benchmark funnel. This is the
   only screen that tells you whether the *system* works, not just today's book.
   Opening it runs the **automatic outcome backfill**: realized R and MAE/MFE for
   every position closed since last time, and a vs-benchmark refresh on skipped picks.
2. Parameter sanity (Entry & Stop System §8): are stops tagged by noise? losses > 1R?
   Tune the constant, not the discipline.

---

## 3. Lifecycle overview

```
IDEA → classify (C:TH/TE) → WATCH LIST → zone turns buyable → GATES → size → COMMIT
                                                                            ↓
        CLOSE ←──── stop hit / thesis broken / hard target / trim ladder ←──── MONITOR (weekly)
          ↓
        sync → reset-on-zero closes the ledger lot → log realized R
```

---

## 4. Opening a position — the walkthrough

1. **Classify the idea first** — THESIS (fundamental case, fundamental invalidation) or
   TECHNICAL (structural setup, structural stop). This decides every clock below.
   One source is a candidate, not a verdict (Entry & Stop System §0a).
2. **Put it on the WATCH LIST** (`6`) — don't buy the day you meet it. Let the zone
   scanner and trend engine watch it for you.
3. **Wait for a location** — the weekly `8` ZONE SCANNER pass shows a defended level:
   a `ZONE` value-area read or a flagged `ZONE-MOMO` micro-anchor. Mid-air / unflagged
   MOMO with a deep `VAL_*` fallback = **no trade, keep waiting** (Scenario C).
4. **Define the trigger** — write the entry as a rule before acting: "on a close back
   above [level], abort on a close below." Entry − stop = R₁ is now fixed.
5. **Model it in the RISK WORKSPACE** (`2`) — select the prospect, type the full
   command, `ENTER` to model (nothing saved):
   ```
   @156 T P:B C:TE X:H        TECHNICAL breakout, hard target, standard preset
   15% T P:L C:TH X:T         THESIS hold, thesis-only exit, large preset
   150 F G:135                held through earnings → size for the gap, not the level
   ```
   Watch the modeled R%, Exp%, and qty. A tight stop that balloons qty past the
   exposure cap is a lottery ticket — cut size, don't widen the stop.
6. **Gates** — with `gates_mode` at `advisory`/`blocking` (the `M` modal), commit runs
   G1–G8 automatically. Any explicit FAIL = stop sign, not a size penalty.
7. **Commit** — `CTRL+ENTER` (or `S` for all drafts). The stop, preset, tag, and exit
   shape persist; a commit carrying `C:` or `SRC:` writes the decision journal row —
   add `SRC:`/`THM:` so the source and theme ride along (that's what menu 9 benchmarks).
8. **Execute at the broker**, then `1` SYNC ALL — the fill lands in the ledger and the
   position appears with its strategy already attached.

**The decision sheet (Entry & Stop System §11):** only six things are judgment —
classification, location, trigger, stop, exit shape, risk budget. Everything else is
[auto] or [gate]. If you can't fill row 6 (how you'll exit) you're not ready to enter.

---

## 5. Monitoring — what to check, what to ignore

**Per session (seconds per name):** Dashboard only. Price vs stop, EXIT column, flags.
Green and unremarkable = *look away*. Daily fiddling is how trailing stops get widened
and thesis trades get sold on wobbles.

**Weekly (the stop-migration pass, workspace `2`):**
- Stop still below live structure? If the scanner now shows a tighter defended level
  *above* your stop → migrate up (`@price T` or new fixed price). **Never widen.**
- Exit stage reached? The PLAN strip + TRIM_MATRIX give the action:
  - **M1/M2/TP in the ladder** — trim per regime (TREND holds longer, RANGING banks).
  - **TP with `X:H`** — that's the full exit; take it, the setup delivered its objective.
  - **TP hit on a runner** — the re-anchor play: tighten the stop to lock profit, then
    `TP:3:1` for a fresh runway (Strategy Lab guide).
- **Regime flip to RANGING** — the trend case weakened; trims get more aggressive.
- **THESIS names** (`C:TH X:T`): skip the technical wobble check entirely. The weekly
  question is only *"is the fundamental case intact?"* — price is not the input.
- **Stale flag** — old position, sub-hurdle growth, not income: it's renting capital a
  better idea could use. No forced action, but it must re-justify itself.

**What you never do mid-trade:** widen a stop, remove a stop "temporarily," override
the ladder because RR *looks* bad (deep-stop geometry, not a signal), or exit a THESIS
position on a technical drawdown that didn't touch the thesis.

---

## 6. Closing a position — the walkthrough

**Legitimate closes** (anything else is improvisation):

| Trigger | Applies to | Action |
|---|---|---|
| Stop hit | all | exit in full, no negotiation — this is the system working |
| Hard target reached | `X:H` TECHNICAL | exit in full at the objective |
| Trim ladder (M1/M2/TP × regime) | LADDER / RUNNER | partial exits per TRIM_MATRIX |
| Thesis broken | `C:TH` | exit on the *fundamental* invalidation, whatever price says |
| Runner's trailing stop hit | RUNNER | the tail is over; exit remainder |
| Stale money reallocation | flagged names | deliberate swap into a better idea |

**Mechanics:**
1. Execute at the broker.
2. `1` SYNC ALL — the sell lands; at zero qty **reset-on-zero** clears the lot cleanly
   (re-entry later starts a fresh basis, so closing fully is never "losing history").
3. Glance at `3` DASHBOARD — position gone, NAV and realized P/L sensible. Doubts →
   `5` MAINTENANCE reconciliation.
4. **The outcome logs itself** — the next time you open `9` EXPECTANCY, the backfill
   detects the close in the ledger and writes realized R, MAE/MFE, and the
   vs-benchmark result to the journal automatically (provided the trade was journaled
   at entry with `C:`/`SRC:`). Your only manual job is qualitative: note what worked
   and what didn't while it's fresh.
5. Keep the name on the WATCH LIST if the story isn't over — the scanner keeps
   watching for the re-entry zone; the clean ledger makes re-entry tracking exact.

---

## 7. The habit summary

| When | Do | Don't |
|---|---|---|
| Every session | sync, scan dashboard for flags, leave | tune stops daily |
| Weekly | migrate stops up, act on stages/regimes, scan zones, check heat | add trades when portfolio R% is maxed |
| Monthly | expectancy review, journal backfill, parameter sanity | change parameters mid-trade |
| Opening | classify → wait for zone → gates → size → commit → sync | buy mid-air on the day of the idea |
| Closing | honour the trigger table, sync, log realized R | "give it room" past the stop |
