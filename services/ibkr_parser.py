import pandas as pd
from pathlib import Path
from datetime import datetime
import db
from logger import logger
from core.asset_registry import AssetRegistry

class IBKRParser:
    """
    Handles interpreting IBKR-specific file formats (CSV and XML).
    Separates the 'Knowledge of Columns' from the 'Networking' layer.
    """

    # --- Private Helpers ---

    @staticmethod
    def _load_csv(file_path, filter_symbol=True, execution_only=False):
        """Reads a Flex CSV, strips headers, and applies standard row filters."""
        df = pd.read_csv(file_path, low_memory=False, on_bad_lines='skip')
        df.columns = df.columns.str.strip()
        if filter_symbol and 'Symbol' in df.columns:
            df = df[df['Symbol'] != 'Symbol'].dropna(subset=['Symbol'])
        if execution_only and 'LevelOfDetail' in df.columns:
            df = df[df['LevelOfDetail'] == 'EXECUTION']
        return df

    @staticmethod
    def _normalize_conid(conid_raw, ticker):
        """Parses raw conid value; falls back to ticker with a warning if missing."""
        try:
            conid = str(int(float(str(conid_raw)))) if pd.notna(conid_raw) else ''
        except Exception:
            conid = str(conid_raw)
        if not conid or conid == 'nan':
            logger.warning(f"Missing conid for {ticker} — using ticker as fallback")
            conid = ticker
        return conid

    @staticmethod
    def _update_asset_master(row, conid, ticker, asset_cat, multiplier=None):
        """Upserts a row into the ticker_info Asset Master."""
        db.save_ticker_info(
            conid=conid,
            ticker_ibkr=ticker,
            isin=str(row.get('ISIN', '')),
            asset_class=asset_cat,
            multiplier=multiplier,
            description=row.get('Description', ticker),
            listing_exchange=str(row.get('ListingExchange', '')),
            currency=str(row.get('CurrencyPrimary', '')),
            underlying_symbol=str(row.get('UnderlyingSymbol', ''))
        )

    @staticmethod
    def parse_confirmations_csv(file_path):
        """Parses real-time Trade Confirmations and replaces matching manual entries."""
        if not file_path or not Path(file_path).exists():
            return 0

        try:
            df = IBKRParser._load_csv(file_path, filter_symbol=True, execution_only=True)
            count = 0
            for _, row in df.iterrows():
                ticker = str(row.get('Symbol', '')).upper()
                side = str(row.get('Buy/Sell', '')).upper()
                date_val = str(row.get('TradeDate', ''))
                qty = abs(float(row.get('Quantity', 0)))

                if not ticker or side not in ['BUY', 'SELL'] or qty == 0:
                    continue

                try:
                    date_normalized = pd.to_datetime(date_val).strftime("%Y-%m-%d")
                    price = float(row.get('Price', row.get('TradePrice', 0)))
                    multiplier = float(row.get('Multiplier', 1.0))
                    asset_cat = str(row.get('AssetClass', 'STK')).upper()
                    account_id = str(row.get('ClientAccountID', row.get('AccountId', 'U0000000')))
                    qty, multiplier = AssetRegistry.standardize_asset_quantity_and_multiplier(asset_cat, qty, multiplier)
                except Exception as e:
                    logger.warning(f"Skipping confirmation row for {ticker}: {e}")
                    continue

                conid = IBKRParser._normalize_conid(row.get('Conid'), ticker)
                IBKRParser._update_asset_master(row, conid, ticker, asset_cat, multiplier)

                ib_id = row.get('TradeID') or row.get('ExecID')
                ext_id = str(ib_id) if ib_id else f"CONF-{date_normalized}-{ticker}-{qty}"

                if not db.trade_exists(ext_id):
                    db.add_trade(
                        date=date_normalized, ticker=ticker, side=side,
                        quantity=qty, price=price, conid=conid,
                        account_id=account_id, multiplier=multiplier,
                        notes=f"IBKR CONFIRMATION {datetime.now().date()}",
                        source="IBKR_CONFIRMATION", external_id=ext_id
                    )
                    count += 1
            return count
        except Exception as e:
            logger.error(f"IBKR CONFIRMATION Parsing Error: {e}")
            return 0

    @staticmethod
    def parse_trade_csv(file_path):
        """Parses an IBKR Trade Confirmation CSV and saves results to DB."""
        if not file_path or not Path(file_path).exists():
            return 0

        try:
            df = IBKRParser._load_csv(file_path, filter_symbol=True, execution_only=True)
            count = 0
            for _, row in df.iterrows():
                ticker = row.get('Symbol')
                side = str(row.get('Buy/Sell', '')).upper()
                date_raw = str(row.get('TradeDate', '')).replace('-', '')

                if not ticker or side not in ['BUY', 'SELL']:
                    continue

                try:
                    date_str = pd.to_datetime(date_raw).strftime("%Y-%m-%d")
                    qty = abs(float(row.get('Quantity', 0)))
                    price = float(row.get('TradePrice', 0))
                    multiplier = float(row.get('Multiplier', 1.0))
                    asset_cat = str(row.get('AssetClass', 'STK')).upper()
                    account_id = str(row.get('ClientAccountID', row.get('AccountId', 'U0000000')))
                    qty, multiplier = AssetRegistry.standardize_asset_quantity_and_multiplier(asset_cat, qty, multiplier)

                    conid = IBKRParser._normalize_conid(row.get('Conid'), ticker)
                    IBKRParser._update_asset_master(row, conid, ticker, asset_cat, multiplier)

                    ib_id = row.get('IBOrderID') or row.get('TradeID')
                    ext_id = str(ib_id) if ib_id else f"TRD-{date_str}-{ticker}-{price}-{qty}"

                    if db.trade_exists(ext_id):
                        continue

                    db.add_trade(
                        date=date_str, ticker=ticker, side=side,
                        quantity=qty, price=price, conid=conid,
                        account_id=account_id, multiplier=multiplier,
                        notes=f"IBKR TRADES Import {datetime.now().date()}",
                        source="IBKR_TRADES_CSV", external_id=ext_id
                    )
                    count += 1
                except Exception as e:
                    logger.warning(f"Skipping trade row for {ticker}: {e}")
                    continue
            return count
        except Exception as e:
            logger.error(f"IBKR TRADES CSV Parsing Error: {e}")
            return 0

    @staticmethod
    def parse_transfers_csv(file_path):
        """Parses an IBKR Transfers CSV and saves INTERCOMPANY moves to DB."""
        if not file_path or not Path(file_path).exists():
            return 0

        try:
            df = IBKRParser._load_csv(file_path, filter_symbol=True, execution_only=False)
            if 'Type' in df.columns:
                df = df[df['Type'].isin(['INTERCOMPANY', 'INTERNAL', 'ADJUSTMENT'])]

            count = 0
            for _, row in df.iterrows():
                ticker = row.get('Symbol')
                direction = str(row.get('Direction', '')).upper()

                if not ticker or direction not in ['IN', 'OUT']:
                    continue

                try:
                    date_str = pd.to_datetime(row.get('Date')).strftime("%Y-%m-%d")
                    qty = abs(float(row.get('Quantity', 0)))
                    multiplier = float(row.get('Multiplier', 1.0))
                    asset_cat = str(row.get('AssetClass', 'STK')).upper()
                    account_id = str(row.get('ClientAccountID', row.get('AccountId', 'U0000000')))

                    pos_amt = abs(float(row.get('PositionAmount', 0)))
                    price = (pos_amt / qty) / multiplier if (qty * multiplier) > 0 else 0.0

                    # Bond/Bill Scaling: IBKR reports Face Value; convert to $1000-par shares and Points
                    if asset_cat in ['BOND', 'BILL', 'FIXED']:
                        qty = qty / 1000.0
                        if multiplier == 1.0:
                            multiplier = 10.0
                        price = price * 100.0

                    conid = IBKRParser._normalize_conid(row.get('Conid'), ticker)
                    IBKRParser._update_asset_master(row, conid, ticker, asset_cat, multiplier)

                    side = 'TRANSFER_IN' if direction == 'IN' else 'TRANSFER_OUT'
                    raw_id = row.get('TransactionID')
                    ext_id = f"{raw_id}-{account_id}-{side}" if raw_id else f"XFER-{date_str}-{ticker}-{qty}-{account_id}-{side}"

                    if not db.trade_exists(ext_id):
                        db.add_trade(
                            date=date_str, ticker=ticker, side=side,
                            quantity=qty, price=price, conid=conid,
                            account_id=account_id, multiplier=multiplier,
                            notes=f"IBKR TRANSFER Import ({row.get('Type')})",
                            source="IBKR_TRANSFER_CSV", external_id=ext_id
                        )
                        count += 1
                except Exception as e:
                    logger.warning(f"Skipping transfer row for {ticker}: {e}")
                    continue
            return count
        except Exception as e:
            logger.error(f"IBKR TRANSFER CSV Parsing Error: {e}")
            return 0

    @staticmethod
    def parse_corporate_actions_csv(file_path):
        """Parses IBKR Corporate Actions (Splits, etc.) CSV."""
        if not file_path or not Path(file_path).exists():
            return 0

        try:
            df = IBKRParser._load_csv(file_path, filter_symbol=True, execution_only=False)
            count = 0
            for _, row in df.iterrows():
                ticker = row.get('Symbol')
                if not ticker or str(ticker) == '-':
                    continue

                action_desc = str(row.get('ActionDescription', row.get('Type', ''))).upper()
                if 'SPLIT' not in action_desc:
                    continue

                try:
                    raw_date = row.get('Report Date', row.get('Date'))
                    date_str = pd.to_datetime(raw_date).strftime("%Y-%m-%d")
                    qty = float(row.get('Quantity', 0))
                    account_id = str(row.get('ClientAccountID', row.get('AccountId', 'U0000000')))

                    if qty == 0 or account_id == '-':
                        continue

                    conid = IBKRParser._normalize_conid(row.get('Conid'), ticker)
                    asset_cat = str(row.get('AssetClass', 'STK')).upper()
                    IBKRParser._update_asset_master(row, conid, ticker, asset_cat)

                    raw_id = row.get('TransactionID')
                    ext_id = f"{raw_id}-{account_id}" if raw_id else f"CORP-{date_str}-{ticker}-{qty}-{account_id}"

                    if not db.trade_exists(ext_id):
                        db.add_trade(
                            date=date_str, ticker=ticker, side='SPLIT',
                            quantity=qty, price=0.0, conid=conid,
                            account_id=account_id, multiplier=1.0,
                            notes=f"IBKR CORP ACTION: {action_desc[:100]}",
                            source="IBKR_CORP_CSV", external_id=ext_id
                        )
                        count += 1
                except Exception:
                    continue
            return count
        except Exception as e:
            logger.error(f"IBKR CORP ACTION CSV Parsing Error: {e}")
            return 0

    @staticmethod
    def parse_nav_csv(file_path):
        """
        Parses an IBKR Equity Summary CSV and returns (total_nav, currency, account_list, report_date).
        Supports both Flex sections and flat CSVs with repeated headers.
        """
        if not file_path or not Path(file_path).exists():
            return 0.0, "???", [], "Unknown"

        try:
            # Load CSV - do not skip rows, handle repeated headers manually
            df = pd.read_csv(file_path, low_memory=False, on_bad_lines='skip')
            df.columns = df.columns.str.strip()
            
            # Clean repeated headers
            if 'Total' in df.columns:
                df = df[df['Total'].astype(str) != 'Total']
            
            # Find Equity Summary rows
            # 1. Check SectionName column if it exists
            section_col = next((c for c in df.columns if 'SectionName' in c), None)
            
            if section_col:
                nav_rows = df[df[section_col].str.contains('EquitySummary', na=False, case=False)]
            else:
                # 2. If no SectionName, use rows that have both 'Total' and 'ReportDate'
                nav_rows = df.dropna(subset=['Total', 'ReportDate'], how='any')
            
            if nav_rows.empty:
                logger.warning(f"No NAV data found in {file_path}")
                return 0.0, "???", [], "Unknown"

            # Ensure numeric
            nav_rows = nav_rows.copy()
            nav_rows['Total'] = pd.to_numeric(nav_rows['Total'], errors='coerce')
            nav_rows = nav_rows.dropna(subset=['Total'])
            
            total_nav = nav_rows['Total'].sum()
            
            # Extract Currency and ReportDate
            nav_ccy = "???"
            if 'CurrencyPrimary' in nav_rows.columns:
                valid_ccy = nav_rows['CurrencyPrimary'].dropna()
                if not valid_ccy.empty:
                    nav_ccy = str(valid_ccy.iloc[0])

            report_date = "Unknown"
            if 'ReportDate' in nav_rows.columns:
                valid_dates = nav_rows['ReportDate'].dropna()
                if not valid_dates.empty:
                    report_date = str(valid_dates.iloc[0])
            
            accounts = []
            # Map accounts using standard IBKR columns
            acct_col = next((c for c in ['AccountId', 'Account Alias', 'ClientAccountID'] if c in nav_rows.columns), None)
            
            if acct_col:
                for _, row in nav_rows.iterrows():
                    accounts.append({
                        'alias': row[acct_col],
                        'nav': float(row.get('Total', 0))
                    })
            
            logger.info(f"Parsed NAV: {total_nav:,.2f} {nav_ccy} for date {report_date} from {len(accounts)} accounts.")
            return total_nav, nav_ccy, accounts, report_date
        except Exception as e:
            logger.error(f"ERROR: IBKR NAV CSV Parsing Error: {e}")
            return 0.0, "???", [], "Unknown"
