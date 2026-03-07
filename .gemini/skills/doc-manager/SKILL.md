---
name: doc-manager
description: Automates the maintenance of technical documentation (docs/TECHNICAL_DOCS.md). Use when updating existing features or implementing new ones to ensure the "Single Source of Truth" remains accurate.
---

# Documentation Manager Skill

This skill ensures that all technical implementations and operational workflows are accurately recorded in `docs/TECHNICAL_DOCS.md`.

## Workflow

### 1. Update Existing Functionalities
When you modify an existing feature (e.g., changing risk formulas, updating UI behavior, or refactoring core logic):
- Identify the relevant section in `docs/TECHNICAL_DOCS.md`.
- Update the **Operational Workflow** and **Technical Implementation Details** to reflect the new state.
- Ensure the language remains professional, direct, and PE-grade.

### 2. Document New Functionalities
When you implement a completely new feature (e.g., adding a new module, integrating a new API, or creating a new dashboard):
- **Mandatory Step**: Ask the user: "I've implemented a new functionality [Name]. Would you like me to create the technical documentation for it in the Help system?"
- If the user agrees:
    - Create a new numbered section in `docs/TECHNICAL_DOCS.md`.
    - Follow the established structure:
        - **Description**: High-level purpose of the feature.
        - **Operational Workflow**: Step-by-step instructions for the user.
        - **Technical Implementation Details**: Data persistence, core logic, and architectural integration.

## Design Principles
- **Consiseness**: Keep documentation high-signal. Focus on "How it works" and "How to use it".
- **Single Source of Truth**: `docs/TECHNICAL_DOCS.md` is the authoritative record for the application's capabilities.
- **Dynamic Integration**: Remember that `risk_workspace.py` dynamically reads this file for the F1 Help system. Avoid using complex markdown that might break the Textual `Static` widget rendering (e.g., deeply nested tables or unsupported CSS classes).
