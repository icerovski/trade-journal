"""Outcome backfill (Entry & Stop System §7) — pure-core tests.

Covers the zero-crossing replay (find_close_after), the MAE/MFE excursion math,
and the benchmark window return. The run_backfill() runner is thin I/O wiring
and is exercised manually via menu option 9.
"""

import pandas as pd

from core.outcome_backfill import find_close_after, compute_excursions, window_return


def _t(date, side, qty, price, source="MANUAL"):
    return {"date": date, "side": side, "quantity": qty, "price": price, "source": source}


class TestFindCloseAfter:
    def test_simple_buy_then_full_sell(self):
        trades = [
            _t("2026-01-05", "BUY", 100, 50.0),
            _t("2026-03-10", "SELL", 100, 60.0),
        ]
        assert find_close_after(trades, "2026-01-05") == ("2026-03-10", 60.0)

    def test_still_open_returns_none(self):
        trades = [
            _t("2026-01-05", "BUY", 100, 50.0),
            _t("2026-02-01", "SELL", 40, 55.0),  # partial — 60 shares remain
        ]
        assert find_close_after(trades, "2026-01-05") is None

    def test_exit_price_is_qty_weighted_over_the_closeout(self):
        trades = [
            _t("2026-01-05", "BUY", 100, 50.0),
            _t("2026-02-01", "SELL", 50, 60.0),
            _t("2026-03-01", "SELL", 50, 70.0),
        ]
        close = find_close_after(trades, "2026-01-05")
        assert close is not None
        assert close[0] == "2026-03-01"
        assert close[1] == 65.0  # (50×60 + 50×70) / 100

    def test_close_before_log_date_is_a_prior_lot(self):
        # A round trip BEFORE the log date must not be read as this trade's exit;
        # the re-entry after the log date is still open.
        trades = [
            _t("2025-06-01", "BUY", 100, 30.0),
            _t("2025-09-01", "SELL", 100, 40.0),   # prior lot closes
            _t("2026-01-05", "BUY", 100, 50.0),    # the logged trade
        ]
        assert find_close_after(trades, "2026-01-05") is None

    def test_prior_lot_sells_do_not_pollute_exit_avg(self):
        trades = [
            _t("2025-06-01", "BUY", 100, 30.0),
            _t("2025-09-01", "SELL", 100, 40.0),
            _t("2026-01-05", "BUY", 100, 50.0),
            _t("2026-04-01", "SELL", 100, 80.0),
        ]
        assert find_close_after(trades, "2026-01-05") == ("2026-04-01", 80.0)

    def test_split_inside_window_bails_out(self):
        # Post-split prices don't compare to the logged entry/stop → no R, not a wrong R.
        trades = [
            _t("2026-01-05", "BUY", 100, 50.0),
            _t("2026-02-01", "SPLIT", 100, 0.0),   # 2:1 forward split (+100 shares)
            _t("2026-03-01", "SELL", 200, 30.0),
        ]
        assert find_close_after(trades, "2026-01-05") is None

    def test_transfer_out_counts_as_a_close(self):
        trades = [
            _t("2026-01-05", "BUY", 100, 50.0),
            _t("2026-05-01", "TRANSFER_OUT", 100, 58.0),
        ]
        assert find_close_after(trades, "2026-01-05") == ("2026-05-01", 58.0)

    def test_empty_ledger(self):
        assert find_close_after([], "2026-01-05") is None


class TestComputeExcursions:
    def _df(self, lows, highs):
        idx = pd.date_range("2026-01-05", periods=len(lows), freq="D")
        return pd.DataFrame({"Low": lows, "High": highs}, index=idx)

    def test_mae_mfe_in_r_units(self):
        # entry 100, r1 = 5; worst low 92.5 → MAE 1.5R; best high 115 → MFE 3R.
        df = self._df([98, 92.5, 105], [103, 99, 115])
        assert compute_excursions(df, 100.0, 5.0) == (1.5, 3.0)

    def test_floored_at_zero(self):
        # Price never went below entry → MAE 0, not negative.
        df = self._df([101, 104], [106, 110])
        mae, mfe = compute_excursions(df, 100.0, 5.0)
        assert mae == 0.0 and mfe == 2.0

    def test_missing_data_returns_none(self):
        assert compute_excursions(None, 100.0, 5.0) == (None, None)
        assert compute_excursions(self._df([98], [103]), 100.0, 0.0) == (None, None)
        assert compute_excursions(pd.DataFrame(), 100.0, 5.0) == (None, None)

    def test_lowercase_columns_accepted(self):
        idx = pd.date_range("2026-01-05", periods=2, freq="D")
        df = pd.DataFrame({"low": [95, 96], "high": [104, 108]}, index=idx)
        assert compute_excursions(df, 100.0, 5.0) == (1.0, 1.6)


class TestWindowReturn:
    def _bench(self):
        idx = pd.date_range("2026-01-01", periods=10, freq="D")
        closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 110]
        return pd.DataFrame({"Close": closes}, index=idx)

    def test_window_return(self):
        # first close on/after Jan 3 = 102; last close on/before Jan 8 = 107.
        r = window_return(self._bench(), "2026-01-03", "2026-01-08")
        assert abs(r - (107 / 102 - 1)) < 1e-12

    def test_open_ended_uses_latest(self):
        r = window_return(self._bench(), "2026-01-03")
        assert abs(r - (110 / 102 - 1)) < 1e-12

    def test_start_after_data_returns_none(self):
        assert window_return(self._bench(), "2027-01-01") is None

    def test_empty_df_returns_none(self):
        assert window_return(pd.DataFrame(), "2026-01-03") is None
        assert window_return(None, "2026-01-03") is None
