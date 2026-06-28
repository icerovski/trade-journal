# Indicator & Metric Glossary

The **single source of truth** for every indicator, metric, and threshold the system
uses. If a definition appears anywhere else (a panel, another guide, the F1 help),
this file is canonical. Numbers in **bold** are live constants from `constants.py`
(or the noted source file) — the appendix at the end lists them all in one table.

For *how to choose a stop* from these, see the **Stop Placement Playbook**. For the
zone scanner specifically, see the **Zone Scanner Guide**.

---

## 1. ATR — Average True Range

**What it is.** The average size of a bar's full range (including overnight gaps) —
the instrument's volatility yardstick, in price units. Everything risk-related is
measured in ATRs ("R-multiples") so a $5 move on a $50 stock and a $50 move on a
$500 stock are treated the same.

**How it's computed.** Wilder ATR via an exponentially-weighted mean of True Range,
`ewm(com=window-1, adjust=False)` — the same method everywhere (`stop_loss.py`,
`zone_scan._wilder_atr`) so the scanner and the risk engine never disagree.

True Range of a bar = max of: (high − low), |high − prev close|, |low − prev close|.

**The institutional timeframes** (ATR Discovery, `stop_loss.py:258-261`):

| Label | Timeframe | Window |
|---|---|---|
| `14d` | Daily | 14 |
| `12w` | Weekly | 12 |
| `12m` | Monthly | 12 |
| `12q` | Quarterly | 12 |

All four come from a **single** `period="max"` daily pull resampled up — no extra
HTTP call per timeframe.

**Inception ATR vs trailing ATR** — the distinction that governs the whole exit ladder:

- **Inception ATR** — the ATR frozen at your first entry. It defines the *reward*
  ladder (M1/M2/TP) and never changes. It is the "original risk you took".
- **Trailing ATR** — the live, current ATR. For a TRAILING stop it sets only *where
  the stop sits today*. It never moves the reward ladder (otherwise an expanding-vol
  winner would have its targets drift away and look perpetually mediocre).

**Volatility buffer (fixed-dollar).** A stop percentage is converted to a fixed dollar
`atr_value` at entry and held. As price rises the *percentage* tightens — intentional.
Never recompute the buffer from a percentage at the current price.

---

## 2. Volume Profile — POC / VAH / VAL

A **composite volume profile** approximated from **daily** bars (Yahoo exposes no
intraday volume-at-price). Each day's volume is smeared across its high–low range with
a triangular weight peaking at the close, into fixed price buckets
(`volume_profile.compute_volume_profile`). It is an *estimate* of where volume traded —
**never** represent it as tick-derived.

- **POC — Point of Control.** The single price bucket with the most traded volume. The
  "fair price" / center of gravity of the range.
- **Value Area.** The contiguous band around the POC holding **70%** (`VP_VALUE_AREA_PCT`)
  of total volume — where most business got done.
- **VAH — Value Area High.** Top edge of that band (resistance).
- **VAL — Value Area Low.** Bottom edge of that band (support). The scanner's primary
  structural stop anchor for a long.
- **Bucket width.** Each bucket spans **0.5%** (`VP_BUCKET_PCT`) of price.
- **Lookbacks.** Profiles are built over **6 and 12 months** (`VP_LOOKBACKS_MONTHS`),
  giving `VAL_6mo`, `VAH_6mo`, `POC_6mo`, `VAL_12mo`, etc.

**HVN — High-Volume Node.** A local *peak* in the profile — a price shelf where volume
stacked up heavier than its surroundings. More precise than the VAL edge. A node counts
only if its prominence clears **0.5** (`HVN_MIN_PROMINENCE`). Below price, the nearest
HVN is a tight support; a break through it means price fell through where recent volume
accumulated.

**Naked POC.** A high-volume shelf from a prior profile that price has **not revisited
since** (`find_naked_pocs`). Markets tend to revisit naked POCs, so the nearest one
*above* price is used as the scanner's **target**.

---

## 3. Anchored VWAP (AVWAP)

