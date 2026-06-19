"""Tests for PriceService.latest_close — the cached-price fallback used when a live quote is
unavailable, so a position's current price never degrades to its entry price (which would
fabricate a stop breach for a winner whose stop sits above cost)."""
import pytest

from services.price_service import PriceService


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
