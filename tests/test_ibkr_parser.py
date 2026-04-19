import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from services.ibkr_parser import IBKRParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_csv(path, content: str):
    path.write_text(content.strip())


# ---------------------------------------------------------------------------
# parse_trade_csv
# ---------------------------------------------------------------------------

TRADE_HEADER = (
    "Symbol,Buy/Sell,TradeDate,Quantity,TradePrice,Multiplier,AssetClass,"
    "ClientAccountID,Conid,IBOrderID,LevelOfDetail,ISIN,ListingExchange,"
    "CurrencyPrimary,UnderlyingSymbol,Description"
)


@patch("services.ibkr_parser.db")
def test_parse_trade_csv_ingests_one_row(mock_db, tmp_path):
    mock_db.trade_exists.return_value = False
    f = tmp_path / "trades.csv"
    write_csv(f, f"""{TRADE_HEADER}
AAPL,BUY,20240115,100,150.0,1.0,STK,U0000001,12345,ORD001,EXECUTION,,NASDAQ,USD,,Apple""")

    count = IBKRParser.parse_trade_csv(str(f))

    assert count == 1
    mock_db.add_trade.assert_called_once()
    call_kwargs = mock_db.add_trade.call_args.kwargs
    assert call_kwargs["ticker"] == "AAPL"
    assert call_kwargs["side"] == "BUY"
    assert call_kwargs["quantity"] == 100.0
    assert call_kwargs["price"] == 150.0


@patch("services.ibkr_parser.db")
def test_parse_trade_csv_deduplicates(mock_db, tmp_path):
    """Row with an already-known external_id must not be ingested again."""
    mock_db.trade_exists.return_value = True  # already in DB
    f = tmp_path / "trades.csv"
    write_csv(f, f"""{TRADE_HEADER}
AAPL,BUY,20240115,100,150.0,1.0,STK,U0000001,12345,ORD001,EXECUTION,,NASDAQ,USD,,Apple""")

    count = IBKRParser.parse_trade_csv(str(f))

    assert count == 0
    mock_db.add_trade.assert_not_called()


@patch("services.ibkr_parser.db")
def test_parse_trade_csv_skips_non_execution_rows(mock_db, tmp_path):
    mock_db.trade_exists.return_value = False
    f = tmp_path / "trades.csv"
    write_csv(f, f"""{TRADE_HEADER}
AAPL,BUY,20240115,100,150.0,1.0,STK,U0000001,12345,ORD001,SUMMARY,,NASDAQ,USD,,Apple""")

    count = IBKRParser.parse_trade_csv(str(f))

    assert count == 0


@patch("services.ibkr_parser.db")
def test_parse_trade_csv_missing_file_returns_zero(mock_db):
    count = IBKRParser.parse_trade_csv("/does/not/exist.csv")
    assert count == 0


# ---------------------------------------------------------------------------
# parse_transfers_csv — bond point correction
# ---------------------------------------------------------------------------

TRANSFER_HEADER = (
    "Symbol,Direction,Date,Quantity,Multiplier,AssetClass,ClientAccountID,"
    "Conid,TransactionID,PositionAmount,ISIN,ListingExchange,CurrencyPrimary,"
    "UnderlyingSymbol,Description,Type"
)


@patch("services.ibkr_parser.db")
def test_parse_transfers_csv_bond_point_correction(mock_db, tmp_path):
    """
    IBKR transfer CSVs for bonds report quantity as face value (e.g. 100000)
    and PositionAmount as total dollar value. The parser must convert to:
      qty = face_value / 1000  (= number of $1000-par bonds)
      price = (PositionAmount / face_value) * 100  (= % of par in points)
    """
    mock_db.trade_exists.return_value = False
    f = tmp_path / "transfers.csv"
    # 100,000 face value bond, total value = 85,000 → price = 85% of par = 85.0
    write_csv(f, f"""{TRANSFER_HEADER}
GOVT,IN,2024-01-10,100000,1.0,BOND,U0000001,99999,TXN001,85000,,LSE,USD,,Govt Bond,INTERCOMPANY""")

    IBKRParser.parse_transfers_csv(str(f))

    call_kwargs = mock_db.add_trade.call_args.kwargs
    assert call_kwargs["quantity"] == pytest.approx(100.0)     # 100000 / 1000
    assert call_kwargs["price"] == pytest.approx(85.0)         # (85000/100000) * 100
    assert call_kwargs["multiplier"] == pytest.approx(10.0)    # bond multiplier applied


@patch("services.ibkr_parser.db")
def test_parse_transfers_csv_deduplicates(mock_db, tmp_path):
    mock_db.trade_exists.return_value = True
    f = tmp_path / "transfers.csv"
    write_csv(f, f"""{TRANSFER_HEADER}
AAPL,IN,2024-01-10,100,1.0,STK,U0000001,12345,TXN001,5000,,NASDAQ,USD,,Apple,INTERCOMPANY""")

    count = IBKRParser.parse_transfers_csv(str(f))
    assert count == 0


# ---------------------------------------------------------------------------
# parse_confirmations_csv
# ---------------------------------------------------------------------------

CONF_HEADER = (
    "Symbol,Buy/Sell,TradeDate,Quantity,Price,Multiplier,AssetClass,"
    "ClientAccountID,Conid,TradeID,LevelOfDetail,ISIN,ListingExchange,"
    "CurrencyPrimary,UnderlyingSymbol,Description"
)


@patch("services.ibkr_parser.db")
def test_parse_confirmations_csv_ingests_row(mock_db, tmp_path):
    mock_db.trade_exists.return_value = False
    f = tmp_path / "confirmations.csv"
    write_csv(f, f"""{CONF_HEADER}
MSFT,BUY,2024-01-15,50,400.0,1.0,STK,U0000001,67890,TRDID001,EXECUTION,,NASDAQ,USD,,Microsoft""")

    count = IBKRParser.parse_confirmations_csv(str(f))

    assert count == 1
    call_kwargs = mock_db.add_trade.call_args.kwargs
    assert call_kwargs["source"] == "IBKR_CONFIRMATION"
    assert call_kwargs["ticker"] == "MSFT"


@patch("services.ibkr_parser.db")
def test_parse_confirmations_csv_skips_non_execution(mock_db, tmp_path):
    mock_db.trade_exists.return_value = False
    f = tmp_path / "confirmations.csv"
    write_csv(f, f"""{CONF_HEADER}
MSFT,BUY,2024-01-15,50,400.0,1.0,STK,U0000001,67890,TRDID001,ORDER,,NASDAQ,USD,,Microsoft""")

    count = IBKRParser.parse_confirmations_csv(str(f))
    assert count == 0
