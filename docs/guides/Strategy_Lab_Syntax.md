# Strategy Lab — Command Syntax

How to enter a stop-loss / sizing command in the Risk Workspace. The input box accepts
one command of the form:

```
VALUE [F/T]  [P:S/B/L]  [R:x]  [E:x]  [TP:n]  [C:TH/TE]  [X:H/R/T]  [G:gap]  [SRC:name]  [THM:theme]  [+N/-N]  [BE]
```

Tokens can appear in any order. Only the parts you want to change are required —
everything else is preserved from the saved profile.

---

## Stop type

### `F` — Fixed stop (absolute price)
You type the exact price where the stop sits. The system never moves it automatically.
To raise it later, type the new price and `CTRL+ENTER`. The **ratchet** ignores a re-saved
lower stop unless you explicitly intend it. TP is anchored to **entry + 3×ATR** (the ATR
stored at first save — the *inception* ATR).

```
156 F          → stop locked at 156.00
96.50 F        → stop locked at 96.50
```

### `T` — Trailing stop (distance from the high)
You type the gap between the high-water mark (HIGH P) and the stop. The stop auto-follows
the highest price since entry and never retreats. TP uses the same uniform **entry + 3×ATR**
ladder as Fixed. Three ways to express the distance:

1. **Dollar amount (default):**
   ```
   20.31 T        → stop = HIGH P − 20.31
   $8 T           → stop = HIGH P − 8.00   ($ prefix optional)
   ```
2. **Percentage of HIGH P:**
   ```
   5% T           → stop = HIGH P − 5% of HIGH P
   ```
3. **Target price (`@` prefix) — let the system compute the gap:**
   ```
   @156 T         → if HIGH P = 187.83, sets ATR distance = 31.83
   ```

All three honour the ratchet — if the resulting stop is lower than the saved stop, the
higher one is kept.

---

## Position-sizing overrides

### `P:S` / `P:B` / `P:L` — presets (set R and E together)

| Preset | Risk (R) | Exposure (E) | Crossover stop | Use case |
|---|---|---|---|---|
| `P:S` | 0.30% NAV | 1.5% NAV | 20% | speculative / high-vol |
| `P:B` | 0.60% NAV | 3.0% NAV | 20% | standard single-name |
| `P:L` | 1.00% NAV | 5.0% NAV | 20% | large cap / broad index |

**Crossover stop** = R ÷ E: the ATR distance at which both limits bind at once. Tighter stop
→ Risk binds (exposure stays under E); wider stop → Exposure binds (actual R stays under R).
*(Preset values come from the DB matrix; these are the shipped defaults.)*

### `R:x` / `E:x` — override one limit only
```
R:0.5          → max 0.5% of NAV at risk (keeps current E)
E:4.0          → max 4% of NAV in the position (keeps current R)
```

---

## Take-profit target — `TP:n`

Extends the top target beyond the default **entry + 3×ATR** (3R). The multiple is of the
**inception ATR** (frozen at first save), so the target does *not* drift when you later
tighten the stop. M1/M2 always stay at +1R / +2R.

| Command | Sets the target to |
|---|---|
| `TP:4` / `TP:4R` | entry + 4×inception ATR (the R is optional) |
| `TP:+35%` | entry +35% → multiple = (entry×35%)/ATR |
| `TP:$60K` | total open profit = $60,000 (needs share count) |
| `TP:3:1` | auto N:1 forward reward:risk vs the stop you're setting |
| `TP:-` | clears the override → back to default 3R |

**`TP:N:1` — anchor the target to the stop.** Sets `target = price + N×(price − stop)`. It
reads the stop from the *same* command, so `@655 T TP:3:1` locks a 655 floor and puts the
target exactly 3:1 above price. The result is frozen as an ATR multiple, so tightening the
stop later won't move it — re-run the command to re-anchor.

**When to use it — the re-anchor play.** Once price *reaches* the original 3R target the
ladder is maxed and the panel parks on "trim". That is the trigger to re-anchor: tighten the
stop to lock the open profit, then `TP:3:1` hands the winner a fresh 3:1 runway from here.

**3:1 guardrail.** With an override active the panel shows a **TARGET** line with the forward
reward:risk `(target − price)/(price − stop)`, flagged **⚠ below 3:1** if it drops under 3.0
(`RR_SETUP_FLOOR`). This is informational, not an exit.

---

## Trade character — classify, shape the exit, size for gaps

These three tokens come from the **Entry & Stop System** (§0a, §5a, §6). They describe
*what kind of trade this is* rather than where the stop sits. All are optional and
default-off — omit them and the trade behaves exactly as before. Each is **sticky**: once
saved it is preserved until you change it (`:-` clears it back to the default).

