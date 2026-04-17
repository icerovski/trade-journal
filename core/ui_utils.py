from textual.widgets import Label, Static
from datetime import datetime

class UIUtils:
    """
    Centralized theme and helper methods for Textual UI components.
    Ensures visual consistency across all workspaces.
    """
    
    # Theme Colors
    COLOR_POSITIVE = "green"
    COLOR_NEGATIVE = "red"
    COLOR_NEUTRAL = "white"
    COLOR_ACCENT = "cyan"
    COLOR_WARNING = "yellow"
    
    @staticmethod
    def color_fmt(val, fmt=",.0f", suffix="", include_brackets=True):
        """Standardized color formatting for financial metrics."""
        if val is None:
            return "---"
        color = UIUtils.COLOR_POSITIVE if val >= 0 else UIUtils.COLOR_NEGATIVE
        result = f"{val:{fmt}}{suffix}"
        return f"[{color}]{result}[/]" if include_brackets else (color, result)

    @staticmethod
    def get_timestamp_str():
        """Returns standard timestamp for status bars."""
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def format_percent(val, precision=1):
        """Standardized percentage formatting."""
        if val is None:
            return "---"
        return f"{val:.{precision}f}%"
