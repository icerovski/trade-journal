Follow these steps exactly when the user says "wrap it up", "wrap up", or "document the session".

## 1. Research Changes

Run in parallel:
- `git diff --stat` — all modified files since last commit
- `git log --oneline -10` — recent commits to identify what was done this session

## 2. Create Session Log

Create `docs/sessions/YYYY-MM-DD_Brief_Description.md` using today's date and a 3–5 word semantic description of the session theme.

Structure (all sections required):
- **Objectives** — what we set out to do
- **Technical Changes** — bulleted list of modifications with file paths and line references where relevant
- **Logic & Decisions** — the *why* behind non-obvious choices: risk formulas, architectural decisions, data invariants, trade-offs considered
- **Verification** — test results, manual checks, confirmed behaviours
- **Next Steps** — open items for the next session

## 3. Update CLAUDE.md

Update only for **architectural changes**: new or moved modules, schema changes, new core invariants, renamed files. Do not add feature detail, UI copy, thresholds, or session-specific notes — those belong in the session log.

## 4. Update docs/TECHNICAL_DOCS.md

Update for **user-facing feature additions or changes**: new UI commands, new risk metrics, new workflow steps, changed key bindings. Follow the existing numbered-section structure. Keep Textual-safe markdown — no deeply nested tables or unsupported CSS classes (the F1 Help system renders this file in a Textual `Static` widget).

## 5. Commit

Stage the session log and any doc changes. Commit with a clear message describing what the session covered.

## 6. Remind Backup

Tell the user: "Run `uv run python sync_config.py` to back up `.env` to OneDrive."

---

**Tone:** Professional and direct. PE-grade auditability — focus on mathematical integrity and data provenance. High-signal only, no filler.
