# Strategy Lab — Command Syntax

How to enter a stop-loss / sizing command in the Risk Workspace. The input box accepts
one command of the form:

```
VALUE [F/T]  [P:S/B/L]  [R:x]  [E:x]  [TP:n]  [C:TH/TE]  [G:gap]  [X:H/T]  [+N/-N]  [BE]
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
| `TP:3:1` | auto N:1 forward reward:risk vs the stop you're setting |
| `TP:-` | clears the override → back to default 3R |

*(The absolute-$ form `TP:$60K` was removed — `TP:nR` and `TP:N:1` carry the real use
cases. A `$`/`K` token is rejected with a warning.)*

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

## Entry & Stop System tokens (all optional, default-off)

### `C:` — Trade classification (THESIS / TECHNICAL)

Tags *why* the trade exists. Information only — no exit logic branches on it — but a
classified commit also writes a row to the decision journal (`trade_log`) for the
expectancy report (menu 9).

```
C:TH           → tag THESIS   (own the story; exit when the story breaks)
C:TE           → tag TECHNICAL (own the level; exit at the objective)
C:-            → clear the tag
```

### `X:` — Exit shape (how the trade is banked)

Decided at entry alongside the stop. The default (no token) is the regime-aware
M1/M2/TP ladder — scale out at the objective, runner behind the trailing stop.

```
X:H            → Hard target: bank the FULL position at TP, no runner
X:T            → Thesis exit: no price target at all; stop/thesis only
X:-            → back to the default ladder
```

*(`X:R` is still accepted as a legacy alias of the default ladder — it was never
behaviourally distinct. There is no time stop: no shape exits on elapsed time.)*

### `G:` — Gap-aware sizing (event risk)

Supplies a plausible post-event gap price for a name entered through a catalyst.
Sizing then risks against the **larger** of R₁ (entry − stop) and R_gap
(entry − gap price), which can only shrink the size. Modeling shows a
`GAP-SIZED @ …` chip.

```
480 F G:440 P:B   → stop 480, but sized as if the exit fills at 440
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
```

---

## R-compliance restore

When risk is YELLOW or RED the execution desk shows two paths:

- **A) Raise stop → [price]** — the minimum stop to restore compliance at current qty.
  FIXED: type that price and `CTRL+ENTER`. TRAILING: type `@[price] T` and `CTRL+ENTER`.
- **B) Trim [N] shares** — shares to sell so risk at the current stop falls within the R limit.

---

## Controls

| Key | Action |
|---|---|
| `ENTER` | Model hypothetically — updates the grid without saving |
| `CTRL+ENTER` | Commit permanently to the database |
| `S` | Save all pending drafts at once |
