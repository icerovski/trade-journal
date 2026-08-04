"""The broker-snapshot ingestion boundary (`DataLoader.get_broker_verified_snapshot`).

This is where external data enters a system whose entire value is being right
about numbers. Everything downstream — the reconciliation checkpoint, cost basis,
FX normalisation, the asset master — is derived from what this function returns,
and it had no tests: the IBKR Flex CSV is messy in specific, recurring ways
(repeated header rows mid-file, preamble lines before the real header, blank
totals rows, quantities as face value for bonds), and each of those is handled by
a line here that nothing was checking.

Fixtures are shaped like the real file: the live `open_positions_lbd.csv` carries
45 SUMMARY rows interleaved with 5 repeated header rows, which is why the
`Symbol != 'Symbol'` filter exists.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import config
from data_loader import DataLoader

HEADER = (
    "ClientAccountID,LevelOfDetail,Symbol,Conid,Quantity,CostBasisPrice,MarkPrice,"
    "Multiplier,PercentOfNAV,FXRateToBase,AssetClass,Description,ListingExchange,"
    "CurrencyPrimary,UnderlyingSymbol,ISIN,ReportDate,OpenDateTime"
)

AAPL_SUMMARY = ("U1,SUMMARY,AAPL,12345,100,150.0,160.0,1,5.0,0.92,STK,Apple Inc,"
                "NASDAQ,USD,,US0378331005,2026-07-30,")


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    """Writes a CSV and points the loader at it. Returns a writer callable."""
    path = tmp_path / "open_positions_lbd.csv"

    def _write(*rows, header=HEADER, preamble=""):
        body = "\n".join(rows)
        path.write_text(f"{preamble}{header}\n{body}\n" if header else f"{preamble}{body}\n")
        monkeypatch.setattr(config, "IBKR_OPEN_POSITIONS_CSV", path)
        return path

    return _write


@pytest.fixture(autouse=True)
def _no_db_writes():
    """The loader writes the asset master as a side effect of reading. Tests must
    not touch a real database — and the mock lets us assert what it recorded."""
    with patch("data_loader.db", MagicMock()) as m:
        yield m


def _load():
    return DataLoader.get_broker_verified_snapshot()


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------
def test_summary_row_becomes_one_keyed_position(snapshot):
    snapshot(AAPL_SUMMARY)
    data, report_date = _load()

    assert list(data) == ["U1:12345"]          # keyed account:conid, not by symbol
    row = data["U1:12345"]
    assert row["Symbol"] == "AAPL"
    assert row["Qty"] == 100.0
    assert row["Entry"] == 150.0               # CostBasisPrice
    assert row["MarkPrice"] == 160.0
    assert row["Currency"] == "USD"
    assert row["FXRateToEUR"] == 0.92
    assert report_date == pd.Timestamp("2026-07-30")


def test_yyyymmdd_report_date_silently_becomes_1970_known_defect(snapshot):
    """PINS A REAL RISK — latent under the current Flex configuration.

    The live open-positions query emits ISO dates ('2026-07-29'), which parse
    correctly. But IBKR Flex lets the date format be set per query, and the
    *trades* query in this same app is configured as yyyyMMdd. Feed that format
    here and `pd.to_datetime(20260730)` reads the integer as NANOSECONDS since the
    epoch — 1970-01-01 — with no error.

    The consequence is not a cosmetic date: `report_date` is the reconciliation
    checkpoint. `_filter_pending_deltas` applies every IBKR_CONFIRMATION dated
    AFTER it as a delta on top of the snapshot, so a 1970 checkpoint means every
    confirmation is re-applied to a snapshot that already contains it —
    double-counted positions.

    Pinned rather than fixed: the fix is a format-aware parse, which is a
    behaviour change and belongs in its own commit.
    """
    snapshot(AAPL_SUMMARY.replace(",2026-07-30,", ",20260730,"))
    _, report_date = _load()
    assert report_date == pd.Timestamp("1970-01-01 00:00:00.020260730")
    assert report_date.year == 1970


def test_asset_master_is_updated_from_the_snapshot(snapshot, _no_db_writes):
    snapshot(AAPL_SUMMARY)
    _load()

    # Collected during the parse, written once at the end (see test_write_boundaries).
    rows = _no_db_writes.save_ticker_info_bulk.call_args.args[0]
    assert len(rows) == 1
    row = rows[0]
    assert row["conid"] == "12345"
    assert row["ticker_ibkr"] == "AAPL"
    assert row["isin"] == "US0378331005"
    assert row["asset_class"] == "STK"


# --------------------------------------------------------------------------
# Real-world CSV mess
# --------------------------------------------------------------------------
def test_repeated_header_rows_are_filtered(snapshot):
    # The live file interleaves header rows between data rows — 5 of them in 50.
    snapshot(AAPL_SUMMARY, HEADER.replace("ClientAccountID", "U1"), AAPL_SUMMARY.replace("AAPL,12345", "MSFT,67890"))
    data, _ = _load()
    assert set(data) == {"U1:12345", "U1:67890"}
    assert all(r["Symbol"] != "Symbol" for r in data.values())


def test_header_is_discovered_below_a_preamble(snapshot):
    """Some Flex exports lead with a section/title line before the real header.

    The recovery scans the first 10 parsed rows for the 'LevelOfDetail' cell and
    re-seats the header there. It only works when the preamble is at least as wide
    as the data: pandas fixes the column count from line 1, and `on_bad_lines=skip`
    silently discards every wider row after it — including the real header. IBKR
    pads its section lines with commas, which is why this holds in practice.
    """
    pad = "," * (HEADER.count(",") )
    snapshot(AAPL_SUMMARY, preamble=f"Open Positions Report{pad}\n")
    data, _ = _load()
    assert list(data) == ["U1:12345"]


def test_a_narrow_preamble_defeats_header_discovery_known_limitation(snapshot):
    # Documented so the boundary of the recovery above is explicit rather than
    # discovered later against a real file: a 4-column title line makes pandas
    # skip the 18-column header, and the snapshot degrades to empty (not wrong).
    snapshot(AAPL_SUMMARY, preamble="Open Positions Report,,,\n")
    assert _load() == ({}, None)


def test_missing_file_returns_empty(snapshot, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IBKR_OPEN_POSITIONS_CSV", tmp_path / "absent.csv")
    assert _load() == ({}, None)


def test_file_without_the_key_column_returns_empty(snapshot):
    snapshot("AAPL,100", header="Symbol,Quantity")
    assert _load() == ({}, None)


def test_no_summary_rows_returns_empty(snapshot):
    # A LOT-only file has no position totals to trust as a checkpoint.
    snapshot(AAPL_SUMMARY.replace(",SUMMARY,", ",LOT,"))
    assert _load() == ({}, None)


def test_unparseable_file_degrades_instead_of_raising(snapshot, tmp_path, monkeypatch):
    path = tmp_path / "binary.csv"
    path.write_bytes(b"\x00\x01\x02 not a csv \xff")
    monkeypatch.setattr(config, "IBKR_OPEN_POSITIONS_CSV", path)
    assert _load() == ({}, None)


# --------------------------------------------------------------------------
# Numeric coercion
# --------------------------------------------------------------------------
def test_zero_quantity_positions_are_dropped(snapshot):
    snapshot(AAPL_SUMMARY.replace(",100,150.0", ",0,150.0"))
    data, _ = _load()
    assert data == {}


def test_rows_without_a_conid_are_dropped(snapshot):
    snapshot("U1,SUMMARY,AAPL,,100,150.0,160.0,1,5.0,0.92,STK,Apple,NASDAQ,USD,,,2026-07-30,")
    data, _ = _load()
    assert data == {}


def test_float_conid_is_normalised_to_an_integer_string(snapshot):
    # A blank conid anywhere makes pandas read the column as float — "12345.0".
    # The key must still be "12345" or it will not join to the ledger.
    snapshot(AAPL_SUMMARY,
             "U1,SUMMARY,MSFT,,0,0,0,1,0,1,STK,Blank,NASDAQ,USD,,,2026-07-30,")
    data, _ = _load()
    assert list(data) == ["U1:12345"]


def test_zero_multiplier_is_corrected_to_one(snapshot):
    # A 0 multiplier would zero out every value derived from the position.
    snapshot(AAPL_SUMMARY.replace(",160.0,1,", ",160.0,0,"))
    data, _ = _load()
    assert data["U1:12345"]["Multiplier"] == 1.0


def test_missing_fx_rate_falls_back_to_par(snapshot):
    snapshot(AAPL_SUMMARY.replace(",5.0,0.92,", ",5.0,,"))
    data, _ = _load()
    assert data["U1:12345"]["FXRateToEUR"] == 1.0


def test_nav_percent_is_summed_across_duplicate_rows(snapshot):
    snapshot(AAPL_SUMMARY, AAPL_SUMMARY)
    data, _ = _load()
    assert data["U1:12345"]["Qty"] == 200.0        # quantities add
    assert data["U1:12345"]["NavPct"] == 10.0      # and so does NAV%


# --------------------------------------------------------------------------
# Asset-class rules
# --------------------------------------------------------------------------
def test_bond_face_value_is_scaled_to_par_units(snapshot):
    # IBKR reports bonds as face value (100,000) priced in % of par. The ledger
    # wants $1000-par units with a 10x multiplier.
    snapshot("U1,SUMMARY,GOVT,55555,100000,98.5,99.0,1,5.0,1.0,BOND,Govt Bond,"
             "LSE,USD,,US912828,2026-07-30,")
    data, _ = _load()
    row = data["U1:55555"]
    assert row["Qty"] == pytest.approx(100.0)      # 100000 / 1000
    assert row["Multiplier"] == pytest.approx(10.0)


def test_equity_quantity_and_multiplier_are_untouched(snapshot):
    snapshot(AAPL_SUMMARY)
    row = _load()[0]["U1:12345"]
    assert row["Qty"] == 100.0 and row["Multiplier"] == 1.0


# --------------------------------------------------------------------------
# Multi-account
# --------------------------------------------------------------------------
def test_same_conid_in_two_accounts_stays_separate(snapshot):
    # Consolidation is a later, deliberate step (PortfolioManager). The snapshot
    # must preserve per-account detail or account isolation becomes impossible.
    snapshot(AAPL_SUMMARY, AAPL_SUMMARY.replace("U1,", "U2,"))
    data, _ = _load()
    assert set(data) == {"U1:12345", "U2:12345"}
    assert data["U1:12345"]["Qty"] == 100.0
    assert data["U2:12345"]["account_id"] == "U2"


# --------------------------------------------------------------------------
# LOT rows → inception dates
# --------------------------------------------------------------------------
LOT = ("U1,LOT,AAPL,12345,100,150.0,160.0,1,5.0,0.92,STK,Apple Inc,NASDAQ,USD,,"
       "US0378331005,2026-07-30,{dates}")


def test_earliest_lot_date_becomes_the_inception_date(snapshot):
    snapshot(AAPL_SUMMARY,
             LOT.format(dates="2025-06-01"),
             LOT.format(dates="2025-01-15"))
    data, _ = _load()
    assert data["U1:12345"]["Date"] == pd.Timestamp("2025-01-15")


def test_semicolon_separated_lot_timestamps_take_the_first(snapshot):
    # IBKR packs multiple open timestamps into one cell.
    snapshot(AAPL_SUMMARY, LOT.format(dates="2025-01-15;2025-02-01;2025-03-01"))
    data, _ = _load()
    assert data["U1:12345"]["Date"] == pd.Timestamp("2025-01-15")


def test_no_lot_rows_leaves_the_date_unset(snapshot):
    # The live Flex query returns SUMMARY only, so this is the normal case today:
    # inception falls back to the ledger's own reset-on-zero date downstream.
    snapshot(AAPL_SUMMARY)
    data, _ = _load()
    assert data["U1:12345"]["Date"] is None


def test_blank_conid_silently_drops_every_lot_date_known_defect(snapshot):
    """PINS A REAL DEFECT — currently latent, deliberately not fixed here.

    LOT dates are looked up by `earliest_dates.get(conid_str)`, where the lot keys
    come from `lots['Conid'].astype(str)` and `conid_str` from
    `str(int(float(conid)))`. Those agree only while pandas reads Conid as int.
    One blank Conid anywhere in the file — a totals row, a trailer — flips the
    whole column to float64, so the lot keys become "12345.0" while the lookup asks
    for "12345". Every inception date is then silently lost.

    Not firing on the current live file: that Flex query returns no LOT rows at
    all, and its repeated header rows make Conid a str column. It would fire the
    moment lot detail is enabled in the query. Fixing it is a one-line
    normalisation and belongs in its own commit.
    """
    snapshot(AAPL_SUMMARY,
             LOT.format(dates="2025-01-15"),
             "U1,TOTAL,,,0,0,0,1,0,1,,,,,,,2026-07-30,")   # blank Conid
    data, _ = _load()
    assert data["U1:12345"]["Date"] is None      # the date was found, then lost


# --------------------------------------------------------------------------
# clean_trade_data — the ledger-side half of the boundary
# --------------------------------------------------------------------------
def _trades_df(**over):
    row = {
        "TradeDate": "2025-01-15", "Symbol": "AAPL", "Buy/Sell": "BUY",
        "Quantity": 100.0, "Price": 150.0, "Conid": "12345", "Multiplier": 1.0,
    }
    row.update(over)
    return pd.DataFrame([row])


def test_clean_trade_data_normalises_conids():
    # A conid arriving as a float string must key identically to an int one, or
    # the same asset splits into two positions in the ledger replay.
    out = DataLoader.clean_trade_data(_trades_df(Conid="12345.0"))
    assert out["Conid"].iloc[0] == "12345"


def test_clean_trade_data_falls_back_to_symbol_when_conid_is_missing():
    out = DataLoader.clean_trade_data(_trades_df(Conid=None))
    assert out["Conid"].iloc[0] == "AAPL"


def test_clean_trade_data_rejects_unknown_sides():
    out = DataLoader.clean_trade_data(_trades_df(**{"Buy/Sell": "DIVIDEND"}))
    assert out.empty


@pytest.mark.parametrize("side", ["BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT", "SPLIT"])
def test_clean_trade_data_accepts_every_ledger_side(side):
    out = DataLoader.clean_trade_data(_trades_df(**{"Buy/Sell": side}))
    assert len(out) == 1


def test_clean_trade_data_keeps_zero_priced_splits_but_drops_priceless_trades():
    # A SPLIT legitimately has no price; a BUY without one is unusable.
    assert len(DataLoader.clean_trade_data(_trades_df(**{"Buy/Sell": "SPLIT", "Price": None}))) == 1
    assert DataLoader.clean_trade_data(_trades_df(Price=None)).empty


def test_clean_trade_data_drops_rows_without_a_date_or_quantity():
    assert DataLoader.clean_trade_data(_trades_df(TradeDate=None)).empty
    assert DataLoader.clean_trade_data(_trades_df(Quantity=None)).empty


def test_clean_trade_data_corrects_a_zero_multiplier():
    out = DataLoader.clean_trade_data(_trades_df(Multiplier=0))
    assert out["Multiplier"].iloc[0] == 1.0


def test_clean_trade_data_sorts_chronologically():
    df = pd.concat([_trades_df(TradeDate="2025-03-01"), _trades_df(TradeDate="2025-01-01")])
    out = DataLoader.clean_trade_data(df)
    assert list(out["TradeDate"]) == sorted(out["TradeDate"])


def test_clean_trade_data_handles_an_empty_frame():
    assert DataLoader.clean_trade_data(pd.DataFrame()).empty
