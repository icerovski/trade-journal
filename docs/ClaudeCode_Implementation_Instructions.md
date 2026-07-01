# Implementation Instructions for Claude Code

> **How to use (for you, the human — not part of the prompt):** create the test branch
> first (see the Git guide), make sure `Entry_and_Stop_System.md` and
> `Horizon_Calibration_3to6mo.md` are in the repo, then paste everything below the line into
> Claude Code at the repo root. You can paste it whole (it will work phase-by-phase on its
> own) or paste one phase at a time for even tighter control.

---

You are extending an existing, **working** trading application. Two design documents in this
repo — `Entry_and_Stop_System.md` and `Horizon_Calibration_3to6mo.md` — describe the
additions I want. **Your #1 priority is to not break any behavior that currently works.**
Read both documents fully before doing anything else.

## Absolute rules (do not violate)

1. **Explore before you edit.** Change no code until you have mapped the codebase and I have
   approved a plan.
2. **Additive and opt-in.** Every new feature sits behind a config flag or profile whose
   default reproduces today's exact behavior. With defaults unchanged, the app must behave
   identically to how it does right now.
3. **Prefer new modules.** Add new files/functions rather than rewriting existing ones. Touch
   existing files only to wire in new code behind a default-off flag. Never delete or rewrite
   a working function; if one must change, keep the original path reachable.
4. **Characterization tests first.** Before any functional change, capture the current
   behavior of the core paths as golden-master snapshot tests over several representative
   inputs — especially the scanner (e.g. `zone_scan.scan_ticker`), the sizing / Risk
   Workspace, the regime/stop-source logic, and the exit ladder. These snapshots must stay
   identical through every later phase. If a change alters a snapshot, **STOP and flag it**.
5. **One phase at a time.** Implement a single phase, run the full test suite + snapshots,
   then **STOP and summarize for my review**. Do not begin the next phase until I reply
   "continue".
6. **Small commits.** After each green phase, propose a commit message and wait; I will
   commit. Never leave tests failing.
7. **No new network calls, external services, or secrets** without asking first.
8. **When the documents and the code conflict on trade logic, ask — do not guess.**

## Distinguish automatable from judgment

Some items in the docs are **human judgment**, not code: source qualification, location and
trigger selection, and conviction-based risk sizing. Do **not** try to automate these —
surface them as checklist prompts in the pre-trade flow. Everything else (config, gates,
logging, expectancy math, sizing, exit shapes, the calibration profile) is automatable.

---

## Phase 0 — Map & safety net (NO functional changes)

- Produce a concise map of: entry points / menu system, the scanner, the volatility/ATR
  calculation, regime detection, stop-source logic, sizing / Risk Workspace, the exit ladder,
  logging/persistence, and where configuration lives.
- List every "magic number" currently hardcoded (e.g. the momentum threshold, the micro
  window length, the stop buffer, the ATR period/lookback).
- Write characterization/snapshot tests capturing current outputs for a handful of
  tickers/caches. If there is no test setup yet, create a minimal one.
- Output the map + a proposed file-level plan for Phases 1–8. **STOP for my approval.**

## Phase 1 — Config extraction (behavior unchanged)

Move the magic numbers into one config location, using their **current** values as defaults;
replace the hardcoded literals with references. Goal: **zero** behavior change — this just
makes later tuning safe.
**Acceptance:** all tests green; snapshots identical to Phase 0.

## Phase 2 — Logging schema expansion (additive)

Extend the trade log to hold the fields in *System §7*: source (and "would I have taken it
independently?"), theme, THESIS/TECHNICAL tag, regime, archetype, stop_source, flagged,
confluence count, entry, stop, R₁, R%, ATR period/value, event-adjacent, realized R, realized
**base-currency** return, result-vs-benchmark, and MAE/MFE. Add a way to log **skipped**
source picks (date, price) as well. New fields default to empty; **old log rows without the
new fields must still load and save**.
**Acceptance:** old logs load; new fields persist; no change to trade logic.

## Phase 3 — THESIS/TECHNICAL classification (*System §0a*)

Add a per-trade classification field (default: unset). Store it, surface it in the pre-trade
flow, and write it to the log. Do **not** branch any exit logic on it yet — just carry it.
**Acceptance:** tag sets/reads/persists; untagged trades behave exactly as before.

## Phase 4 — Gates G1–G8, advisory first (*System §4*)

Implement the gates as a **separate validation module** that takes a proposed trade and
returns, per gate, pass/fail/NA plus a reason. Read thresholds from the Phase-1 config.
Include **G7 theme heat** and **G8 base-currency risk**. Wire it into the pre-trade flow
behind a flag `gates_mode = off | advisory | blocking`, default **off**:
- `off` → no change;
- `advisory` → prints warnings, blocks nothing;
- `blocking` → a failed hard gate prevents commit.
**Acceptance:** with `off`, behavior unchanged; each gate has unit tests for pass/fail.

## Phase 5 — Expectancy analytics, read-only (*System §5, §7*)

Add a read-only report computing, per archetype, w / average win / average loss / E[R] from
the log, plus source-vs-benchmark and base-currency stats. No effect on the trade flow.
**Acceptance:** report runs off the log; empty/short logs handled gracefully.

## Phase 6 — Sizing: gap-aware option (*System §6*)

Keep the existing fixed-fractional sizing (`qty = risk_budget / R₁`) as the default. Add an
**optional** gap-aware path that sizes off `R_gap = entry − plausible_gap_price` for
event-adjacent trades, behind a default-off flag.
**Acceptance:** default sizing unchanged; gap path covered by tests.

## Phase 7 — Exit shape: scale-out + runner (*System §5a*)

**Extend** the exit ladder, do not replace it. Support the three exit shapes:
1. hard target (TECHNICAL trades),
2. scale-out + trailing runner,
3. thesis-exit (no price target).
Selection is per-trade and defaults to the **current** exit behavior. Enforce **no time
stop** — add no time-based forced exit. Keep the earnings/event gate untouched and separate
(it governs entry timing and gap sizing, not exits).
**Acceptance:** current exit behavior reproducible as the default; new shapes selectable and
tested.

## Phase 8 — Horizon calibration profile (*Horizon_Calibration_3to6mo.md*)

Add a **selectable config profile** implementing the calibration doc: weekly structure, long
(12–24-month) ATR, percent-of-price buffers (~3–7%) and stop-width band (~10–18%), the
30-week MA anchor, and the MOMENTUM-regime override (treat a momentum flag as "wait for a
weekly pullback / use a weekly-structure stop", not a tight micro-stop). Ship it as a
**non-default** profile (e.g. `position_3to6mo`); the default profile keeps today's
short-swing calibration. Respect the doc's "two roles of time": the profile changes the
**lens** (timeframe/smoothing) only and adds **no time stop**.
**Acceptance:** default profile → snapshots identical to Phase 0; selecting `position_3to6mo`
changes parameters as specified; both covered by tests.

---

## After all phases

- Summarize every new config flag/profile and how to toggle each.
- Confirm that, with all defaults, the app is behaviorally identical to the starting commit
  (snapshots green).
- List the human-judgment items you surfaced as checklist prompts rather than automating.

**Begin with Phase 0 only. Do not edit any code yet — map the codebase, write the safety-net
tests, propose the plan, and stop for my review.**
