"""Tests for the local price cache.

Two things are guarded here:

  * `latest_close` — the cached-price fallback used when a live quote is
    unavailable, so a position's current price never degrades to its entry price
    (which would fabricate a stop breach for a winner whose stop sits above cost).
  * the adjustment-basis guard — Yahoo is queried with auto_adjust=True, so every
    split and dividend re-bases its whole history, while save_prices only ever
    appends unseen dates. Without detection the cache silently becomes old-basis
    history welded to new-basis recent bars.
"""
import pandas as pd
import pytest

import services.price_service as price_service
from services.price_service import PRICE_BASIS_TOLERANCE, PriceService


@pytest.fixture
def ps(tmp_path):
    return PriceService(db_path=tmp_path / "prices_test.db")


def _insert(ps, conid, rows):
    conn = ps._connect()
    conn.executemany(
        "INSERT INTO prices_daily (conid, ticker, date, close) VALUES (?, ?, ?, ?)",
        [(conid, "T", d, c) for d, c in rows],
    )
    conn.commit()
    conn.close()


def test_latest_close_returns_most_recent_by_date(ps):
    # Inserted out of order — must return the row with the latest date, not the last inserted.
    _insert(ps, "111", [("2026-06-15", 100.0), ("2026-06-17", 105.0), ("2026-06-16", 102.0)])
    assert ps.latest_close("111") == pytest.approx(105.0)


def test_latest_close_empty_cache_returns_none(ps):
    assert ps.latest_close("999") is None


def test_latest_close_coerces_conid_to_str(ps):
    _insert(ps, "222", [("2026-06-17", 88.0)])
    assert ps.latest_close(222) == pytest.approx(88.0)


# --------------------------------------------------------------------------
# Adjustment-basis guard
# --------------------------------------------------------------------------
CACHED = [("2026-06-15", 100.0), ("2026-06-16", 102.0), ("2026-06-17", 104.0)]
LATEST = pd.Timestamp("2026-06-17")


def _fetched(rows):
    """A fetch already through PriceService._normalize (date strings, lowercase)."""
    return pd.DataFrame({"date": [d for d, _ in rows], "close": [c for _, c in rows]})


def test_matching_overlap_is_not_a_basis_shift(ps):
    _insert(ps, "111", CACHED)
    same = _fetched([("2026-06-15", 100.0), ("2026-06-16", 102.0), ("2026-06-18", 106.0)])
    assert ps.basis_shifted("111", same, LATEST) is False


def test_split_rebase_is_detected(ps):
    # A 10:1 split divides Yahoo's whole history by 10 — the cached rows are now
    # an order of magnitude away from the same dates re-fetched.
    _insert(ps, "111", CACHED)
    after_split = _fetched([("2026-06-15", 10.0), ("2026-06-16", 10.2), ("2026-06-18", 10.6)])
    assert ps.basis_shifted("111", after_split, LATEST) is True


def test_dividend_rebase_is_detected(ps):
    # Far smaller than a split, and just as corrupting once it accumulates.
    _insert(ps, "111", CACHED)
    ex_div = _fetched([("2026-06-15", 99.0), ("2026-06-16", 100.98)])   # −1%
    assert ps.basis_shifted("111", ex_div, LATEST) is True


def test_rounding_noise_is_tolerated(ps):
    _insert(ps, "111", CACHED)
    nudged = _fetched([("2026-06-15", 100.0 * (1 + PRICE_BASIS_TOLERANCE / 2))])
    assert ps.basis_shifted("111", nudged, LATEST) is False


def test_latest_cached_bar_is_excluded_from_the_comparison(ps):
    # Mid-session the last cached bar is a partial day and will differ from a
    # settled re-fetch. Comparing it would rebuild the whole series every sync.
    _insert(ps, "111", CACHED)
    partial = _fetched([("2026-06-17", 130.0)])       # only the unsettled date
    assert ps.basis_shifted("111", partial, LATEST) is False


def test_no_comparable_data_never_triggers_a_rebuild(ps):
    _insert(ps, "111", CACHED)
    assert ps.basis_shifted("111", _fetched([]), LATEST) is False
    assert ps.basis_shifted("111", None, LATEST) is False
    assert ps.basis_shifted("111", _fetched(CACHED), None) is False
    # Dates we hold nothing for can't disagree with anything.
    assert ps.basis_shifted("111", _fetched([("2020-01-02", 5.0)]), LATEST) is False
    # A conid with no cache at all.
    assert ps.basis_shifted("999", _fetched(CACHED), LATEST) is False


def test_rebuild_replaces_the_whole_series(ps, monkeypatch):
    _insert(ps, "111", CACHED)
    fresh = pd.DataFrame(
        {"Open": [10.0, 10.2], "High": [10.5, 10.7], "Low": [9.8, 10.0],
         "Close": [10.0, 10.2], "Volume": [1000.0, 1100.0]},
        index=pd.to_datetime(["2026-06-15", "2026-06-16"]),
    )
    monkeypatch.setattr(price_service.yf, "download", lambda *a, **k: fresh)

    assert ps.rebuild_series("111", "TST") == 2

    conn = ps._connect()
    rows = conn.execute("SELECT date, close FROM prices_daily WHERE conid='111' ORDER BY date").fetchall()
    conn.close()
    # Old-basis rows are gone, not merged alongside the new ones.
    assert rows == [("2026-06-15", 10.0), ("2026-06-16", 10.2)]


def test_failed_rebuild_leaves_the_cache_intact(ps, monkeypatch):
    # A seamed series is still better than no series — never delete on a bad fetch.
    _insert(ps, "111", CACHED)
    monkeypatch.setattr(price_service.yf, "download", lambda *a, **k: pd.DataFrame())

    assert ps.rebuild_series("111", "TST") == 0
    assert ps.latest_close("111") == pytest.approx(104.0)
