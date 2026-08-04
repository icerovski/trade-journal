"""IBKR → Yahoo symbol resolution (`services/ticker_mapper.py`).

The other half of the ingestion boundary, and the one with the widest branch count
in the repo (36) and — until now — no tests. Everything price-derived depends on
it: get the symbol wrong and the ATR, the 200-DMA, the volume profile and the
trailing high-water mark are all computed against the wrong instrument, with no
error anywhere. A mis-resolution does not fail loudly; it quietly prices the wrong
company.

Every test here is offline. `search_online_ticker` is patched in all of them —
partly because tests must not hit the network, and partly because *when* the
network is consulted is itself a behaviour worth pinning: a resolution that
already has an answer must not make an HTTP call in a per-position loop.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from services.ticker_mapper import TickerMapper


@pytest.fixture(autouse=True)
def _isolated_mapper():
    """`resolve_yf_ticker` is lru_cached and `_positions_df` is a class attribute
    lazily loaded from the real broker CSV, so without this every test would leak
    into the next AND read the user's live data hub.
    """
    TickerMapper.resolve_yf_ticker.cache_clear()
    TickerMapper._positions_df = pd.DataFrame()      # hermetic: no disk, no hub
    yield
    TickerMapper.resolve_yf_ticker.cache_clear()
    TickerMapper._positions_df = None


def _positions_csv(*symbols, conid=12345):
    """Seed the cached open-positions frame with controlled rows."""
    TickerMapper._positions_df = pd.DataFrame([
        {"Symbol": s, "Symbol_Upper": s.upper(), "Conid": conid + i, "ISIN": "",
         "AssetClass": "STK", "ListingExchange": "NYSE", "CurrencyPrimary": "USD",
         "UnderlyingSymbol": ""}
        for i, s in enumerate(symbols)
    ])


@pytest.fixture
def mock_db():
    with patch("services.ticker_mapper.db", MagicMock()) as m:
        m.get_ticker_info.return_value = None
        m.get_yf_ticker.return_value = None
        m.get_asset_details_from_trades.return_value = None
        yield m


@pytest.fixture
def no_network():
    """Patched search — asserts on call count as well as return value."""
    with patch.object(TickerMapper, "search_online_ticker", return_value=None) as s:
        yield s


def _info(ticker_yfinance="AAPL", isin="US037", asset_class="STK"):
    """A ticker_info row (sqlite3.Row behaves like a mapping)."""
    return {"ticker_yfinance": ticker_yfinance, "isin": isin, "asset_class": asset_class}


# --------------------------------------------------------------------------
# Resolution priority
# --------------------------------------------------------------------------
def test_complete_asset_master_row_wins_without_touching_the_network(mock_db, no_network):
    # The hot path: this runs once per position on every dashboard refresh.
    mock_db.get_ticker_info.return_value = _info("AAPL.DE", "DE0005", "STK")
    assert TickerMapper.resolve_yf_ticker("AAPL", conid="12345") == "AAPL.DE"
    no_network.assert_not_called()


def test_ticker_lookup_is_the_fallback_when_no_conid_is_known(mock_db, no_network):
    mock_db.get_yf_ticker.return_value = "MSFT"
    assert TickerMapper.resolve_yf_ticker("MSFT") == "MSFT"


def test_online_search_resolves_from_an_isin(mock_db):
    with patch.object(TickerMapper, "search_online_ticker", return_value="SXR8.DE") as s:
        assert TickerMapper.resolve_yf_ticker("IUSA", isin="IE00B5BMR087") == "SXR8.DE"
        s.assert_called_once_with("IE00B5BMR087")


def test_stored_symbol_is_used_when_the_search_finds_nothing(mock_db, no_network):
    # Row has a symbol but no ISIN, so the early return does not fire; the search
    # is attempted, fails, and the stored value must still win over a heuristic.
    mock_db.get_ticker_info.return_value = _info("BRK-B", isin=None)
    assert TickerMapper.resolve_yf_ticker("BRK B", conid="12345") == "BRK-B"


def test_a_resolved_symbol_is_persisted_to_the_asset_master(mock_db, no_network):
    TickerMapper.resolve_yf_ticker("AAPL", conid="12345", asset="STK", ccy="USD")
    assert mock_db.save_ticker_info.called
    kwargs = mock_db.save_ticker_info.call_args.kwargs
    assert kwargs["conid"] == "12345" and kwargs["ticker_yfinance"] == "AAPL"


def test_nothing_is_persisted_without_a_conid(mock_db, no_network):
    # conid is the asset master's primary key — writing without one would create
    # an unjoinable row.
    TickerMapper.resolve_yf_ticker("AAPL", asset="STK", ccy="USD")
    mock_db.save_ticker_info.assert_not_called()


def test_missing_details_are_filled_from_the_trades_table(mock_db):
    mock_db.get_asset_details_from_trades.return_value = {
        "isin": "US037", "asset_category": "STK", "listing_exchange": "NASDAQ",
        "currency": "USD", "underlying_symbol": "",
    }
    with patch.object(TickerMapper, "search_online_ticker", return_value="AAPL") as s:
        assert TickerMapper.resolve_yf_ticker("AAPL", conid="12345") == "AAPL"
        s.assert_called_once_with("US037")      # ISIN recovered from the ledger


# --------------------------------------------------------------------------
# Heuristics — exchange suffixes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("exchange,expected", [
    ("IBIS", "SAP.DE"),      # Xetra
    ("IBIS2", "SAP.DE"),     # substring match is deliberate
    ("LSE", "SAP.L"),
    ("AEB", "SAP.AS"),
])
def test_exchange_suffixes(mock_db, no_network, exchange, expected):
    got = TickerMapper.resolve_yf_ticker("SAP", asset="STK", exchange=exchange, ccy="EUR")
    assert got == expected


def test_xetra_prefers_the_underlying_symbol(mock_db, no_network):
    # On IBIS the IBKR symbol is often a local code; the underlying is the one
    # Yahoo actually lists.
    got = TickerMapper.resolve_yf_ticker("XYZ", asset="STK", exchange="IBIS",
                                         ccy="EUR", underlying="SAP")
    assert got == "SAP.DE"


def test_xetra_ignores_a_nan_underlying(mock_db, no_network):
    # CSV-sourced fields arrive as the literal string 'nan'.
    got = TickerMapper.resolve_yf_ticker("SAP", asset="STK", exchange="IBIS",
                                         ccy="EUR", underlying="nan")
    assert got == "SAP.DE"


def test_currency_suffix_when_no_exchange_matches(mock_db, no_network):
    got = TickerMapper.resolve_yf_ticker("SAP", asset="STK", exchange="UNKNOWN", ccy="EUR")
    assert got == "SAP.DE"


# --------------------------------------------------------------------------
# Heuristics — US symbol normalisation
# --------------------------------------------------------------------------
@pytest.mark.parametrize("ibkr,expected", [
    ("BRK B", "BRK-B"),        # space → dash
    ("BF.B", "BF-B"),          # dot → dash
    ("AAPL", "AAPL"),          # already clean
])
def test_us_symbol_normalisation(mock_db, no_network, ibkr, expected):
    assert TickerMapper.resolve_yf_ticker(ibkr, asset="STK", ccy="USD") == expected


@pytest.mark.parametrize("ibkr,expected", [
    ("BAC PR L", "BAC-PL"),
    ("BAC PRL", "BAC-PL"),
])
def test_preferred_share_notation(mock_db, no_network, ibkr, expected):
    assert TickerMapper.resolve_yf_ticker(ibkr, asset="STK", ccy="USD") == expected


# --------------------------------------------------------------------------
# Heuristics — asset-class rules
# --------------------------------------------------------------------------
def test_crypto_gets_a_usd_pair_suffix(mock_db, no_network):
    assert TickerMapper.resolve_yf_ticker("BTC", asset="CRYPTO") == "BTC-USD"


def test_options_have_their_spaces_stripped(mock_db, no_network):
    assert TickerMapper.resolve_yf_ticker("AAPL  240119C00150000", asset="OPT") \
        == "AAPL240119C00150000"


def test_an_unhandled_asset_class_passes_through_unchanged(mock_db, no_network):
    # A bond/future has no Yahoo convention here; returning the symbol unchanged
    # is the honest fallback (the price fetch will simply find nothing).
    assert TickerMapper.resolve_yf_ticker("GOVT", asset="BOND", ccy="USD") == "GOVT"


def test_asset_class_defaults_to_equity_when_absent(mock_db, no_network):
    assert TickerMapper.resolve_yf_ticker("BRK B", ccy="USD") == "BRK-B"


# --------------------------------------------------------------------------
# Online search
# --------------------------------------------------------------------------
def test_search_returns_the_first_quote_symbol():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"quotes": [{"symbol": "SXR8.DE"}, {"symbol": "SXR8.L"}]}
    with patch("services.ticker_mapper.requests.get", return_value=resp):
        assert TickerMapper.search_online_ticker("IE00B5BMR087") == "SXR8.DE"


@pytest.mark.parametrize("isin", [None, "", float("nan")])
def test_search_skips_a_missing_isin(isin):
    with patch("services.ticker_mapper.requests.get") as g:
        assert TickerMapper.search_online_ticker(isin) is None
        g.assert_not_called()


def test_search_swallows_a_network_failure():
    # A Yahoo outage must degrade to the heuristics, never propagate.
    with patch("services.ticker_mapper.requests.get", side_effect=OSError("no route")):
        assert TickerMapper.search_online_ticker("IE00B5BMR087") is None


def test_search_ignores_a_non_200_response():
    with patch("services.ticker_mapper.requests.get", return_value=MagicMock(status_code=429)):
        assert TickerMapper.search_online_ticker("IE00B5BMR087") is None


def test_search_handles_an_empty_quote_list():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"quotes": []}
    with patch("services.ticker_mapper.requests.get", return_value=resp):
        assert TickerMapper.search_online_ticker("IE00B5BMR087") is None


# --------------------------------------------------------------------------
# The cached open-positions CSV as a detail source
# --------------------------------------------------------------------------
def test_details_are_filled_from_the_cached_positions_csv(mock_db):
    _positions_csv("IUSA")
    TickerMapper._positions_df.loc[0, "ISIN"] = "IE00B5BMR087"
    with patch.object(TickerMapper, "search_online_ticker", return_value="SXR8.DE") as s:
        assert TickerMapper.resolve_yf_ticker("IUSA") == "SXR8.DE"
        s.assert_called_once_with("IE00B5BMR087")


def test_resolving_a_held_symbol_without_a_conid_succeeds(mock_db, no_network):
    """Regression guard for an UnboundLocalError fixed 2026-08-04.

    `info` was assigned only inside `if conid:` at the top, but a symbol matched in
    the cached positions CSV ASSIGNS `conid` further down — so the later
    `if conid and info:` guard stopped short-circuiting and read an unbound name.

    Trigger: resolve WITHOUT a conid for a symbol already held — the
    prospect/discovery path (`fetch_atr_data(None, ticker=…)` →
    `get_atr_discovery_data(conid=None)`). `get_atr_discovery_data` swallows
    exceptions, so discovery silently returned nothing. The live broker CSV holds
    'BRK B', 'FOUR PRA' and an IWM option — the symbols that reach this path.
    """
    _positions_csv("BRK B")
    assert TickerMapper.resolve_yf_ticker("BRK B", asset="STK", ccy="USD") == "BRK-B"


def test_a_conid_discovered_from_the_csv_is_used_to_persist_the_mapping(mock_db, no_network):
    # The reassignment that caused the bug has a purpose: it lets a symbol resolved
    # without a conid still be written to the asset master under the right key.
    _positions_csv("BRK B", conid=777)
    TickerMapper.resolve_yf_ticker("BRK B", asset="STK", ccy="USD")
    assert mock_db.save_ticker_info.call_args.kwargs["conid"] == 777


def test_the_same_symbol_resolves_identically_with_a_conid_supplied(mock_db, no_network):
    _positions_csv("BRK B")
    assert TickerMapper.resolve_yf_ticker("BRK B", asset="STK", ccy="USD",
                                          conid="12345") == "BRK-B"


@pytest.mark.parametrize("symbol,expected", [
    ("BRK B", "BRK-B"),
    ("FOUR PRA", "FOUR-PA"),
])
def test_every_space_containing_symbol_in_the_live_book_resolves(mock_db, no_network, symbol, expected):
    # The exact symbols that triggered the defect in production data.
    _positions_csv(symbol)
    assert TickerMapper.resolve_yf_ticker(symbol, asset="STK", ccy="USD") == expected


# --------------------------------------------------------------------------
# Caching
# --------------------------------------------------------------------------
def test_repeat_resolution_is_served_from_cache(mock_db, no_network):
    mock_db.get_ticker_info.return_value = _info("AAPL", "US037", "STK")
    for _ in range(5):
        TickerMapper.resolve_yf_ticker("AAPL", conid="12345")
    assert mock_db.get_ticker_info.call_count == 1      # one DB read, not five


def test_cache_is_keyed_on_every_argument(mock_db, no_network):
    mock_db.get_ticker_info.side_effect = [_info("AAPL", "US037"), _info("MSFT", "US594")]
    assert TickerMapper.resolve_yf_ticker("AAPL", conid="1") == "AAPL"
    assert TickerMapper.resolve_yf_ticker("MSFT", conid="2") == "MSFT"


def test_cache_does_not_observe_a_later_asset_master_correction(mock_db, no_network):
    """Pins a caching consequence rather than a bug.

    `resolve_yf_ticker` is `lru_cache`d for the process lifetime, so correcting a
    wrong `ticker_yfinance` in the database does NOT take effect until the app is
    restarted. That is the right trade for a per-position hot path, but it means a
    mis-resolution cannot be repaired from inside a running session — worth knowing
    before debugging one.
    """
    mock_db.get_ticker_info.return_value = _info("WRONG", "US037")
    assert TickerMapper.resolve_yf_ticker("AAPL", conid="12345") == "WRONG"

    mock_db.get_ticker_info.return_value = _info("RIGHT", "US037")
    assert TickerMapper.resolve_yf_ticker("AAPL", conid="12345") == "WRONG"   # stale

    TickerMapper.resolve_yf_ticker.cache_clear()
    assert TickerMapper.resolve_yf_ticker("AAPL", conid="12345") == "RIGHT"


# --------------------------------------------------------------------------
# Degenerate input
# --------------------------------------------------------------------------
def test_nan_string_details_are_treated_as_absent(mock_db, no_network):
    # Details sourced from a CSV arrive as 'nan'/'None' strings; treating those as
    # real values would produce symbols like "AAPL.nan".
    got = TickerMapper.resolve_yf_ticker("AAPL", isin="nan", asset="STK",
                                         exchange="None", ccy="USD")
    assert got == "AAPL"


def test_lowercase_input_is_upper_cased_for_lookups(mock_db, no_network):
    mock_db.get_yf_ticker.return_value = "MSFT"
    TickerMapper.resolve_yf_ticker("msft")
    mock_db.get_yf_ticker.assert_called_with("MSFT")
