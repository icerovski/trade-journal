# Application Assessment Brief — for Fable

> **How to use (not part of the prompt):** paste everything below the line into a chat with
> Fable, with the repo / relevant source files and `Entry_and_Stop_System.md`,
> `Horizon_Calibration_3to6mo.md` available (either pasted in or accessible in context).
> If Fable can't see the live repo, paste the key modules directly — the sizing/risk logic,
> the gates module, the exit ladder, the ATR/volatility calc, and the config/profile files
> at minimum.

---

You are assessing a working swing-trading application built for a single user: positions
held 3–6 months, a handful of trades per month, trade ideas sourced externally (Stansberry
Research) with entries/stops/sizing decided independently. Risk is capped at 1% of NAV per
trade. The user is Bulgaria-based holding USD-denominated US equities, so currency exposure
is a real (not cosmetic) dimension. Two documents in the repo — `Entry_and_Stop_System.md`
and `Horizon_Calibration_3to6mo.md` — are the canonical spec; the code was built against them
in phases.

**The goal of this review is to find the balance between a professional-grade system and one
that stays simple enough for someone trading a few times a month.** Don't just list every
possible improvement — help identify which complexity is earning its place and which isn't.

## Assess in this order (stop escalating effort once a tier is clean)

### Tier 1 — Financial correctness (highest priority)
- Does the implementation actually match the two spec docs? Flag any drift between gates
  G1–G8, THESIS vs. TECHNICAL classification, and the three exit shapes (hard target /
  scale-out+runner / thesis-exit).
- Verify position sizing enforces the 1% NAV risk cap in every code path, including any
  gap-aware sizing variant for event-adjacent trades.
- **Explicitly confirm no time-based forced exit exists anywhere in the code.** This was a
  deliberate design decision (time is a smoothing lens only, never an exit trigger) —
  re-verify it holds in the implementation, not just the docs.
- Check the ATR/volatility calculation: correct 12–24 month lookback, expressed in
  percent-of-price terms (not raw ATR multiples), and how the code handles the staleness
  risk of a long lookback during volatility expansion.
- Check the currency/base-currency gate (G8) — is it a real calculation against actual
  exposure, or a placeholder check?
- Where possible, **test with concrete numbers** (a few representative trades) rather than
  reading logic in the abstract — sizing and stop-width bugs are easiest to catch by
  recomputing the math by hand and comparing.

### Tier 2 — Data integrity & edge cases
- Behavior on thin/short price history (recent listings, insufficient bars for the long ATR).
- Earnings-proximity gate (G3) and event-adjacent gap sizing correctness.
- Log schema backward compatibility — older log rows without newer fields must still load
  and save without error.

### Tier 3 — Workflow friction (this is where "simplicity" lives)
- Walk through one full trade decision end-to-end and count the actual steps/screens/config
  choices involved. Does that match a cadence of a few trades a month, or does it feel like
  overhead built for a desk trading daily?
- Is the `gates_mode` flag (off/advisory/blocking) and the calibration profile switch
  (default vs. 3–6 month profile) easy to reason about at a glance, or does it require
  remembering internal state after weeks away from the app?
- Because positions are held for months, the user may not touch the app for weeks at a time.
  Can they reorient quickly on return, or does resuming require re-learning current
  configuration?

### Tier 4 — Code quality
- Did implementation follow "prefer new modules, don't rewrite working functions"? Flag any
  hidden coupling or rewritten paths that should have been additive.
- Confirm the original characterization/snapshot tests (from the initial mapping phase) still
  exist and still pass unchanged.

### Tier 5 — Extensibility
- How easily could a new gate, a retuned ATR period, or a new trade archetype be added
  without risking the snapshot tests?

## Output format requested

1. A short executive summary (5–10 lines) — overall state, and the single biggest risk if
   one exists.
2. Findings by tier above, most severe first within each tier.
3. Recommendations, each tagged as one of:
   - **Must-fix** — financial correctness issue, could cause a wrong stop/size/exit
   - **Should-fix** — robustness/data-integrity issue, unlikely but possible harm
   - **Consider** — usability improvement, no correctness risk
   - **Cut** — technically fine but adds complexity/surface area disproportionate to a
     few-trades-a-month cadence; name the specific feature and why it doesn't earn its keep
4. For any major feature (a gate, a config profile, an analytics report), a one-line verdict:
   *does this pull its weight given how often it will actually be used?*
