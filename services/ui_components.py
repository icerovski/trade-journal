from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import Label, Static, TabbedContent, TabPane, Markdown
from textual.containers import Vertical, ScrollableContainer
from textual.binding import Binding
from textual.screen import ModalScreen

# Repo root (parent of services/), so help renders correctly regardless of CWD.
_ROOT = Path(__file__).resolve().parent.parent

# In-app Help Desk tabs. Each tab simply renders a Markdown file — the docs/guides/*.md
# files are the SINGLE SOURCE OF TRUTH, viewable both as files and here. Editing a guide
# updates the F1 help automatically; there are no hardcoded help strings to drift.
HELP_FILES = [
    ("Rhythm",        "docs/guides/Operating_Rhythm.md"),
    ("Glossary",      "docs/guides/Indicator_Glossary.md"),
    ("Stop Playbook", "docs/guides/Stop_Placement_Playbook.md"),
    ("Strategy Lab",  "docs/guides/Strategy_Lab_Syntax.md"),
    ("Exit Strategy", "docs/guides/Exit_Strategy.md"),
    ("Zone Scanner",  "docs/guides/Zone_Scanner_Guide.md"),
    ("Technical",     "docs/TECHNICAL_DOCS.md"),
]


def _read_doc(rel_path: str) -> str:
    try:
        return (_ROOT / rel_path).read_text(encoding="utf-8")
    except Exception:
        return f"# Not found\n\n`{rel_path}` could not be loaded."


class HelpScreen(ModalScreen):
    """An overlay screen providing definitions and shortcuts, sourced from docs/guides."""
    BINDINGS = [Binding("escape,f1", "dismiss", "Close")]

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-modal {
        width: 90%;
        height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        height: 1fr;
        padding: 0;
    }
    .help-scroll {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-modal"):
            yield Label("HELP DESK & GLOSSARY", classes="panel-header")
            with TabbedContent(initial="tab-0"):
                for i, (label, rel_path) in enumerate(HELP_FILES):
                    with TabPane(label, id=f"tab-{i}"):
                        with ScrollableContainer(classes="help-scroll"):
                            yield Markdown(_read_doc(rel_path))
            yield Label("Press ESC or F1 to Close", id="close-hint")
