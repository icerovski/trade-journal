from textual.widgets import Label, Static
from datetime import datetime
from services.market_data_service import fetch_fx_rate

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
    def nav_subtitle(nav: float, nav_ccy: str, n_positions: int, hint: str = "") -> str:
        """Builds a compact header sub_title with NAV, optional USD equivalent, and position count."""
        usd_part = ""
        if nav_ccy != "USD" and nav > 0:
            rate = fetch_fx_rate(nav_ccy, "USD")
            if rate:
                usd_part = f" / {nav * rate:,.0f} USD"
        hint_part = f" | {hint}" if hint else ""
        return f"AUM: {nav:,.0f} {nav_ccy}{usd_part} | {n_positions} positions{hint_part}"

    @staticmethod
    def format_percent(val, precision=1):
        """Standardized percentage formatting."""
        if val is None:
            return "---"
        return f"{val:.{precision}f}%"
