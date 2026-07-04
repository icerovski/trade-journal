# Application Assessment — Entry & Stop System / Horizon Calibration

**Date:** 2026-07-04
**Auditor:** Claude (Fable 5), per `Fable_Application_Assessment_Brief.md`
**Scope:** Read-only audit. Full read of the brief, all 32 files in `/docs` (with `Entry_and_Stop_System.md` and `Horizon_Calibration_3to6mo.md` treated as canonical), and the implementation (`core/gates.py`, `core/sizing.py`, `core/stop_loss.py`, `core/profit_taking.py`, `core/zone_scan.py`, `core/calibration.py`, `core/exit_shapes.py`, `core/expectancy.py`, `core/trade_log.py`, `db.py`, `ui/risk_workspace.py`, `ui/zone_scan_workspace.py`, `main.py`, tests). Full test suite run: **265 passed**. Numeric verification done by hand against the golden snapshot and live-workflow arithmetic (details in Tier 1). No code was changed.

---

## 1. Executive summary

The financial core is sound: the exit ladder, dual-constraint sizing arithmetic, ratchet rule, gap-aware sizing, and regime table all hand-verify exactly, the no-time-stop guarantee genuinely holds (code + dedicated tests), and the additive/default-off discipline was followed rigorously (2,831 insertions vs 44 deletions; golden master intact). **The single biggest risk is that every position-sizing path is FX-blind**: EUR NAV is divided by USD risk-per-share with no conversion, so every suggested share count is wrong by the EUR/USD rate (~7–8% under-sized today; it silently flips to *over*-sized — a breached 1% cap — if EUR/USD drops below parity, which happened in 2022). The audit path (`audit_position_risk`) *is* FX-correct, so the app currently disagrees with itself by the FX rate between "size to take" and "risk you hold." Beyond that, the honest headline is a gap between spec and delivery: the gates evaluate on almost no real inputs (G2–G7 permanently NA, G8 can never fail), the 3–6mo calibration profile — built for exactly this user's horizon — is both mostly inert (its %-bands are unwired metadata) and unreachable (no UI can select it), and the expectancy report reads a journal the app cannot yet meaningfully populate. None of this produces wrong numbers, because it's all default-off — but roughly half the new surface area is scaffolding, not function, and should either be finished or trimmed.

---

## 2. Findings by tier (most severe first within each tier)

### Tier 1 — Financial correctness

**T1-1 (severe): Sizing paths ignore FX; the 1% NAV risk cap is enforced only in asset currency.**
`compute_position_size` (`core/sizing.py:4`) has no FX parameter. Callers pass EUR NAV against USD prices with no conversion: the zone scanner presets (`core/zone_scan.py:295`), ATR-discovery QTY (`core/stop_loss.py:298`), and the workspace's inline prospect sizing and modeled R% (`ui/risk_workspace.py:1385-1394`) — including the gap-aware path. Meanwhile the committed audit (`audit_position_risk`, `core/stop_loss.py:32`) correctly applies `fx_rate`. Hand-check with the documented live NAV (€2,688,800) on a $190 stock, L preset: scanner gives exposure-bound qty = 2,688,800×5%/190 = **707 sh**; converting NAV at EUR/USD 1.08 gives **764 sh** — a 7.4% under-size. Under-sizing is the safe direction *today*, but the cap is not actually enforced in base currency anywhere a size is proposed, and the error sign is set by the FX market, not by the code.

