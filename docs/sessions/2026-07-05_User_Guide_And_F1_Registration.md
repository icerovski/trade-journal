# Session Log — 2026-07-05 — User Guide & F1 Registration

## Objectives

The Entry & Stop System build is feature-complete but the operator lacked a
task-level manual: the strategy guides explain *why*, nothing explained *which
menu, which key, which command*. Goal: a task-oriented user guide covering the
full trade lifecycle (prospect → entry → add → trim → stop-out → journal →
portfolio review), registered in the in-app F1 help, with every keystroke and
command verified against the code rather than copied from older docs.

## Technical Changes

- **`docs/guides/User_Guide.md`** (new, ~490 lines) — task-oriented operating
  manual. Structure:
  - §0 mental model (app never places orders; positions replayed, never typed)
    + operating-cadence table (daily ~2 min / per-idea / weekly ~20 min /
    quarterly ~1 h).
  - §1 screen index — all nine menu options with what each writes, plus
    per-workspace key-binding tables.
  - §2 task index ("I want to…" → section).
  - §3–§5 new-entry lifecycle: watch-list add (`[6]` → `a`, or Risk Workspace
    discovery input → draft → save persists as WATCH), zone-scan read
    (ZONE/ZONE-MOMO/THIN tags, Scenario-C no-trade, `c` handoff), size &
    commit (prospect `BUY N` sizing, `G:` gap sizing, gates at save,
    journal upsert via `C:` tag).
  - §6 add-on-dip walkthrough (breach check → THESIS/TECHNICAL clock →
    structure rescan → `ADD +N sh` ceiling → `+N`/`BE` modeling → stop
    migration up only).
  - §7 profit-taking (ladder directives, ACTION column legend, exit-shape
    overrides, RR informational-only, STALE nudge).
  - §8 stop-hit protocol (BREACH/EXIT recognition, degraded live-exit P/L,
    no renegotiation, reset-on-zero → re-entry is a new decision, `b`
    backfill).
  - §9 earnings on a *held* position — gap what-if recipe: model gap price as
    hypothetical fixed stop (`330 F`), iterate pre-earnings trim (`330 F -50`),
    nothing persists without `s`.
  - §10 journal capture (`b`/`k` in menu 9), §11 3–6mo lens switch.
  - §12 portfolio heat reduction — read `[7]` (Portfolio R%, P/L if all stops
    hit, headroom, HHI, ccy) then deleverage: tighten-to-structure → ladder
    trims → Top-5-by-Risk → STALE cuts.
  - §13 raise-cash selling order: breached → STALE → profit-taking stages →
    lowest-E[R] archetypes → healthy positions pro-rata; FX-conversion and
    G4-timing checks.
  - §14–§18 data routine, reviews, command-box grammar reference (full token
    table incl. `@price T`, `+N/-N`, `BE`, all `TP:` forms), settings modal
    reference, guide map.
- **`services/ui_components.py:15-25`** — `HELP_FILES` expanded 6 → 9 tabs and
  reordered: **User Guide** (new, first tab), Glossary, Stop Playbook,
  **Entry & Stops** (new), Exit Strategy, Zone Scanner, **Horizon 3-6mo**
  (new), Strategy Lab, Technical. The Entry & Stop System and Horizon
  Calibration guides had never been registered — F1 was missing the three
  newest documents.

## Logic & Decisions

- **How-vs-why split.** The User Guide deliberately contains no strategy
  argument — it cross-references the Entry & Stop System / Playbook / Exit
  Strategy for rationale and owns only the button-level procedure. Prevents
  drift: thresholds and reasoning continue to live in exactly one guide each.
- **Code-verified, not doc-copied.** Menu numbers, key bindings, and command
  grammar were read from `main.py` and the workspace sources. Notable
  corrections vs. drifted references elsewhere: Risk Workspace is menu **[2]**
  (not 7); commits are `Enter` (draft) + `s` (Save All), not Ctrl+Enter.
- **Earnings-gap recipe uses existing machinery only.** `G:` re-sizes only
  prospects (`compute_position_size_gap` runs when qty==0,
  `risk_workspace.py:1469`), so the held-position section teaches the gap as a
  *hypothetical fixed stop* what-if in the modeling box instead of claiming a
  `G:` effect that doesn't exist for held lots. Drafts are in-memory until
  `s`, which makes the what-if safe.
- **Raise-cash ranking is a recipe over existing surfaces** (STALE flags,
  exit stages, E[R] table, Top-5 exposure) — no new metric invented, so the
  section cannot desynchronize from the code.
- **F1 ordering:** User Guide first as the front door for a returning
  operator; Strategy Lab demoted behind the strategy guides since it's a
  syntax reference. Nine tabs accepted as within Textual `TabbedContent`
  ergonomics.
- **Deferred (agreed):** Tier-2 guide sections — FX exposure check, data-anomaly
  troubleshooting table, deposits/withdrawals NAV-rescale note, asset-class
  nuances (bond multipliers, income-asset exemptions).

## Verification

- `uv run python -m pytest tests/ -q` — **298 passed** after the
  `ui_components.py` edit (docs are inert; the characterization golden master
  is untouched).
- Import + path check: `from services.ui_components import HELP_FILES` and
  existence test of all nine registered paths — all resolve.
- Internal cross-references in the User Guide re-audited after section
  renumbering (grep of all `§n` tokens; two stale refs to the old §9 lens
  section fixed to §11; remaining hits confirmed as external-guide
  references).

## Next Steps

- Tier-2 User Guide pass: FX exposure walkthrough, troubleshooting
  (splits / wrong Yahoo mapping / ghost positions), deposits-withdrawals,
  asset-class nuances.
- Honest-gap notes if desired: theme/correlation heat remains manual (G7 theme
  dimension cut; HHI is the proxy).
- Watch-list dedicated add flow polish remains on the long-term list
  (`docs/OPEN_ITEMS.md`).
