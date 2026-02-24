---
name: session-logger
description: Automates the wrap-up of a development session by generating semantic logs and updating the project's technical architecture (GEMINI.md). Use when the user wants to "wrap up," "document the session," or "summarize work." Installation instructions: To use this skill in future sessions, simply run 'gemini skills install session-logger.skill --scope workspace' and 'then /skills reload'.
---

# Session Logger Skill

This skill ensures that every session is documented with the rigor required for a Private Equity trading desk. It maintains the "Single Source of Truth" and provides an auditable trail of changes.

## Workflow

When triggered (e.g., "Wrap up the session"), follow these steps:

### 1. Research Changes
- Run `git status` and `git diff HEAD` to see all code changes.
- Identify new files, modified logic, and updated configurations.

### 2. Generate Session Log
Create a new file in `docs/sessions/YYYY-MM-DD_Brief_Description.md`.
Use the following structure:
- **Title:** Semantic name of the session.
- **Objectives:** What were we trying to achieve?
- **Technical Changes:** Bulleted list of code modifications.
- **Logic & Decisions:** Explain the *why* behind critical logic (e.g., Ledger math, Risk formulas).
- **Verification:** Results of any tests or database rebuilds performed.
- **Next Steps:** Open items for the next session.

### 3. Update GEMINI.md
Synchronize the **Technical Architecture** section of `GEMINI.md` with the new reality:
- Update module descriptions if their responsibilities changed.
- Update data flow diagrams or logic protocols.
- Ensure the "Single Source of Truth" reflects the latest file paths and environment variables.

### 4. Backup
Trigger the project's backup mechanism (e.g., `uv run python sync_config.py` or the built-in CLI backup option) to ensure documentation is mirrored to OneDrive.

### 5. Git Synchronization
Proactively manage the session's source control:
- Stage all changes with `git add .`.
- Propose a concise, semantic commit message based on the session's objectives.
- Ask the user for confirmation to commit and push to the current remote branch.
- Execute `git commit -m "..."` and `git push` only after explicit confirmation.

## Tone & Style
- **Professional & Direct:** Use clear, senior-engineer-level language.
- **PE-Grade Auditability:** Focus on mathematical integrity and data provenance.
- **Minimal Filler:** High-signal information only.