### `C:TH` / `C:TE` — classify the idea (THESIS vs TECHNICAL)

Tags *why you are in the trade*. The two are managed on different clocks, and blending
them is the most common quiet loss — a multi-year fundamental hold exited on a 15%
technical wobble that never invalidated the thesis.

| Token | Classification | You're in because… | Invalidation is… |
|---|---|---|---|
| `C:TH` | **THESIS** | a fundamental case (often slow, multi-year) | the *fundamental* reason is gone |
| `C:TE` | **TECHNICAL** | a structural setup (a defined chart level) | the structural stop |
| `C:-` | *clear* | — | back to unset |

The tag is **carried and displayed** (a chip shows while you draft, and a classified commit
writes a row to the decision journal for the expectancy report) — it does **not** itself
change the stop or exit. To make a THESIS trade actually exit on thesis-only, pair it with
`X:T` (below).

```
C:TH           → tag this position THESIS (fundamental clock)
C:TE           → tag this position TECHNICAL (structural clock)
15 T C:TH X:T  → trailing 15%, tagged THESIS, thesis-only exit (the full "one clock" pairing)
```

### `X:H` / `X:R` / `X:T` — exit shape (how you bank being right)

Sets the **exit shape at entry**, alongside the stop. The stop says *where you're wrong*;
the exit shape says *how you take the win*. They are two separate decisions — never let one
imply the other.

| Token | Shape | What it does |
|---|---|---|
| `X:L` | **Ladder** *(default)* | today's regime-aware M1/M2/TP ladder — scale out, trail a runner |
| `X:R` | **Scale + runner** | same as the default ladder (explicit) — partial at objective, runner trails |
| `X:H` | **Hard target** | a TECHNICAL setup with a defined objective: bank the **full** position at the TP stage, no runner |
| `X:T` | **Thesis exit** | **drops the price target** entirely — exit on stop or broken thesis only |
| `X:-` | *clear* | back to the default ladder |

Only `X:H` and `X:T` change behaviour; both are opt-in hooks on the existing ladder.
`X:T` is the natural partner of `C:TH` — a fundamental hold should not carry a
guessed-at-entry price target.

```
X:H            → hard target: exit in full at the objective (defined TECHNICAL setup)
X:T            → thesis exit: no target, ride until stop/thesis breaks
X:R            → explicit scale-out + runner (same as default)
```

### `G:<price>` — gap-aware sizing (size for the gap, not the level)

For names held through a known event (earnings/catalyst), a structural stop won't survive
an overnight gap. `G:` supplies the **plausible post-event gap price** and sizes off
`R_gap = entry − gap_price` instead of `R₁ = entry − stop` — so the position is small
enough that the *gap*, not the clean stop, stays within your risk budget. Opt-in: omit it
and sizing stays on the standard fixed-fractional path.

```
150 F G:135     → fixed stop 150, but size as if a stop-out slips to 135 (the gap)
```

If gap-aware sizing shrinks the trade to something not worth taking — that's the event gate
working, not a bug.

### `SRC:name` / `THM:theme` — journal the idea's origin

Feeds the **decision journal** (Entry & Stop System §7) so the expectancy report can
benchmark the *source* of your ideas, not just your execution. Single uppercase tokens,
no spaces (e.g. `SRC:ZACKS`, `THM:SEMIS`, `THM:JAPAN`).

- A commit carrying `SRC:` **or** `C:` writes a journal row (date, source, theme, tag,
  entry, stop, R₁). No token → no row, exactly as before.
- These are journal-only: they are *not* stored on the risk profile, so type them on the
  commit that opens the trade.
- The outcome fields (realized R, MAE/MFE, vs-benchmark) are backfilled **automatically**
  when the position later closes — see the Expectancy report (menu 9).
- The other half of the funnel — source picks you *didn't* take — is logged from the
  **Watch List** (`L` key → skipped-pick form). After ~20–30 picks per source, menu 9
  answers whether the source beats the benchmark at all.

```
@156 T C:TE X:H SRC:ZACKS THM:SEMIS   → full journal row: technical breakout from Zacks
15% T C:TH SRC:OWN THM:JAPAN          → thesis hold, own research, Japan theme
```

---

## Quantity modeling (what-if, nothing saved)

Test buying/selling at the current market price and watch the sizing table update P/L@Stop,
R%, Exp%, HCM, and the new average cost.

```
+26            → model buying 26 more shares at the live price
-50            → model selling 50 shares
BE             → goal-seek: how many shares to buy so P/L@Stop = 0
```

`BE` solves the buy that pulls your average cost onto the stop (break-even at a stop-out).
Watch Exp% — it may turn red if the required size breaches your exposure cap. If break-even
can't be reached by buying, it says so.