Volume-Weighted Average Price computed *from a chosen anchor bar forward* — the average
price every share has paid since that event. It bends with price (unlike a horizontal
level), tracking the average cost of a specific move.

- **Pivots / swing points.** Detected by symmetric fractal logic with a
  **10-bar** (`PIVOT_WINDOW`) window each side (`anchored_vwap.find_pivots`).
- **`AVWAP_low`** — anchored at the most recent **swing low**. Support: a break below
  means the average buyer *off that low* is now underwater.
- **`AVWAP_high`** — anchored at the most recent **swing high**. Reference / resistance.

---

## 4. Moving Averages

- **DMA50 / DMA200** — simple 50- and 200-day moving averages of close. Structural
  reference levels and, for the 200-DMA, the basis of the **trend regime** (§8).

---

## 5. Risk primitives

- **Stop types.**
  - **FIXED** — you enter an absolute stop *price*. The system never moves it (the
    ratchet prevents accidental *lowering*).
  - **TRAILING** — you enter a *distance* (in $, %, or via an `@price` target). The stop
    follows the high-water mark down by that distance and never retreats.
- **R (risk per share)** = `entry − stop` (the price you lose per share if stopped out).
- **R (% NAV)** = `(entry − stop) × qty / NAV`, normalized to NAV currency via live FX.
  Your total downside if the stop fills, as a fraction of the book. Can be **negative**
  when the stop sits above entry (a stop-out is profitable).
- **HCM — Higher of Cost or Market.** `max(cost, market value)`. Used for exposure so
  the book never *understates* how much capital a position commits.
- **Dual-Constraint Audit.** Every open position is checked against two independent caps,
  and the **tighter one binds**:
  - Risk limit: `(entry − stop) × qty / NAV ≤ max_r_pct`
  - Exposure limit: `HCM / NAV ≤ max_exp_pct`

---

## 6. RR — Reward:Risk ratio

**Formula.** `RR = (TP − Price) / (Price − Stop)` — units of upside to the target for
each unit of downside to the stop (`stop_loss.py:185`; PLAN forward-RR `risk_workspace.py:820`).

**Status: informational only — NOT an exit trigger.** A deep stop drags RR low on
geometry alone. Exits come from the **stop** and a **RANGING regime**, never from RR.
(The former sub-1.0 "efficiency floor" that forced a FIXED-stop exit was **removed** —
commit `5b2f9ff`.)

**Color bands** (Risk Workspace PLAN strip, `risk_workspace.py:1001`):

| Band | RR |
|---|---|
| 🟢 green | ≥ 2.0 |
| 🟡 yellow | ≥ 1.0 |
| 🔴 red | < 1.0 |

**`RR_SETUP_FLOOR` = 3.0** is a *separate* idea: the 3:1 forward reward used (a) as the
scanner's default target multiple and (b) the floor a `TP:n` override's forward RR is
flagged against on the PLAN TARGET line. It does **not** force an exit.

---

## 7. Confluence

How the scanner decides a price is "on structure". `evaluate_confluence` measures the
ATR-distance from price (and from the stop) to every structural level, and counts how
many cluster nearby.

- **ATR distance.** Distance to a level expressed in daily-ATR units (R). The operative
  measure — percent is secondary.
- **Zone threshold = 0.25R** (`CONFLUENCE_ATR_THRESHOLD`). A level within 0.25 ATR of
  price is a *meaningful* convergence.
- **Fortress threshold = 0.1R** (`CONFLUENCE_FORTRESS_THRESHOLD`). A level within 0.1 ATR
  is exceptionally tight — flagged with a **★**.
- **Flag a zone:** **≥ 2** converging entry signals (`ZONE_MIN_CONFLUENCE`).
- **`ZONE_CONFLUENCE_PCT` = 2.5%** — the percent band, converted to ATR units, that the
  engine uses as its working threshold per ticker.

---

## 8. The two regimes (they are different things)

### Scanner regime — decides *where the stop comes from*
- **NORMAL (`ZONE`)** — price is near longer-term support; the stop is the nearest true
  structural support (6mo/12mo VAL or `AVWAP_low`).
