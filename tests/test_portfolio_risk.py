"""Portfolio-level risk aggregation (core/sizing.compute_portfolio_risk).

The load-bearing rule here is that portfolio HEAT does not net. `risk_pct_nav` is
(entry − stop) × qty / NAV, so a position whose stop has ratcheted above entry
carries a NEGATIVE value — a gain locked in at its stop. That is the right sign
for "what does a full stop-out pay me", and the wrong sign for "how much NAV is
still at risk". Summing raw lets one winner cancel live downside on other names
and hands back budget headroom that does not exist; the same figure feeds the G7
heat gate, so the error would wave through an entry as well as mis-report one.
"""

import pandas as pd
import pytest

from core.sizing import compute_portfolio_risk, hhi_label


NAV = 1_000_000.0


def _book(*positions) -> pd.DataFrame:
    """Rows in the shape get_dashboard_df hands the report."""
    rows = []
    for i, p in enumerate(positions):
        entry, stop, qty = p["entry"], p["stop"], p["qty"]
        risk_val = (stop - entry) * qty          # negative = loss at stop, as Position sets it
        rows.append({
            "Ticker": p.get("ticker", f"T{i}"),
            "Qty": qty,
            "Entry": entry,
            "Price": p.get("price", entry),
            "SL_Price": stop,
            "Risk_Val": risk_val,
            "risk_pct_nav": (entry - stop) * qty / NAV * 100.0,
            "NavPct": p.get("nav_pct", entry * qty / NAV * 100.0),
            "MaxRPct": p.get("max_r_pct", 1.0),
            "FXRate": p.get("fx", 1.0),
            "CCY": p.get("ccy", "USD"),
        })
    return pd.DataFrame(rows)


def _loser(**over):
    """1% of NAV at risk: 1,000 shares, 10 wide."""
    return {"entry": 100.0, "stop": 90.0, "qty": 1000.0, **over}


def _locked_in(**over):
    """A ratcheted winner: stop 30 ABOVE entry → −3% risk_pct_nav."""
    return {"entry": 100.0, "stop": 130.0, "qty": 1000.0, "price": 140.0, **over}


# --------------------------------------------------------------------------
# Heat does not net
# --------------------------------------------------------------------------
def test_locked_in_winner_does_not_cancel_live_risk():
    m = compute_portfolio_risk(
        _book(_loser(ticker="A"), _loser(ticker="B"), _loser(ticker="C"), _locked_in(ticker="W")),
        NAV, "EUR",
    )
    # Three names can still lose 1% each. The winner's −3% must not erase them.
    assert m["total_r_pct"] == pytest.approx(3.0)
    assert m["total_r_pct_net"] == pytest.approx(0.0)
    assert m["n_locked_in"] == 1


def test_headroom_and_budget_use_the_unnetted_heat():
    m = compute_portfolio_risk(
        _book(_loser(ticker="A"), _loser(ticker="B"), _loser(ticker="C"), _locked_in(ticker="W")),
        NAV, "EUR",
    )
    # 4 positions × 1% budget = 4%; 3% of it is genuinely committed.
    assert m["total_budget"] == pytest.approx(4.0)
    assert m["headroom"] == pytest.approx(1.0)          # not 4.0
    assert m["pct_budget_used"] == pytest.approx(75.0)  # not 0


def test_book_of_only_locked_in_winners_reports_zero_heat():
    m = compute_portfolio_risk(_book(_locked_in(ticker="W1"), _locked_in(ticker="W2")), NAV, "EUR")
    assert m["total_r_pct"] == pytest.approx(0.0)   # no downside — but never negative
    assert m["total_r_pct_net"] == pytest.approx(-6.0)
    assert m["headroom"] == pytest.approx(2.0)


def test_ordinary_book_is_unchanged_by_the_clamp():
    plain = _book(_loser(ticker="A"), _loser(ticker="B"))
    m = compute_portfolio_risk(plain, NAV, "EUR")
    assert m["total_r_pct"] == pytest.approx(2.0)
    assert m["total_r_pct"] == pytest.approx(m["total_r_pct_net"])
    assert m["n_locked_in"] == 0


def test_stop_out_pl_stays_net():
    # Currency P/L is the one place netting is correct: if every stop hit, the
    # winner really does pay for the losers.
    m = compute_portfolio_risk(_book(_loser(ticker="A"), _locked_in(ticker="W")), NAV, "EUR")
    assert m["total_stop_out"] == pytest.approx(-10_000.0 + 30_000.0)


def test_fx_applies_to_the_stop_out_total():
    m = compute_portfolio_risk(_book(_loser(ticker="A", fx=0.9)), NAV, "EUR")
    assert m["total_stop_out"] == pytest.approx(-9_000.0)


# --------------------------------------------------------------------------
# The rest of the aggregate
# --------------------------------------------------------------------------
def test_unstopped_positions_are_counted_but_carry_no_risk():
    book = _book(_loser(ticker="A"), _loser(ticker="B"))
    book.loc[1, "SL_Price"] = None
    m = compute_portfolio_risk(book, NAV, "EUR")
    assert m["n_active"] == 2
    assert m["n_with_stop"] == 1 and m["n_without_stop"] == 1
    assert m["unmanaged"] == ["B"]
    assert m["total_r_pct"] == pytest.approx(1.0)
    assert m["total_budget"] == pytest.approx(1.0)  # no budget claimed for an unstopped name


def test_breached_positions_are_flagged():
    m = compute_portfolio_risk(
        _book(_loser(ticker="A", price=85.0), _loser(ticker="B", price=120.0)), NAV, "EUR",
    )
    assert m["n_breached"] == 1 and m["breached_tickers"] == ["A"]


def test_currency_breakdown_splits_exposure():
    m = compute_portfolio_risk(
        _book(_loser(ticker="A", ccy="USD"), _loser(ticker="B", ccy="EUR")), NAV, "EUR",
    )
    assert set(m["ccy_breakdown"]) == {"USD", "EUR"}
    assert sum(share for _, share in m["ccy_breakdown"].values()) == pytest.approx(100.0)


def test_hhi_reflects_concentration():
    # 20 equal names → HHI 0.05. (Exactly 10 lands on 0.10, the green/yellow
    # boundary — hhi_label is `< 0.10` — so stay off the knife-edge here.)
    even = compute_portfolio_risk(
        _book(*[_loser(ticker=f"T{i}") for i in range(20)]), NAV, "EUR")
    concentrated = compute_portfolio_risk(
        _book(_loser(ticker="BIG", nav_pct=90.0), _loser(ticker="SMALL", nav_pct=10.0)), NAV, "EUR")
    assert even["hhi"] < concentrated["hhi"]
    assert hhi_label(even["hhi"])[0] == "green"
    assert hhi_label(concentrated["hhi"])[0] == "red"


def test_empty_and_degenerate_inputs_return_empty():
    assert compute_portfolio_risk(pd.DataFrame(), NAV, "EUR") == {}
    assert compute_portfolio_risk(_book(_loser()), 0.0, "EUR") == {}
    flat = _book(_loser())
    flat.loc[0, "Qty"] = 0.0
    assert compute_portfolio_risk(flat, NAV, "EUR") == {}
