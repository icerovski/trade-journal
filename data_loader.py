import pandas as pd
import numpy as np
from typing import List
from config import DATA_DIR
import db
from models import Trade
from logger import logger, log_system_milestone

# Log the recent improvement
log_system_milestone("Implemented centralized DataLoader for DB and CSV snapshots")

class DataLoader:
    """
    Centralized data loader for DB and CSV sources.
    Handles cleaning and standardizing column names, prioritizing Conid for identity.
    """
    
    @staticmethod
    def get_connection():
        """Helper to allow patching in tests."""
        return db.get_conn()

    @staticmethod
    def load_trades_from_db() -> pd.DataFrame:
        """
        Loads all trades from the SQLite database as a cleaned DataFrame.
        """
        conn = DataLoader.get_connection()
        df = pd.read_sql_query("SELECT * FROM trades", conn)
        conn.close()
        
        rename_map = {
            'date': 'TradeDate', 'ticker': 'Symbol', 'side': 'Buy/Sell',
            'quantity': 'Quantity', 'price': 'Price', 'multiplier': 'Multiplier',
            'asset_category': 'AssetClass', 'description': 'Description', 
            'conid': 'Conid', 'listing_exchange': 'ListingExchange',
            'currency': 'CurrencyPrimary', 'underlying_symbol': 'UnderlyingSymbol'
        }
        df = df.rename(columns=rename_map)
        return DataLoader.clean_trade_data(df)

    @classmethod
    def get_trades_as_models(cls) -> List[Trade]:
        """
        Loads trades from DB and returns them as a list of Trade dataclass objects.
        """
        df = cls.load_trades_from_db()
        trades = []
        for _, row in df.iterrows():
            trades.append(Trade(
                date=row['TradeDate'].strftime('%Y-%m-%d %H:%M:%S') if pd.notna(row['TradeDate']) else "",
                ticker=row['Symbol'],
                side=row['Buy/Sell'],
                quantity=row['Quantity'],
                price=row['Price'],
                conid=str(row['Conid']),
                multiplier=row.get('Multiplier', 1.0),
                description=row.get('Description', ''),
                asset_category=row.get('AssetClass', 'STK'),
                listing_exchange=row.get('ListingExchange', ''),
                currency=row.get('CurrencyPrimary', 'USD'),
                underlying_symbol=row.get('UnderlyingSymbol', ''),
                source=row.get('source', 'MANUAL'),
                external_id=str(row.get('external_id', '')) if pd.notna(row.get('external_id')) else None,
                notes=row.get('notes', '')
            ))
        return trades

    @staticmethod
    def clean_trade_data(df):
        """Standardizes types and sorting."""
        if df.empty:
            return df
        
        df = df.copy()
        df.columns = df.columns.str.strip()
        df['TradeDate'] = pd.to_datetime(df['TradeDate'], errors='coerce')
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
        df['Price'] = pd.to_numeric(df['Price'], errors='coerce')
        df['Multiplier'] = pd.to_numeric(df.get('Multiplier', 1.0), errors='coerce')
        df['Multiplier'] = df['Multiplier'].replace(0, np.nan).fillna(1.0)
        
        # Ensure critical columns exist
        for col in ['Conid', 'ListingExchange', 'CurrencyPrimary', 'UnderlyingSymbol']:
            if col not in df.columns:
                df[col] = np.nan
        
        # Priority: Conid is the unique identifier. Normalize to clean string integer.
        if 'Conid' in df.columns:
            def normalize_conid(val):
                try:
                    if pd.isna(val) or str(val).strip() == '' or str(val).strip() == 'nan': 
                        return np.nan
                    return str(int(float(str(val))))
                except:
                    return str(val).strip()
            
            df['Conid'] = df['Conid'].apply(normalize_conid)
            df['Conid'] = df['Conid'].fillna(df['Symbol']).astype(str)
            
        # For SPLITS, price is 0. For others, price must be valid.
        df['Buy/Sell'] = df['Buy/Sell'].str.strip().str.upper()
        allowed_sides = ['BUY', 'SELL', 'TRANSFER_IN', 'TRANSFER_OUT', 'SPLIT']
        df = df[df['Buy/Sell'].isin(allowed_sides)]
        
        # Keep rows with valid Date and Quantity. Price can be 0 for Splits.
        df = df.dropna(subset=['TradeDate', 'Quantity'])
        df = df[(df['Buy/Sell'] == 'SPLIT') | (df['Price'].notna())]
        
        return df.sort_values('TradeDate')

    @staticmethod
    def get_broker_verified_snapshot():
        """Reads open_positions_lbd.csv and returns aggregated summary using Conid."""
        from config import IBKR_OPEN_POSITIONS_CSV
        path = IBKR_OPEN_POSITIONS_CSV
        logger.info(f"Checking for snapshot at: {path}")
        if not path.exists():
            logger.warning(f"Snapshot file not found at: {path}")
            return {}, None
            
        try:
            # Load CSV - do NOT skip rows, we will handle repeated headers manually
            df = pd.read_csv(path, low_memory=False, on_bad_lines='skip')
            df.columns = df.columns.str.strip()
            
            # Robust header discovery: if 'LevelOfDetail' is not in columns, search for it in rows
            if 'LevelOfDetail' not in df.columns:
                for i in range(min(10, len(df))):
                    if "LevelOfDetail" in df.iloc[i].values:
                        df.columns = df.iloc[i].str.strip()
                        df = df.iloc[i+1:]
                        break
            
            if 'LevelOfDetail' not in df.columns:
                logger.error(f"Could not find 'LevelOfDetail' column in {path.name}")
                return {}, None

            # Filter out redundant header rows and empty symbols
            df = df[df['Symbol'] != 'Symbol'].dropna(subset=['Symbol'])
            
            df = df[df['LevelOfDetail'].isin(['SUMMARY', 'LOT'])]
            df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
            df['CostBasisPrice'] = pd.to_numeric(df['CostBasisPrice'], errors='coerce')
            df['MarkPrice'] = pd.to_numeric(df['MarkPrice'], errors='coerce')
            df['Multiplier'] = pd.to_numeric(df.get('Multiplier', 1.0), errors='coerce')
            df['Multiplier'] = df['Multiplier'].replace(0, np.nan).fillna(1.0)
            df['PercentOfNAV'] = pd.to_numeric(df['PercentOfNAV'], errors='coerce')
            
            summaries = df[df['LevelOfDetail'] == 'SUMMARY'].copy()
            if summaries.empty:
                logger.warning(f"No 'SUMMARY' rows found in {path.name}")
                return {}, None
                
            summaries = summaries.dropna(subset=['Quantity', 'Conid'])
            lots = df[df['LevelOfDetail'] == 'LOT'].copy()
            earliest_dates = {}
            if not lots.empty:
                # OpenDateTime often has multiple timestamps separated by semicolon
                lots['OpenDateClean'] = pd.to_datetime(lots['OpenDateTime'].astype(str).str.split(';').str[0], errors='coerce')
                earliest_dates = lots.groupby('Conid')['OpenDateClean'].min().to_dict()
            
            report_date_raw = summaries['ReportDate'].iloc[0]
            report_date = pd.to_datetime(report_date_raw, errors='coerce')
            broker_data = {}
            
            for conid_val, group in summaries.groupby('Conid'):
                try:
                    conid_str = str(int(float(str(conid_val))))
                except (ValueError, TypeError):
                    conid_str = str(conid_val)
                    
                qty = group['Quantity'].sum()
                asset_cat = str(group['AssetClass'].iloc[0]).upper()
                multiplier = group['Multiplier'].iloc[0]

                # Bond/Bill Scaling: IBKR reports Face Value, but we want 'Shares' ($1000 par)
                if asset_cat in ['BOND', 'BILL', 'FIXED']:
                    qty = qty / 1000.0
                    if multiplier == 1.0:
                        multiplier = 10.0

                if abs(qty) < 0.0000001: continue
                
                entry = group['CostBasisPrice'].iloc[0] if 'CostBasisPrice' in group.columns else 0
                isin_val = group['ISIN'].iloc[0] if 'ISIN' in group.columns else np.nan
                
                broker_data[conid_str] = {
                    'Qty': qty, 
                    'Entry': entry,
                    'Multiplier': multiplier,
                    'Date': earliest_dates.get(conid_val) or report_date,
                    'Description': group['Description'].iloc[0], 
                    'Symbol': group['Symbol'].iloc[0],
                    'AssetClass': asset_cat, 
                    'Currency': group['CurrencyPrimary'].iloc[0],
                    'ListingExchange': group['ListingExchange'].iloc[0], 
                    'UnderlyingSymbol': group['UnderlyingSymbol'].iloc[0],
                    'ISIN': isin_val, 
                    'MarkPrice': group['MarkPrice'].iloc[0],
                    'NavPct': group['PercentOfNAV'].sum()
                }
            
            logger.info(f"Successfully loaded {len(broker_data)} positions from {path.name}")
            return broker_data, report_date
        except Exception as e:
            logger.error(f"Error parsing open_positions.csv: {e}")
            return {}, None
