import sqlite3
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta
from config import PRICES_DB_PATH
from logger import logger

class PriceService:
    def __init__(self, db_path: Path = PRICES_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices_daily (
                conid TEXT,
                ticker TEXT,
                date DATE,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (conid, date)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices_daily(ticker)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_date ON prices_daily(date)")
        conn.commit()
        conn.close()

    def get_latest_date(self, conid: str):
        conn = self._connect()
        result = conn.execute(
            "SELECT MAX(date) FROM prices_daily WHERE conid = ?", (conid,)
        ).fetchone()
        conn.close()
        return pd.to_datetime(result[0]) if result[0] else None

    def save_prices(self, conid: str, ticker: str, df: pd.DataFrame):
        if df.empty:
            return 0

        # Prepare for DB
        df = df.copy()
        if 'Date' in df.columns:
            df = df.rename(columns={'Date': 'date'})
        elif not 'date' in df.columns:
            df = df.reset_index().rename(columns={'Date': 'date', 'index': 'date'})
        
        df['conid'] = str(conid)
        df['ticker'] = ticker.upper()
        
        # Standardize column names
        name_map = {
            'Open': 'open', 'High': 'high', 'Low': 'low', 
            'Close': 'close', 'Adj Close': 'close', 'Volume': 'volume'
        }
        df = df.rename(columns=name_map)
        
        # Filter columns
        cols = ['conid', 'ticker', 'date', 'open', 'high', 'low', 'close', 'volume']
        df = df[[c for c in cols if c in df.columns]]
        
        # Ensure date is string format for SQLite
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        
        # --- Deduplication Check ---
        conn = self._connect()
        existing = pd.read_sql_query(
            "SELECT date FROM prices_daily WHERE conid = ?", 
            conn, 
            params=(str(conid),)
        )
        
        if not existing.empty:
            existing_dates = set(existing['date'])
            df = df[~df['date'].isin(existing_dates)]
        
        if df.empty:
            conn.close()
            return 0

        # Insert new rows
        df.to_sql("prices_daily", conn, if_exists="append", index=False, method="multi")
        conn.close()
        return len(df)

    def fetch_and_store(self, conid: str, yf_ticker: str, days_back: int = 365 * 3):
        """Fetches from Yahoo and saves to local DB, only for missing dates."""
        latest = self.get_latest_date(conid)
        
        if latest:
            # If we have data, start from the day after latest
            start_date = (latest + timedelta(days=1)).strftime('%Y-%m-%d')
            # If latest is today or yesterday, might not need anything
            if latest.date() >= datetime.now().date() - timedelta(days=1):
                return self.get_prices(conid)
        else:
            start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

        logger.info(f"Fetching {yf_ticker} (conid:{conid}) from {start_date}")
        df = yf.download(yf_ticker, start=start_date, interval="1d", progress=False, auto_adjust=True)
        
        if not df.empty:
            # Handle MultiIndex if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            self.save_prices(conid, yf_ticker, df)
            
        return self.get_prices(conid)

    def get_prices(self, conid: str, start_date: str = None, end_date: str = None, timeframe: str = 'daily') -> pd.DataFrame:
        query = "SELECT * FROM prices_daily WHERE conid = ?"
        params = [conid]
        
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
            
        query += " ORDER BY date ASC"
        
        conn = self._connect()
        df = pd.read_sql_query(query, conn, params=tuple(params))
        conn.close()
        
        if df.empty:
            return df

        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        
        # Standardize for resampling
        df = df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low', 
            'close': 'Close', 'volume': 'Volume'
        })

        if timeframe == 'daily':
            return df
        elif timeframe == 'weekly':
            return df.resample('W-FRI').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        elif timeframe == 'monthly':
            return df.resample('ME').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        elif timeframe == 'quarterly':
            return df.resample('QE').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        else:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

    def highest_high_since(self, conid: str, since: str, timeframe: str = 'daily'):
        df = self.get_prices(conid, start_date=since, timeframe=timeframe)
        return None if df.empty else df["High"].max()