**T1-2: Numeric verification — everything else checks out.** Hand-recomputed against `tests/snapshots/phase0_golden.json` and code:
- *Sizing (all 6 golden cases):* NAV 1M, entry 100, stop 90, R 1%/E 5% → risk arm 10,000/10 = 1,000, exposure arm 50,000/100 = 500 → **500 ✓** (tighter wins); stop 50 → **200 ✓** (risk-bound); bond ×0.001 → **50,000 ✓**; option ×100 → **5 ✓**; the other two ✓.
- *Exit ladder:* FIXED entry 100/stop 90/inception ATR 10/price 110 → M1 110, M2 120, TP 130, stage M1, RR (130−110)/(110−90) = 1.0, risk_val −1,000 — all ✓. TRAILING HWM 115/dist 10 → stop 105, TP still 130 (entry-anchored, confirming the uniform-ladder fix), RR 4.0, risk_val +500 ✓. TP:5R override → TP 150, M1/M2 unchanged at 110/120 ✓ (override lifts only the top rung, per spec). UDOW migration numbers in the session log are internally consistent (66.50 + n×12.26 reproduces M1/M2/TP exactly).
- *Gap sizing:* $5,000 budget / R_gap 30 = 166 sh ✓; gap at 2×R₁ exactly halves qty ✓; `min(stop, gap)` = "larger of R₁ and R_gap" per spec §6 ✓; exposure clamp preserved ✓.
- *Regime truth table:* all 32 golden cells match the documented table, including hysteresis (DOWN 2d → NORMAL, DOWN 3d → RANGING) ✓.

**T1-3: No time-based forced exit — confirmed, thoroughly.** Grepped the codebase for any time/hold/age-triggered exit: none exists. `is_stale` is a display nudge only (never enters `_exit_recommendation`; suppressed on breach). Two dedicated tests enforce it (`test_no_time_stop_ancient_position_not_forced_out`, `test_profile_has_no_time_stop_field`). The calibration profile carries no time field. This design decision holds in the implementation.

**T1-4: The gates are spec-shaped but mostly starved of inputs; G8 is a placeholder in practice.**
`core/gates.py` faithfully encodes G1–G8 with the spec's defaults, and NA-never-blocks is well designed. But `_gate_check` (`ui/risk_workspace.py:1490-1502`) feeds only entry/stop/ATR/qty/NAV/multiplier/ccy/fx. Consequences in the live flow:
- **G2, G3, G4 (earnings), G5, G6, G7 always return NA** — `stop_source`, `flagged`, `confluence_count`, `days_to_event`, `trail_anchor`, `adv`, `theme_heat_pct` are constructed nowhere outside tests. There is no earnings-calendar data source anywhere in the app. (The docstring at `risk_workspace.py:1482` claims "Only G1/G5/G8 have inputs" — G5 in fact has none; even the docstring overstates.)
- **G8 answers the brief's question: it is a real formula behind a placeholder check.** The base-currency exposure math exists (`gates.py:235`), but it only runs if `fx_exposure_cap_pct` is supplied — and no caller ever supplies it. For a USD asset on the EUR book, G8 returns PASS with an advisory note, always. It also measures only the single trade's exposure, never the book's aggregate USD exposure (which `compute_portfolio_risk` already computes per currency — the data exists, unwired).
- **G1's ATR arm is nearly self-fulfilling.** It receives the draft's `inception_atr`, which for FIXED stops is *snapped to the discovery ATR nearest the stop distance* and for fresh TRAILING stops *is* the trail distance — so `R₁/ATR ≈ 1.0` by construction and only the 8%-of-entry arm does real work. The spec (§8) says to fix one named ATR (e.g. ATR14-daily) and use it everywhere; the daily ATR is sitting in the discovery cache, unused here.
So with `gates_mode=blocking`, the "eight hard gates" reduce in practice to one arm of one gate.

