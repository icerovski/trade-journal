# Trade Journal — User Guide

How to operate the software, task by task. This guide is the **how**; the strategy
guides (*Entry & Stop System*, *Stop Placement Playbook*, *Exit Strategy*) are the
**why**. Every walkthrough below names the menu option and the exact keys/commands.

---

## 0. Mental model — what this software is and is not

- **It does not place orders.** You execute at IBKR; the app ingests the fills.
  The software's job is everything *around* the order: deciding whether to trade,
  where the stop goes, how big, when to trim, and whether your decisions are
  actually making money.
- **Positions are never typed in.** They are derived by replaying the `trades`
  ledger (synced from IBKR). If a position looks wrong, the fix is always a data
  fix (re-sync, re-ingest), never a manual edit.
- **Two ledgers, two jobs.** `trades` records what *happened* (executions, synced
  automatically). `trade_log` records what you *decided* (the journal that feeds
  expectancy) — you feed it by classifying commits and by the capture prompts in
  the Expectancy report.
- **Risk lives in an overlay.** Stops, budgets, classifications, and exit shapes
  are stored per ticker in `risk_profiles` and edited only in the Risk Workspace.

The operating loop everything hangs on:

```
Idea → Watch List [6] → Zone Scanner [8] → Risk Workspace [2] (stop/size/commit)
     → execute at IBKR → SYNC ALL [1] → manage (Dashboard [3] / Risk Workspace [2])
     → close → Expectancy [9] backfill → (the log tunes your next idea)
```

**Operating cadence** — how often you actually open this thing:

| Rhythm | Time | What |
|---|---|---|
| Daily | ~2 min | Dashboard [3]: breaches and the ACTION column. Nothing flagged = close the app. |
| Per idea | as needed | §3–§5 for a new name, §6 for an add. |
| Weekly | ~20 min | The §15 routine: sync, full rescan, walk the PLAN strip, portfolio heat, clear the backfill queue. |
| Quarterly | ~1 h | The §15 quarterly review: expectancy, source funnel, parameter tuning. |

Most days the system's correct output is *nothing to do*. That is it working, not
you underusing it.

---

## 1. Screen index

| # | Screen | Job | Writes anything? |
|---|---|---|---|
| **[1]** | SYNC ALL | Pull IBKR history + open-positions snapshot, ingest confirmations, sync prices | `trades`, `prices.db` |
| **[2]** | RISK WORKSPACE | The cockpit: model stops, size trades, commit decisions, read the per-position verdict | `risk_profiles`, `trade_log`, `settings` |
| **[3]** | DASHBOARD | Live monitoring: P/L, breach highlighting, stop distances | read-only |
| **[4]** | KIDS FUND | Private-wealth glide-path audit | read-only |
| **[5]** | MAINTENANCE | Surgical rebuild, CSV re-ingest, manual price sync | `trades`, `prices.db` |
| **[6]** | WATCH LIST | Add and monitor prospects; confluence distances; 200-DMA trend signals | `risk_profiles` (WATCH rows) |
| **[7]** | PORTFOLIO RISK | Aggregate heat: total R%, stop-out loss, HHI concentration, FX breakdown | read-only |
| **[8]** | ZONE SCANNER | Structural read on the whole universe: volume profile + AVWAP + MA confluence, stop proposal, preset sizes | `scan_context`, handoff |
| **[9]** | EXPECTANCY | Journal analytics (E[R] per archetype, source funnel) + the two capture prompts | `trade_log` |

