import pandas as pd
import numpy as np
from config import DATA_DIR
import db
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
    def load_trades_from_db():
        """
        Loads all trades from the SQLite database for complete ledger accuracy.
        """
        conn = DataLoader.get_connection()
        df = pd.read_sql_query("SELECT * FROM trades", conn)
        conn.close()
        
        rename_map = {
            'date': 'TradeDate', 'ticker': 'Symbol', 'side': 'Buy/Sell',
            'quantity': 'Quantity', 'price': 'Price', 'asset_category': 'AssetClass',
            'description': 'Description', 'conid': 'Conid', 'listing_exchange': 'ListingExchange',
            'currency': 'CurrencyPrimary', 'underlying_symbol': 'UnderlyingSymbol'
        }
        df = df.rename(columns=rename_map)
        return DataLoader.clean_trade_data(df)

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
        
        # Ensure critical columns exist
        for col in ['Conid', 'ListingExchange', 'CurrencyPrimary', 'UnderlyingSymbol']:
            if col not in df.columns:
                df[col] = np.nan
        
        # Priority: Conid is the unique identifier. Fallback to Symbol if missing.
        if 'Conid' in df.columns:
            df['Conid'] = df['Conid'].fillna(df['Symbol']).astype(str)
            
        df = df.dropna(subset=['TradeDate', 'Quantity', 'Price'])
        df = df[df['Buy/Sell'].isin(['BUY', 'SELL'])]
        return df.sort_values('TradeDate')

    @staticmethod
    def get_broker_verified_snapshot():
        """Reads open_positions.csv and returns aggregated summary using Conid."""
        path = DATA_DIR / "open_positions.csv"
        if not path.exists():
            return {}, None
            
        try:
            df = pd.read_csv(path, on_bad_lines='skip')
            df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
            df['CostBasisPrice'] = pd.to_numeric(df['CostBasisPrice'], errors='coerce')
            df['MarkPrice'] = pd.to_numeric(df['MarkPrice'], errors='coerce')
            df['PercentOfNAV'] = pd.to_numeric(df['PercentOfNAV'], errors='coerce')
            df = df.dropna(subset=['Quantity', 'CostBasisPrice', 'Conid'])
            
            # Extract earliest dates from LOT records
            lots = df[df['LevelOfDetail'] == 'LOT'].copy()
            lots['OpenDateClean'] = pd.to_datetime(lots['OpenDateTime'].str.split(';').str[0], errors='coerce')
            earliest_dates = lots.groupby('Conid')['OpenDateClean'].min().to_dict()
            
            # Process summaries
            summaries = df[df['LevelOfDetail'] == 'SUMMARY'].copy()
            if summaries.empty:
                return {}, None
                
            report_date = pd.to_datetime(summaries['ReportDate'].iloc[0], errors='coerce')
            broker_data = {}
            
            for conid, group in summaries.groupby('Conid'):
                conid_str = str(int(float(conid))) if str(conid).replace('.','').isdigit() else str(conid)
                qty = group['Quantity'].sum()
                total_cost_money = (group['CostBasisPrice'] * group['Quantity']).sum()
                
                broker_data[conid_str] = {
                    'Qty': qty, 
                    'Entry': total_cost_money / qty if abs(qty) > 0 else 0,
                    'Date': earliest_dates.get(conid) or report_date,
                    'Description': group['Description'].iloc[0], 
                    'Symbol': group['Symbol'].iloc[0],
                    'AssetClass': group['AssetClass'].iloc[0], 
                    'Currency': group['CurrencyPrimary'].iloc[0],
                    'ListingExchange': group['ListingExchange'].iloc[0], 
                    'UnderlyingSymbol': group['UnderlyingSymbol'].iloc[0],
                    'ISIN': group.get('ISIN', [np.nan]).iloc[0], 
                    'MarkPrice': group['MarkPrice'].iloc[0],
                    'NavPct': group['PercentOfNAV'].sum()
                }
            return broker_data, report_date
        except Exception:
            return {}, None