**T1-5: The 3–6mo calibration profile implements a fraction of the canonical calibration doc, and contradicts it in one combination.**
What's actually wired (`core/calibration.py`, `core/zone_scan.py:219-227`): a 60-day ATR window, a 5% confluence band, and the MOMENTUM override (micro-stop disabled → falls back to value anchors). That override is genuinely valuable and spec-correct. But:
- The **long ATR is a 60-day daily-bar window** (`CAL_3TO6MO_ATR_WINDOW`), ≈3 months — not the spec's 12–24-*month* ATR (§1a) and not weekly-scale. A longer daily window changes smoothness, not magnitude, so every "×ATR" quantity under the lens stays daily-sized. Known and flagged in the session log; the consequence isn't.
- The **%-of-price bands (3–7% buffer, 10–18% width), the 30-week-MA anchor, and the extension override are inert dataclass metadata** — nothing in `scan_ticker`, the gates, or any UI reads them. The spec's central §1a instruction ("reason in percent of price, not ATR-multiples") is encoded as constants and enforced nowhere.
- **No buffer under the anchor**: with the micro path disabled, the 3–6mo stop is the raw VAL/AVWAP level itself; spec §3 requires 0.25–0.5 weekly-ATR beneath it.
- **§1a staleness check absent**: nothing compares recent realized vol to the profile ATR. (The workspace's inception-vs-live "vol delta" line is related but a different comparison.)
- **Conflict — gates × profile**: calibration doc §4 overrides G1 to ~18% width; `gates.py` reads the fixed 8% cap regardless of profile. A correctly built 12–15%-wide 3–6mo stop **fails G1** if this user runs their intended configuration (gates on + position lens). *Deferred to the canonical calibration doc: the code is in drift.* Relatedly, TECHNICAL_DOCS §11's description ("wider buffers (~3–7%)… 30-week-MA anchor") reads as delivered behavior; the canonical spec + code say otherwise — I defer to spec+code and flag §11 as overstating.

**T1-6: Exit shapes and classification match spec, with one footgun.** HARD → full exit at TP only (`risk_workspace.py:190`), THESIS → `tp_price` dropped upstream (`stop_loss.py:167`), default/RUNNER = today's ladder verbatim — all per §5a, tested. But `C:TH` (classification) and `X:T` (thesis shape) are fully independent toggles: tagging a trade THESIS does *not* remove its price target. The spec treats "THESIS ⇒ no guessed price target" as one idea (§0a table + §5a); in the app it's two commands, and forgetting the second silently gives a thesis trade a 3R hard ladder — the exact "wrong clock" §0a warns about.

**T1-7 (minor): NORMAL-regime scanner stop has no buffer.** The golden `normal_zone` case places the stop *at* `AVWAP_low`, 0.35% below price. Playbook §6 says "always add a small buffer (~0.25 ATR)"; the MOMO path does, the NORMAL path doesn't. Internal doc/code inconsistency — deferred to the Playbook's own §6 as the intent.

### Tier 2 — Data integrity & edge cases

**T2-1: Thin history silently degrades in two places.**
- `scan_ticker` returns `None` below `atr_window+1` bars (15 default, **61** under the 3–6mo lens) and `build_zone_report` drops it — the ticker just vanishes from the scan table with no "insufficient data" row. Switching to the position lens can make a recent listing disappear with no explanation.
- `_compute_atr_rows` (`stop_loss.py:281`) shrinks the window to `len(df)−1` but keeps the label: a listing with three quarterly bars shows a "12q" ATR computed from 2 samples. Because the FIXED-stop commit snaps `inception_atr` to the nearest of these rows, a garbage 2-bar "quarterly ATR" can be frozen as the position's permanent R unit, mis-scaling its ladder for life. No warning fires.

**T2-2: Earnings-proximity gate is inert; gap sizing is correct but wholly manual.** (The brief calls the earnings gate "G3"; in the spec/code it is **G4** — audited as the event gate.) There is no earnings-date source anywhere, so G4 is permanently NA; event protection rests entirely on the user typing `G:<price>` with a self-estimated gap. The gap math itself is correct and well-tested (Tier 1). Note also gap sizing only affects *prospect* sizing (`calc_q == 0` path) — for an already-held position heading into earnings, `G:` shows a chip but changes nothing.

**T2-3: Log schema backward compatibility — clean.** `trade_log` is built and additively migrated from a single `COLUMN_TYPES` source; `from_row` drops unknown legacy columns and coerces bools. The exact brief scenario (old table missing new columns → loads, saves, backfills) has a real test (`test_old_row_without_new_columns_still_loads_and_saves`) and passes.

**T2-4: Duplicate journal rows on re-commit.** Every commit of a classified position writes a fresh `trade_log` row (`_log_classification`, no de-dup) — routine stop maintenance on one trade will produce N journal rows and later double-count in expectancy stats. Acknowledged as future work in the session log; it's a data-quality time bomb for the exact analytics the journal exists to feed.

**T2-5: Confluence double-counting.** `evaluate_confluence` counts every label independently: in the golden case `VAL_6mo` and `POC_6mo` share the identical price (98.2497) and count as two "converging signals," so `ZONE_MIN_CONFLUENCE=2` can be satisfied by one physical level under two names — the precise "one signal counted three times" trap spec §4a exists to prevent, and it would inflate any future G2 wiring.

**T2-6 (minor):** `enrich_regime` failure (unresolvable ticker, bad data) silently leaves `trend_regime="NORMAL"` — an M2 winner with missing regime data gets "trim 33%" rather than a "regime unknown" flag.

### Tier 3 — Workflow friction

**T3-1: The end-to-end trade walkthrough is proportionate — with one broken seam.** A full new-idea decision: ① menu 1 sync → ② menu 6, `a`, symbol (auto-fetch ~10y, default profile) → ③ menu 8 scan, read TAG/`stop_source`/sizes → ④ menu 2, select row, one command line (`291.60 F P:B C:TE X:H TP:4R`), ENTER to model, CTRL+ENTER to commit → ⑤ place the order at IBKR manually. Four app surfaces plus the broker, each Textual app exited before the next opens. For a few trades a month this is acceptable — the single-command-line design is genuinely dense and good. The broken seam: **nothing carries from step ③ to step ④.** The scanner's stop, source label, flagged status, and confluence count must be memorized/retyped — which is also exactly the data that would make gates G2/G3 evaluate. One handoff would fix both a friction problem and a correctness gap.

**T3-2: Global modes fail the "weeks away" test.** `gates_mode` is visible only inside the M modal (a free-text field). `calibration_profile` is worse: **no UI reads or writes it anywhere** — it can only be changed by hand-editing the SQLite `settings` table, and neither the zone scanner header nor any panel shows which lens produced the scan you're looking at. TECHNICAL_DOCS §11 documents the profile as a selectable feature; for the app-as-shipped it is not selectable. The reorientation story is otherwise strong (F1 renders the guides directly; the verdict-led PLAN panel is excellent), but the two mode switches that change *what the numbers mean* are invisible.

**T3-3: The command mini-language has grown to ~11 token families** (VALUE, F/T, @, %, P:, R:, E:, TP:/TP:N:1, +N/−N/BE, C:, X:, G:). Manageable with F1 — except `Strategy_Lab_Syntax.md`, the canonical F1 command reference, **documents none of the three new tokens** (`C:`/`X:`/`G:` live only in TECHNICAL_DOCS §10). *Conflict resolved by deferring to TECHNICAL_DOCS §10 + code; the guide is behind.*

**T3-4: Doc conflicts found (flagged, not resolved), with deference noted:**

| Conflict | Deferred to |
|---|---|
| `GEMINI.md`: "RR < 1.0 → Exit", Scale-In `S0` flag, Quarterly ATR window 8 | Code + TECHNICAL_DOCS §5 + Glossary (all: RR informational, Scale-In removed, window 12). GEMINI.md is badly stale. |
| TECHNICAL_DOCS §6: precedence lists "urgent RR-floor exit"; text says `_exit_recommendation` "encodes … the FIXED-only RR efficiency floor" | TECHNICAL_DOCS §5 + code (floor removed in `5b2f9ff`); §6 wasn't updated. Mirrored by the stale comment at `risk_workspace.py:881` and dead `urgent` branches (`:695`, `:907`). |
| TECHNICAL_DOCS §11: 3–6mo profile "wider buffers… 30-week-MA anchor" | Canonical calibration doc + code: those are unwired metadata (see T1-5). |
| TECHNICAL_DOCS §1: "Risk Workspace (Option 2 → 1)" | Code: menu 2 launches directly. |
| `Strategy_Lab_Syntax.md` missing `C:`/`X:`/`G:` | TECHNICAL_DOCS §10 + code. |
| Playbook §2 (Scenario A: "commit the level") vs Playbook §6 ("always add a buffer") vs code (no buffer in NORMAL) | Flagged as an internal inconsistency; §6 reads as the intent. |

### Tier 4 — Code quality

- **Additive principle: followed, verifiably.** All eight phases are new modules (`gates`, `trade_log`, `expectancy`, `exit_shapes`, `calibration`) plus flag-guarded wiring; existing core files changed by handfuls of lines; nothing rewritten, no original path removed. Commit stat: 2,831+/44−.
- **Characterization tests: exist and pass unchanged.** `test_characterization.py` + committed `phase0_golden.json`; suite green (265). Caveat: everything landed as **one commit** (`7378738`), so "snapshot byte-identical through each phase" rests on the session log's word rather than git history — the operative fact (defaults reproduce prior behavior *now*) is verified. Second caveat: the test **bootstraps** the golden file if missing — if the JSON were ever deleted, the tripwire silently re-arms around the new behavior.
- Minor: dead `urgent` machinery (above); the workspace's inline prospect sizing (`risk_workspace.py:1385-1390`) re-implements `compute_position_size_gap` by hand instead of calling it — the one place the "reuse, don't duplicate" rule slipped, and exactly where the FX fix would now need to be made twice.

### Tier 5 — Extensibility

Good. A new gate is one pure function appended to `_GATES` plus a constant — gates aren't in the golden master, so zero snapshot risk. A retuned ATR/buffer belongs in a new `CalibrationProfile` (also outside the snapshot with defaults unchanged); editing the base constants directly *would* trip the snapshot, which is the tripwire working as designed. A new archetype is a free-text journal field — trivial. The genuinely hard extension is the one that matters most: feeding real inputs (scanner context, earnings dates, theme heat) into `ProposedTrade`, which is an integration problem, not an architecture problem — the seams are all in place.

---

## 3. Recommendations

**Must-fix**
1. **FX-normalize every sizing path** (T1-1): pass `fx_rate` into `compute_position_size`/`compute_position_size_gap` (or convert NAV before the call) in the zone scanner, ATR discovery, and the workspace inline sizer — and have that inline sizer call the shared function while you're in there. This is the only finding that makes a live number wrong today.
2. **Guard the FIXED inception-ATR snap against thin history** (T2-1): never freeze an R unit from a shrunken window (require `len(df) > window`, or warn and fall back) — a bad snap permanently mis-scales that position's ladder.

**Should-fix**
3. **G1 should test against a fixed, named market ATR** (daily 14d from the discovery cache), not the snapped inception ATR — today the ×ATR arm is a tautology (T1-4).
4. **Reconcile gates with the calibration profile** (T1-5): either calibration-aware thresholds (G1 → 18%) or a hard warning when `blocking` gates meet the 3–6mo lens. As-is, the user's intended configuration rejects its own correct stops.
5. **De-duplicate `trade_log` writes** per (conid, open lot) (T2-4) — one decision, one row — before the journal accumulates history that poisons E[R].
6. **De-duplicate identical-price levels in confluence counting** (T2-5): collapse levels within ~ε before comparing to `ZONE_MIN_CONFLUENCE` — this is spec §4a's minimum viable form.
7. **Surface "insufficient data" rows in the zone scan** instead of silently dropping tickers (T2-1).
8. **Fix the stale RR-floor text**: TECHNICAL_DOCS §6, `risk_workspace.py:881` comment, and the dead `urgent` branches (T3-4/T4).

**Consider**
9. **A one-line mode banner** — `gates: off · lens: default` — in the risk-workspace and zone-scanner headers. Cheapest possible fix for the weeks-away problem (T3-2).
10. **Make `calibration_profile` selectable in the M modal** (T3-2) — it's currently a documented feature with no door.
11. **Scanner → workspace handoff**: a key on a flagged zone row that prefills the command box (and threads `stop_source`/`flagged`/confluence into `ProposedTrade`, waking G2/G3 for free) (T3-1).
12. **Couple `C:TH` to `X:T` as a default** (prompt or auto-set, overridable) — one clock per trade, per spec §0a (T1-6).
13. **Implement the §1a staleness check** cheaply: warn when the 14d ATR materially exceeds the profile's long ATR — both numbers already sit in the discovery rows (T1-5).
14. **Update `Strategy_Lab_Syntax.md`** with `C:`/`X:`/`G:` (F1 updates itself), and delete or regenerate `GEMINI.md`, which now contradicts the spec on an exit rule (T3-4).
15. **Minimal §7 capture** to make the journal live: a close-out backfill prompt (realized R) and a two-keystroke "log skipped pick" entry — without these, menu 9 stays dark forever.

**Cut**
16. **G6 (liquidity/ADV/slippage)** — for a single-user book of a few mega-cap US equities at ~€50–130k a position, ADV constraints are unreachable by orders of magnitude; no data source feeds it and none is worth building. Keep the stub returning NA if you like symmetry with the spec, but delete the constants and any ambition to wire it.
17. **The `theme` half of G7** — no surface in the app captures a theme for anything, so theme heat can never evaluate. The *portfolio*-heat half is worth keeping and is one line to wire (`compute_portfolio_risk` already returns total R%). Cut the theme dimension until themes exist somewhere.
18. **`X:R` (RUNNER) as a distinct user-facing shape** — it is behaviorally identical to the default ladder (the code says so; the chip and token are pure surface). Keep the alias parsing for compatibility, but document two shapes (HARD, THESIS) plus the default, not three.
19. **`TP:$60K` input form** — four ways to express one number is three too many for a few trades a month; `TP:nR` and `TP:N:1` carry all the real use cases seen in the session logs. (Lowest priority; it's shipped and tested.)

---

## 4. Feature verdicts (does it pull its weight?)

| Feature | Verdict |
|---|---|
| **G1 stop-width gate** | Yes once it tests a real market ATR — it's the one gate that fires on real inputs today. |
| **G2 basis-quality gate** | Not yet — permanently NA until the scanner handoff feeds it; worth keeping *because* that wiring is cheap. |
| **G3 fallback-artifact gate** | Same as G2 — the Scenario-C rule is the spec's best single insight; inert without scanner context. |
| **G4 event gate** | No, as code — with no earnings source it can never fire; as a checklist line in the user's head, yes. |
| **G5 extension gate** | Marginal — needs a trail anchor nobody supplies; the zone scanner's MOMO flag already tells the same story. |
| **G6 liquidity gate** | No — cut (see rec. 16). |
| **G7 heat gate** | Half — portfolio heat is one line from working and worth it; theme heat has no data and no prospect of any. |
| **G8 currency gate** | Not as shipped — an always-PASS note; the real base-currency risk lives in the (unfixed) sizing FX gap and the already-good menu-7 currency table. |
| **`gates_mode` off/advisory/blocking** | Yes — the right control shape, cheap, legible… once its state is visible outside the modal. |
| **THESIS/TECHNICAL `C:` tag** | Yes — cheap, carried, and the seed of the whole journal; needs the `X:T` coupling to be honest. |
| **Exit shapes `X:`** | Yes for HARD and THESIS (two real, minimal hooks); RUNNER is a label for the default and shouldn't pose as a third shape. |
| **Gap-aware sizing `G:`** | Yes — correct math, genuinely opt-in, exactly matched to a 3–6mo holder who must hold through earnings. Best power-to-complexity ratio of the whole build. |
| **`TP:n` / `TP:N:1` override** | Yes — solves a real observed problem (VOO past 3R) with a frozen anchor that survives stop edits. |
| **Trade log (`trade_log`)** | Yes as schema (clean, additive, tested) — but only ~7 of 25 columns are ever written, by one path; its value is entirely contingent on rec. 15. |
| **Expectancy report (menu 9)** | Not yet — a well-built engine reporting on an empty journal; keep the engine, but it earns nothing until the logging loop exists. |
| **Calibration profile `position_3to6mo`** | The MOMENTUM override alone justifies it for this user — but today it's a hidden setting with inert bands and a mislabeled "long" ATR; finish it (buffer, % bands, selectability) or it's a documented feature that doesn't exist. |
| **Zone scanner (menu 8)** | Yes — the structural backbone of the entry system; its sizing just needs the FX fix and its confluence count the §4a de-dup. |
| **Golden-master characterization test** | Emphatically yes — it is the reason this 8-phase build could land without moving a single legacy number, and the cheapest insurance in the repo. |