- **MOMENTUM (`ZONE-MOMO`)** — price has run **more than 10%** (`MOMENTUM_VAL_PREMIUM_PCT`)
  above its 6-month VAL. That support is now too far below to be a usable stop, so the
  scanner switches to a tight **micro-structure** stop from the last 14 bars (§9).
  `ZONE-MOMO` is a *statement about stop placement*, not a stronger/weaker signal.

### Trend regime — decides *how aggressively you take profit* (`profit_taking.classify_regime`)
Based on the 200-DMA's consecutive same-direction days and price's position vs it:

| Regime | Condition | Meaning |
|---|---|---|
| 🟢 **TREND** | DMA rising **≥ 21d** AND price **above** the 200-DMA | structural support confirmed |
| ⚪ **NORMAL** | DMA rising **10–20d**; or ≥21d but price below DMA (pullback); or an unconfirmed reversal | developing / pulling back |
| 🔴 **RANGING** | DMA declining (confirmed), or rising < 10d | no support |

**Reversal hysteresis.** The day-count resets to ~1 on any reversal, so one counter-trend
day would otherwise crash a long TREND straight to RANGING. A reversal shorter than
**3 days** (`REGIME_REVERSAL_CONFIRM_DAYS`) is treated as *unconfirmed* and the regime is
held one notch up at NORMAL.

---

## 9. Momentum micro-anchors (the v2 stop tier)

In MOMENTUM regime the stop is the **tightest qualifying level below price** from the last
**14 bars** (`MICRO_LOOKBACK_DAYS`), placed **0.25 ATR** (`MICRO_STOP_BUFFER_ATR`) beneath
it. Four anchor types compete; the nearest-below-price wins, and `stop_source` names it:

| Label | Anchor | A break of it means |
|---|---|---|
| `VAL_14d` | micro value-area low | price left the recent volume shelf |
| `HVN_14d` | nearest high-volume node below price | price fell through where recent volume stacked |
| `AVWAP_14d` | VWAP anchored to the swing low *inside* the window | the average buyer of this leg is underwater |
| `GAP_14d` | floor (pre-gap high) of the most recent breakout gap, gap **≥ 0.5 ATR** (`GAP_MIN_ATR`) | the breakout gap has filled — the move that started the leg is undone |

If no micro support exists below price, the scanner falls back to base support, then to a
plain **1-ATR stop** (`ATR(1)`) — a weak basis worth noting (see the Playbook, Scenario C).

---

## 10. Exit ladder & milestones

A uniform R-multiple ladder anchored to **entry**, using the **inception ATR** as R
(`profit_taking.compute_exit_milestones`):

| Stage | Trigger | Action |
|---|---|---|
| PRE-M1 | price < entry + 1R | Hold — the stop is the only exit |
| **M1** | price ≥ entry + 1R | Move stop to entry (position becomes risk-free) |
| **M2** | price ≥ entry + 2R | Trim by trend regime (TREND = hold) |
| **TP** | price ≥ entry + 3R | Larger trim by trend regime |

- **TP override (`TP:n`).** The top rung is overridable per position via
  `risk_profiles.tp_atr_mult` (a multiple of the *frozen inception* ATR; `NULL` =
  default **3R**, `TP_ATR_MULTIPLE`). M1/M2 always stay at 1R/2R.
- **Trim matrix** `(stage, regime) → fraction` (`profit_taking.TRIM_MATRIX`): M2 → TREND
  hold / NORMAL 33% / RANGING 50%; TP → TREND 20% / NORMAL 33% / RANGING close all.

---

## 11. Capital efficiency (dead money)

Orthogonal to the exit ladder — asks whether capital is earning its keep.

- **AAGR** — price-only annualised unrealised return. Tagged "prelim" and dimmed under
  180 days (too short to annualise meaningfully).
