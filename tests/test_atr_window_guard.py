"""FIXED inception-ATR snap guard (assessment Must-fix #2).

`_compute_atr_rows` shrinks a timeframe's ATR window when history is thin
(`actual_window = min(window, len(df) - 1)`) but keeps the timeframe label. A
"12q" ATR computed from 3 quarterly bars is not a quarterly ATR — and the FIXED
commit path snaps the position's frozen R unit to the nearest of these values,
permanently mis-scaling the exit ladder. Rows now carry `window_shrunk`, and
every snap site excludes flagged rows.
"""

import numpy as np
import pandas as pd

from core.stop_loss import _compute_atr_rows


def _daily_df(n: int) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    close = 100.0 + 0.01 * np.arange(n)
    return pd.DataFrame({
        "Open": close, "High": close + 1.0, "Low": close - 1.0,
        "Close": close, "Volume": np.full(n, 1000.0),
    }, index=idx)


def _rows(n_days: int):
    # conid=None -> prospect path: pure resampling of the supplied daily frame,
    # no price_service I/O. total_nav=0 keeps sizing out of the picture.
    return _compute_atr_rows(
        "TEST", None, 100.0, 101.0, 100.0,
        1.0, 1.0, 0.0, 0.0, 1.0, 5.0,
        price_service=None, df_prospect_daily=_daily_df(n_days),
    )


def _shrunk_by_label(rows) -> dict:
    out = {}
    for r in rows:
        assert out.setdefault(r.label, r.window_shrunk) == r.window_shrunk, \
            "FIXED and TRAILING rows of one timeframe must agree on window_shrunk"
    return out


def test_ample_history_no_rows_flagged():
    # ~4.4 years of daily bars: every timeframe has more bars than its window.
    flags = _shrunk_by_label(_rows(1600))
    assert flags == {"14d": False, "12w": False, "12m": False, "12q": False}


def test_thin_history_flags_higher_timeframes():
    # 40 daily bars: daily(14) is fine, but weekly(12)/monthly(12) collapse to a
    # handful of bars; quarterly has <2 bars and is skipped entirely.
    flags = _shrunk_by_label(_rows(40))
    assert flags["14d"] is False
    assert flags["12w"] is True
    assert flags["12m"] is True
    assert "12q" not in flags


def test_very_thin_history_flags_daily_too():
    # 10 bars cannot fill even the 14-day window.
    flags = _shrunk_by_label(_rows(10))
    assert all(flags.values())
    assert flags["14d"] is True


def test_snap_excludes_shrunken_rows():
    from core.stop_loss import snap_inception_atr
    from models import ATRDiscoveryRow

    def row(label, atr, shrunk):
        return ATRDiscoveryRow(
            label=label, stop_type="FIXED", atr_wilder=atr, atr_sma=atr,
            stop_price=0.0, atr_base_pct=0.0, pl_at_stop=0.0, buffer_pct=0.0,
            pl_pct_nav=0.0, window_shrunk=shrunk,
        )

    # The shrunken quarterly value (9.9) is nearest the risk distance but must
    # lose to the trustworthy weekly value.
    rows = [row("14d", 2.0, False), row("12w", 6.0, False), row("12q", 9.9, True)]
    atr, label = snap_inception_atr(rows, risk_dist=10.0)
    assert (atr, label) == (6.0, "12w")

    # All rows shrunken -> no snap at all (caller falls back / warns).
    assert snap_inception_atr([row("12m", 5.0, True)], risk_dist=5.0) == (None, None)


def test_migrate_tool_uses_the_shared_snap_rule():
    """The retroactive migration tool must run the SAME snap implementation as the
    live commit path — parity by identity, not by parallel maintenance."""
    from core.stop_loss import snap_inception_atr
    from tools.migrate_fixed_inception_atr import _snap_atr

    assert _snap_atr is snap_inception_atr