**Keys by screen** (Textual apps; `F1` opens the in-app help everywhere it's listed):

| Screen | Keys |
|---|---|
| Risk Workspace [2] | `s` save all drafts · `r` refresh · `m` presets/settings modal · `g` chart · `F1` help · `q` back |
| Dashboard [3] | `r` refresh · `1–4` sort · `a/s/o/b/t` asset filters · `g` chart · `F1` help · `q` exit |
| Watch List [6] | `a` add prospect · `d` delete · `r` refresh · `g` chart · `q` exit |
| Zone Scanner [8] | `r` rescan · `c` hand off selected row to Risk Workspace · `q` exit |
| Expectancy [9] | prompt at the end: `b` backfill closed lots · `k` log a skipped pick · Enter exit |

---

## 2. Task index

| I want to… | Section |
|---|---|
| Add a new ticker I like (e.g. AAPL) to the system | §3 |
| Decide entry, stop, and exit for it | §4 |
| Size it and commit the decision | §5 |
| Add to an existing position after a dip (e.g. MSFT −10%) | §6 |
| Know when/how much to take profit | §7 |
| Handle a stop that just got hit | §8 |
| Decide hold-through vs de-risk before earnings | §9 |
| Close the journal loop after an exit / log a skipped pick | §10 |
| Run a longer-horizon (3–6 month) idea | §11 |
| Reduce risk when the book runs too hot | §12 |
| Raise cash — decide what to sell first | §13 |
| Do the daily/weekly data routine | §14 |
| Review the book and my own edge | §15 |
| Look up the command-box grammar | §16 |
| Change presets, gates, thresholds | §17 |

---

## 3. Task: "I like AAPL — get it into the system"

Two entry points; both end in the same place (a `WATCH` risk profile).

**A. The dedicated flow (default):**
1. Menu **[6] WATCH LIST** → press **`a`** → type `AAPL` → Enter.
2. The worker resolves the Yahoo symbol, stamps the pricing currency (so later
   sizing uses the right FX rate), and stores the prospect as `status='WATCH'`.
3. The row now shows confluence distances to structural levels (in Daily-ATR
   units — under 0.25 ATR is a meaningful zone) and the 200-DMA trend signal
   (🟢 BUY / 🔴 SELL after a 21-day confirmation).

**B. Ad-hoc from the Risk Workspace:** type the ticker into the discovery input
in **[2]**. A `[PROSPECT]` row appears with full ATR discovery; it is ephemeral
until you draft a stop on it and press `s` — that save persists it as WATCH.

Once a ticker is WATCH it is part of the **scan universe**: the Zone Scanner and
Watch List both track it, and its prices are fetched on demand.

> A prospect costs nothing. Add liberally, let the scanner tell you when one of
> them actually sets up.

---

## 4. Task: "Decide entry, stop, and exit for AAPL"

The decision framework is *Entry & Stop System* §9/§11; this is the button-level
version.

1. **Classify first: THESIS or TECHNICAL.** One decision, made before any chart.
   It decides which clock invalidates the trade (fundamental case vs structural
   stop) and which exit shape fits. You'll encode it at commit as `C:TH` / `C:TE`.

2. **Menu [8] ZONE SCANNER.** Find the AAPL row and read the tag:
   - **`ZONE`** — value setup: ≥2 independent structural levels within 0.25 ATR.
     A candidate.
   - **`ZONE-MOMO`** — momentum with a real micro-shelf below price;
     `stop_source` names the winning anchor (`VAL_14d`/`HVN_14d`/`AVWAP_14d`/`GAP_14d`).
   - **`THIN`** — fewer than 2 independent levels. Weak basis; that is gate G2
     telling you to wait.
   - **No tag + a double-digit `VAL_*` stop** — mid-air (Scenario C). **No trade;
     wait for the re-flag.** This "no" is a first-class output of the system.
   The scan also writes `scan_context` — the structural inputs the entry gates
   read at commit time. **Scan before you commit**, or gates G2/G3/G5 come back
   NA instead of giving a real read.

3. **Read the proposed stop and target** in the row (stop, structural target,
   and the position size each preset would allow).

4. **Decide the exit shape now** (before sizing — it's part of the same
   decision):
   - *Default ladder* (scale-out + runner): no token needed. Trims at
     milestones, lets the tail run. Right for most trades.
   - *Hard target* (`X:H`): full exit at TP. Only for TECHNICAL trades with a
     defined objective.
   - *Thesis exit* (`X:T`): no price target at all; the trade ends when the
     thesis is met or broken (or the stop is hit).

5. **Press `c` on the flagged row.** This stores a one-shot handoff; the next
   launch of the Risk Workspace opens with the command box prefilled with the
   scanner's stop for AAPL. Continue in §5.

---

## 5. Task: "Size it and commit"

In **[2] RISK WORKSPACE**, with the AAPL prospect row selected (or prefilled by
the handoff):

1. **Type the command** — for example:

   ```
   182.50 F P:B C:TE
   ```

   = fixed stop at 182.50, Balanced preset, classified TECHNICAL. The table
   updates live as you type: modeled stop %, **R% vs cap**, **NAV-exposure % vs
   cap**, P/L at stop, and — because a prospect has qty 0 — the ACTION column
   shows **`BUY N`**: the maximum quantity under the *tighter* of the two preset
   constraints (risk % and exposure %), FX-normalized. That number is your size.

2. **Holding through earnings?** Add `G:` with a plausible gap price
   (e.g. `G:170`) — sizing then risks against the gap, not the stop. If the
   resulting size is too small to bother, that's the event gate doing its job.

3. **Press Enter** to lodge the draft (you can draft several rows before
   saving), then **`s` = Save All**. On save, the **entry gates** run per the
   `gates_mode` setting:
   - *advisory* (current default): failures print, the save proceeds — you are
     the judge. Treat a FAIL as a stop sign, not a footnote.
   - *blocking*: a FAIL blocks that row's save.
   A classified commit also **upserts the `trade_log` row** — this is what feeds
   the expectancy engine. Uncommitted or unclassified decisions never make it
   into your edge statistics, so tag every real entry.

4. **Execute at IBKR** at your trigger price, then run **[1] SYNC ALL**. The
   fill lands in the ledger, the position appears with your stop and profile
   attached, and the dashboard starts auditing it.

> **The gates in plain terms** — G1 stop not too wide (≤1.5×ATR and ≤8% of
> entry; the 3–6mo lens widens this, §11), G2 stop based on ≥2 independent
> levels, G3 not a Scenario-C fallback artifact, G4 no entry within 5 days of
> earnings, G5 not chasing >2 ATR above the trail anchor, G7 portfolio heat
> within cap, G8 risk measured in base currency. G6 (liquidity) is a permanent
> NA for this book.

---

## 6. Task: "MSFT fell 10%, I still believe — do I add, and how much?"

The system answers this in a specific order. Skipping steps is how averaging
down turns into a funeral.

**Step 1 — Has the stop been hit?** Check the dashboard [3] or the MSFT row in
[2]. A **`BREACH`** highlight / **`EXIT`** action means this is not an
add-opportunity conversation — the position's invalidation fired. "I still
believe" on a breached stop means the stop was on the wrong clock when you set
it (a technical stop on a thesis trade); the fix for *next* time is `C:TH` with
a thesis-appropriate stop, not overriding this one.

**Step 2 — Which clock is the trade on?** If MSFT is classified **THESIS**, a
10% technical wobble is noise unless the *fundamental* case changed — re-read
the thesis, not the chart. If **TECHNICAL**, the structure is the thesis: go
straight to the scanner.

**Step 3 — Did the dip land on structure?** Rescan in **[8]**. Adding is a *new
entry* and must clear the same bar as any entry: a defended level below price.
- Dip landed on a flagged zone (value reclaim / pullback to an anchor that
  holds) → a legitimate add setup.
- Mid-air, no shelf below → **no add**, whatever your conviction. Wait for the
  re-flag.

**Step 4 — How much? Let the workspace answer.** Select MSFT in [2] and read
the verdict panel:
- **`ADD +N sh`** — N is the room to your exposure cap under the active preset,
  at the current price. This is the ceiling, not a recommendation to fill it.
- The **ACTION column** shows `+x%` only when the room exceeds the action
  threshold (default 10% of the position), so transaction noise is filtered.
- A position at a profit-taking stage never shows ADD — headroom is reported
  but muted; the ladder governs.

**Step 5 — Model the exact add before doing it.** In the command box:
- **`+50`** — models buying 50 shares at the live price: blended average cost,
  new R%, new exposure %, and **P/L@Stop** (the honest number: total damage if
  the stop is hit *after* the add).
- **`BE`** — goal-seek: solves for the quantity that brings P/L@Stop to zero
  (the add that makes the whole position break-even at the stop).
- The R% and NAV% cells turn yellow/red the moment the modeled add breaches a
  cap.

**Step 6 — Re-anchor the stop only if the scan found new structure — and only
upward.** `Never widen a live stop to make room for an add.` If the new
structural stop from Step 3 is above the old one, migrate up (type the new
value with the add in one command, e.g. `340 F +50 C:TH`); if it would be
lower, the add is sized against the *existing* stop or not at all.

**Step 7 — `s` to save** (gates run — G4 matters here if earnings are near),
execute at IBKR, **[1] SYNC ALL**.

---

## 7. Task: "It's working — when do I take profit?"

You mostly don't decide this in the moment; the ladder decided it at entry.
Your job is to read the directive and execute it.

- **Milestones are entry-anchored R-multiples:** M1 = entry + 1R, M2 = +2R,
  TP = +3R (R = the frozen inception ATR; override the top rung with `TP:n`).
  The live trailing ATR moves only the *stop*, never the ladder.
- **The regime modulates the ladder:** TREND (≥21 days above a rising 200-DMA)
  holds where NORMAL trims; RANGING trims harder. The `(stage, regime)` matrix
  is in *Exit Strategy* / TECHNICAL_DOCS §5.
- **Read the ACTION column** in [2]: `TRIM 25%` (do it), `HOLD` (ladder says
  let it run), `STOP→E` (move the stop to entry — the position becomes
  risk-free), `EXIT` (stop breached). The verdict panel gives the same
  directive with the reasoning and the share count.
- **Exit-shape overrides:** `X:H` positions fully exit at TP; `X:T` positions
  show no TP at all — their exit is your thesis review plus the stop.
- **RR is informational only.** A low RR on a deep-stopped winner is geometry,
  not a sell signal. Exits come from the stop, the ladder, and the regime.
- **⏳ STALE** in the PLAN panel is the capital-efficiency nudge: the position
  is old and compounding below the hurdle. It is orthogonal to the ladder —
  review the thesis or redeploy; income assets are exempt.

---

## 8. Task: "My stop was hit"

The path that ends most trades, so it gets its own section. The whole point of
setting the stop when you were calm is that *this* moment requires no thinking.

1. **Recognize it.** Dashboard [3] and Risk Workspace [2] both flag it: the
   price cell goes red with a **`BREACH`** tag, the ACTION column shows
   **`EXIT`**, and the verdict panel reads *"EXIT NOW — stop breached. Sell all
   N sh."* The P/L column switches from the planned loss to the **degraded live
   exit** — what you'd actually realize at the current price, which after a gap
   is worse than the plan.
2. **Execute at IBKR. Do not renegotiate.** No widening, no "giving it room",
   no reclassifying to THESIS to avoid selling — the classification was set at
   entry precisely so it can't be changed under pressure. If you genuinely
   believe the stop was on the wrong clock, that lesson goes into the *next*
   entry's `C:` tag, not into this exit.
3. **[1] SYNC ALL.** The sell lands in the ledger; reset-on-zero clears the
   cost basis. If you re-enter later, it is a *brand-new decision*: fresh scan,
   fresh gates, fresh journal row — not "getting back in."
4. **[9] → `b`.** Backfill the realized R. A clean stop ≈ −1R; a gap-through
   fill is worse, and logging it honestly is what powers the quarterly "are
   losses averaging > 1R?" check (slippage/gap calibration).

> If price pierced the stop intraday and recovered before you saw it, the
> breach still happened — your buffer was inside the noise. Log it mentally for
> the buffer review (§15) even if you're still in the position.

---

## 9. Task: "Earnings next week on a position I hold"

Gate G4 stops *new* entries near events. For a position you already hold, the
question is **hold-through vs de-risk**, and the key fact is that a structural
stop does not protect you through a gap — price can open far below it.

Model the gap before it happens, in [2] with the position selected:

1. **Pick a plausible gap price** — e.g. the stock's typical earnings move, or
   its worst recent one. Say the stop is 350 but a bad print could open at 330.
2. **Type the gap price as a hypothetical fixed stop:** `330 F`. The P/L@Stop
   and R% readouts now show the *gap-through* damage — the honest worst case —
   instead of the planned loss at 350.
3. **Too much? Model a pre-earnings trim:** `330 F -50`. The verdict panel
   models selling 50 shares at the live price and the risk breakdown shows the
   before/after (BAL-BEG → ADD → BALANCE). Iterate the share count until the
   gap damage fits your mandate.
4. **Nothing persists unless you press `s`** — this is pure what-if. Re-enter
   your real stop (or just don't save), execute the trim at IBKR if you decided
   on one, then [1] SYNC ALL.
5. **After the event, rescan [8].** Earnings gaps reshape structure — a gap
   floor often becomes the next defended anchor, and your stop may have new,
   higher structure to migrate to.

(For *prospects*, this modeling is built into sizing: the `G:` token in §5
risks against the gap automatically.)

---

## 10. Task: "I closed a trade" / "I skipped a pick" — feed the journal

The expectancy engine is only as good as its diet. Two habits, both in
**[9] EXPECTANCY**, both under a minute:

- **`b` — backfill closed lots.** The report lists every journaled decision
  whose position has since closed. For each, it suggests the realized R from
  your actual ledger sells (avg exit vs entry/stop); Enter accepts, or type a
  correction, `s` skips. Do this after every exit (or batch weekly).
- **`k` — log a skipped source pick.** Ticker, source, note; the price is
  stamped automatically. Skipped picks are the *control group* — without them
  the source-vs-benchmark funnel can't tell whether your newsletter has edge or
  you're cherry-picking its winners.

After ~20–30 logged decisions the per-archetype **E[R]** table and the source
funnel become meaningful. Until then, the rule from the Entry & Stop System
holds: every archetype is unproven → starter size only.

---

## 11. Task: "This is a 3–6 month position, not a swing"

The default machinery (daily ATR, 14-bar micro window, ~1.3% buffers) will
shake you out of a multi-month hold. Switch the lens *before* scanning:

1. In [2], press **`m`** → set `Calibration lens` to `position_3to6mo` →
   `Ctrl+S`.
2. The active lens shows in the Risk Workspace and Zone Scanner **headers** —
   always glance there so you know which mode you're in.
3. What changes: the scanner anchors to weekly value structure (VAL_6mo/12mo,
   30-week MA) with a longer ATR and wider buffers; a MOMENTUM flag **disables
   the micro-stop** (read it as "extended — don't chase") and falls back to the
   weekly anchors; gate G1 tests the weekly-ATR/~18% caps instead of the daily
   1.5×ATR/8%.
4. Trade the same §4–§5 flow, typically with `C:TH` and often `X:T`.
5. **Flip back to `default`** for swing work — the lens is global, not
   per-trade.

---

## 12. Task: "The book feels too hot — reduce risk"

Position-level discipline can still add up to a portfolio problem: every stop
individually fine, the *sum* over your mandate. The instrument for this is
**[7] PORTFOLIO RISK**; read it top to bottom:

- **Portfolio R% (total risk at stop)** vs **Risk budget used / Budget
  headroom** — red headroom means the book is carrying more open risk than the
  per-position budgets allow in aggregate.
- **P/L if all stops hit** — the stop-out loss in NAV currency. The question to
  ask: *if a single macro day fired every stop, is this number survivable and
  acceptable?* If reading it makes you flinch, the book is too hot regardless
  of what the budgets say.
- **Breached** list in the header — those aren't part of this conversation;
  they are §8 exits. Do them first.
- **Concentration** (Top 5 by Exposure / by Risk, HHI) and the **currency
  breakdown** — heat that hides from per-position math.

Then deleverage in order of cost, cheapest risk reduction first:

1. **Tighten stops to structure.** Rescan [8]; wherever price has built new,
   higher structure, migrate the stop up (never into noise — the buffer rules
   still apply). This cuts Portfolio R% without selling anything.
2. **Take the ladder's overdue trims.** Any position showing `TRIM x%` in the
   ACTION column is risk reduction the system already ordered.
3. **Trim the Top-5-by-Risk names.** The biggest R% contributors buy the most
   heat reduction per transaction.
4. **Cut STALE and thin-basis positions outright** — dead money is exposure
   without a live setup behind it.

Re-run [7] after executing and syncing; you're done when headroom is green and
the stop-out number reads as tolerable.

---

## 13. Task: "I need to raise cash"

The family-office scenario: capital is needed elsewhere and something must be
sold. The system's answer is a ranking, so the sale costs the book as little
edge as possible. Sell in this order:

1. **Breached positions** (§8) — those sales were already owed.
2. **⏳ STALE flags** in the [2] PLAN panel — capital compounding below the
   hurdle. Selling dead money costs nothing but the regret of admitting it.
   (Income assets are exempt from the flag — don't strip your yield sleeve by
   accident.)
3. **Positions at a profit-taking stage** — the ladder wanted a trim there
   anyway; take the trim fraction, or more, and keep the runner if the regime
   still says TREND.
4. **Lowest-E[R] archetypes** per the [9] report — cut where your own log says
   the edge is thinnest.
5. **Only then healthy, on-thesis positions** — prefer trimming several
   pro-rata over killing one entirely; use Top 5 by Exposure in [7] if
   concentration should shrink at the same time.

Two checks before executing: the **currency breakdown** in [7] (if the cash
need is in EUR/BGN, selling USD names adds an FX conversion to the trade), and
G4 (don't be forced into selling *into* an earnings print if a day's patience
avoids it). Afterwards: [1] SYNC ALL, and [9] `b` for any lot the sale fully
closed.

---

## 14. Task: the data routine (keeping the machine honest)

- **Session start:** **[1] SYNC ALL** — trade history, open-positions snapshot,
  confirmations, price cache. Everything downstream assumes this ran.
- **Session end:** exit via **[0]** (the `.env` backup hook runs on exit), and
  run the OneDrive backup when reminded: `uv run python sync_config.py`.
- **Something looks wrong** (ghost position, wrong cost basis): **[5]
  MAINTENANCE** → option 1 *Rebuild Trades* wipes only the `trades` table and
  replays every local CSV — risk profiles and settings survive. Option 3
  re-ingests all local CSVs without wiping. Because positions are pure
  functions of the ledger, a replay is always safe.
- **Prices stale / new WATCH ticker:** [5] → option 4, or just rescan in [8]
  (it fetches missing history on demand).

---

## 15. Task: reviews — the loop that tunes the system

**Weekly (weekend):**
1. **[1]** sync, then **[8]** full rescan — refreshes every ticker's
   `scan_context` so the coming week's gate checks run on fresh structure.
2. Walk the **[2]** PLAN strip position by position: exit stages, regimes,
   breaches, STALE flags. Manage-existing rules: migrate stops **up** to new
   structure, never down, never wider; at a structural objective, trim per the
   ladder.
3. **[7] PORTFOLIO RISK** — total open R%, loss-if-every-stop-fires, HHI
   concentration, currency exposure. This is the G7/G8 view of the book.
4. **[9]** — clear the backfill queue.

**Quarterly:** read the Entry & Stop System §7 review table against your log —
seven questions (does the source beat the benchmark net of cost? are winners
capped before the runner runs? are losses averaging >1R?), each mapped to a
specific parameter to tune (§8). This is the point where the default numbers
stop being guesses and become *your* calibration.

---

## 16. Reference: the Risk Workspace command box

Grammar: `VALUE [F/T] [P:S/B/L] [R:x] [E:x] [TP:n] [C:TH/TE] [G:gap] [X:H/T] [+N/-N] [BE]`
— tokens in any order, all optional except that a stop needs a value + type.

**Stop value:**

| You type | Meaning |
|---|---|
| `350 F` | FIXED stop at price 350 (value = literal stop price) |
| `15% T` | TRAILING, 15% below the high-water mark |
| `19.6 T` (or `$19.6 T`) | TRAILING, fixed $19.60 distance below HWM |
| `@340 T` | TRAILING anchored to price 340 (distance = HWM − 340) |

**Modifier tokens:**

| Token | Effect |
|---|---|
| `P:S` / `P:B` / `P:L` | Apply preset (Small/Balanced/Large exposure & risk caps) |
| `R:0.8` | Override max R% for this position |
| `E:6` | Override max exposure % |
| `TP:2.5R` | Top rung at 2.5× inception ATR (default 3R) |
| `TP:+35%` | Top rung at +35% over entry |
| `TP:N:1` | Top rung at N:1 forward reward:risk vs the modeled stop |
| `TP:-` | Clear the override (back to default) |
| `C:TH` / `C:TE` | Classify THESIS / TECHNICAL — **triggers the journal upsert** |
| `G:330` | Gap-aware sizing: risk against min(stop, 330) |
| `X:H` / `X:T` | Exit shape: hard target / thesis (default ladder needs no token; `X:R` = legacy alias of it) |
| `+50` / `-25` | Model buying/selling N shares at the live price |
| `BE` | Goal-seek the add quantity that brings P/L@Stop to zero |

**Worked examples:**

```
182.50 F P:B C:TE              new technical entry, fixed stop, Balanced preset
15% T P:L C:TH X:T             thesis position, 15% trailing, Large, no price target
340 F +50 C:TH                 raise stop to 340 and model a 50-share add
BE                             how many shares to add for break-even at the stop
TP:N:1                         re-anchor the target to 1:1 forward RR (the re-anchor play)
```

Draft with **Enter**, commit everything with **`s`**. `Esc`/retype to revise a
draft before saving.

---

## 17. Reference: settings (the `m` modal in [2])

| Setting | Values | What it does |
|---|---|---|
| Preset matrix | E% / R% per `S`/`B`/`L` | The exposure and risk caps each `P:` token applies |
| Action threshold | % (default 10) | Minimum add/trim size before the ACTION column speaks |
| Entry gates | `off` / `advisory` / `blocking` | Whether gates print or enforce at save (currently advisory) |
| Calibration lens | `default` / `position_3to6mo` | Swing vs 3–6mo machinery everywhere (§11) |

`Ctrl+S` commits the modal; `gates_mode` and the lens show in the workspace
header banners.

---

## 18. Where to go deeper

| Question | Guide (all in F1) |
|---|---|
| What does this indicator/level mean? | *Indicator Glossary* |
| Where does a stop belong, mechanically? | *Stop Placement Playbook* |
| Should I take this trade at all? | *Entry & Stop System* (gates §4, decision flow §9, pre-trade sheet §11) |
| How do exits/trims work in detail? | *Exit Strategy* + TECHNICAL_DOCS §5 |
| What is the scanner actually computing? | *Zone Scanner Guide* |
| Longer-horizon recalibration | *Horizon Calibration 3-to-6mo* |