- **STALE** — flagged when a holding is **≥ 180 days** old (`STALE_MIN_AGE_DAYS`) AND its
  AAGR is below the **8%** hurdle (`CAPITAL_HURDLE_PCT`). A prompt to review or redeploy,
  **not** an automatic exit. Income assets (bonds/bills) are exempt — price-only AAGR
  would understate their coupon.

---

## 12. Position-sizing presets

Each preset sets a Risk% and Exposure% cap together. Source of truth is the DB preset
matrix (`get_presets`, seeded in `db.py:139-141`):

| Preset | Risk (R) | Exposure (E) | Crossover stop (R ÷ E) | Use case |
|---|---|---|---|---|
| **S** Small | 0.30% | 1.5% | 20% | speculative / high-vol |
| **B** Base | 0.60% | 3.0% | 20% | standard single-name |
| **L** Large/Index | 1.00% | 5.0% | 20% | large cap / broad index |

**Crossover stop** = R ÷ E: the ATR distance at which both limits bind at once. A *tighter*
stop → Risk binds; a *wider* stop → Exposure binds.

---

## 13. Table icons & action triggers (Risk Workspace / Dashboard)

| Marker | Meaning |
|---|---|
| `[T/F/-]` | Stop type: Trailing / Fixed / None |
| `★` (yellow) | Unsaved draft in the Sandbox |
| ` Price ` on red | **EMERGENCY** — stop breached, exit |
| `★` (cyan) | **Take-profit hit** — price reached the TP target |
| `⚠` (red) | **Limit exceeded** — Risk or Exposure above your Max |
| ` STALE ` (red) | **Dead money** — held ≥ 180d, AAGR below the 8% hurdle |
| ` MODELING ` | a what-if scenario in the PLAN section (nothing saved) |

**Risk (% NAV) bands:** 🟢 < Max R | 🟡 Max R – 1.5×Max R | 🔴 > 1.5×Max R
(`RISK_RED_MULTIPLIER` = 1.5). **Exposure bands:** red above 1.1×Max
(`EXPOSURE_RED_MULTIPLIER`).

---

## Appendix — constants (`constants.py`)

| Constant | Value | Used for |
|---|---|---|
| `CONFLUENCE_ATR_THRESHOLD` | 0.25 | zone proximity (R) |
| `CONFLUENCE_FORTRESS_THRESHOLD` | 0.1 | fortress proximity (R) |
| `ZONE_MIN_CONFLUENCE` | 2 | signals needed to flag a zone |
| `ZONE_CONFLUENCE_PCT` | 0.025 | percent confluence band |
| `MOMENTUM_VAL_PREMIUM_PCT` | 0.1 | MOMENTUM trigger (above 6mo VAL) |
| `MICRO_LOOKBACK_DAYS` | 14 | momentum micro-stop window |
| `MICRO_STOP_BUFFER_ATR` | 0.25 | buffer below the micro anchor |
| `GAP_MIN_ATR` | 0.5 | min breakout-gap size |
| `HVN_MIN_PROMINENCE` | 0.5 | min high-volume-node prominence |
| `PIVOT_WINDOW` | 10 | swing-pivot fractal window |
| `VP_LOOKBACKS_MONTHS` | (6, 12) | volume-profile lookbacks |
| `VP_VALUE_AREA_PCT` | 0.7 | value-area volume share |
| `VP_BUCKET_PCT` | 0.005 | profile bucket width |
| `RR_SETUP_FLOOR` | 3.0 | default target / 3:1 flag |
| `TP_ATR_MULTIPLE` | 3 | default TP rung (R) |
| `REGIME_REVERSAL_CONFIRM_DAYS` | 3 | trend reversal hysteresis |
| `STALE_MIN_AGE_DAYS` | 180 | dead-money age gate |
| `CAPITAL_HURDLE_PCT` | 8.0 | dead-money AAGR hurdle |
| `RISK_RED_MULTIPLIER` | 1.5 | risk RED band |
| `EXPOSURE_RED_MULTIPLIER` | 1.1 | exposure RED band |
| `QTY_ZERO_THRESHOLD` | 0.0001 | reset-on-zero tolerance |