---

## Combined examples

```
20.31 T P:B     → trailing $20.31, standard preset
@156 T P:L      → trailing floor at 156, large-cap preset
5% T R:0.5      → trailing 5%, custom risk limit of 0.5%
156 F           → fixed stop at 156, no preset change
18.13 T TP:4R   → tighten trailing stop AND extend the target to 4R
@655 T TP:3:1   → trailing floor at 655 AND target auto-set to 3:1 vs that stop
TP:+35%         → set only the target to +35% from entry
R:0.5           → change only the risk limit, keep everything else
15 T C:TH X:T   → trailing 15%, THESIS trade, thesis-only exit (no price target)
@200 F C:TE X:H → fixed floor 200, TECHNICAL trade, hard target (bank in full)
150 F G:135     → fixed stop 150, sized for a plausible gap down to 135
```

---

## R-compliance restore

When risk is YELLOW or RED the execution desk shows two paths:

- **A) Raise stop → [price]** — the minimum stop to restore compliance at current qty.
  FIXED: type that price and `CTRL+ENTER`. TRAILING: type `@[price] T` and `CTRL+ENTER`.
- **B) Trim [N] shares** — shares to sell so risk at the current stop falls within the R limit.

---

## Settings & entry gates — the `M` modal

Press **`M`** to open the Presets / Settings modal. It edits three things that shape
*every* trade, then persists them (`CTRL+ENTER` to commit the modal, `ESC` to cancel):

- **Preset definitions** — the R% / Exposure% behind `P:S` / `P:B` / `P:L`. Change them
  here and every future use of that preset (and existing profiles on it) updates.
- **Action threshold (% of position)** — how far off-target a position must drift before
  the workspace surfaces an *Add* / *Trim* action, filtering transaction noise
  (default 10%; ≥10% remaining → Add, ≥5% → Trim).
- **Entry gates (`off` / `advisory` / `blocking`)** — the §4 hard-gate check that runs on
  commit (see below).
- **Regime lens (`default` / `horizon`)** — which DMA the trim-driving regime is judged
  on. `default` = 200-DMA for every position (today's behaviour). `horizon` = match the
  lens to the horizon the **stop declares**: a stop about one daily ATR wide (e.g. a
  leveraged-ETF trade) → 50-DMA with faster confirmation (TREND ≥ 10d); a weekly-ATR
  stop → 100-DMA (≥ 15d); a wide monthly-ATR conviction stop → 200-DMA, unchanged. The
  regime string names a non-default lens, e.g. `BUY (12d, DMA50)`.

### Entry gates (G1–G8)

An opt-in pre-trade validator (Entry & Stop System §4). On commit each drafted trade is
run through eight gates; a gate is a **stop sign, not a size penalty**. Only an explicit
**FAIL** blocks — a gate whose inputs are missing returns **NA** and never blocks, so
partial context degrades gracefully.

| Mode | What happens on commit |
|---|---|
| `off` *(default)* | gates never run — commits behave exactly as before |
| `advisory` | gates run and warn, but the commit still goes through |
| `blocking` | an explicit gate **FAIL** stops the commit until you fix or downgrade the mode |

| Gate | Checks |
|---|---|
| G1 | Stop-width — `R₁ ≤ 1.5×ATR` and `R₁/entry ≤ 8%` (a wide stop = wrong location) |
| G2 | Basis quality — tight `stop_source` and ≥2 *independent* confluent levels |
| G3 | Not a fallback artifact — reject an unflagged MOMO row on a double-digit `VAL_*` stop |
| G4 | Event — no new entry within N days of earnings/catalyst (size for the gap if held through) |
| G5 | Extension — don't initiate > 2 ATR above the anchor you'd trail from (chasing) |
| G6 | Liquidity — size ≤ a fraction of ADV; modeled slippage within budget |
| G7 | Portfolio & theme heat — `Σ R%` over correlated names / themes ≤ heat cap |
| G8 | Currency — measure R% and exposure in your base currency |

Thresholds are tunables (`constants.py`, `GATE_*`), meant to be calibrated from the log —
not laws. Full rationale in the **Stop Playbook** / Entry & Stop System guide.

---

## Controls

| Key | Action |
|---|---|
| `ENTER` | Model hypothetically — updates the grid without saving |
| `CTRL+ENTER` | Commit the current draft permanently to the database |
| `S` | Save all pending drafts at once (runs the entry gates per mode) |
| `M` | Open the Presets / Settings modal (presets, action threshold, gates mode) |
| `G` | Launch the price chart (200-DMA, 5Y) for the selected row |
| `R` | Refresh the portfolio from the ledger |
| `F1` | Open this help |
| `Q` | Back / exit the workspace |
