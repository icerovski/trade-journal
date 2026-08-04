import sqlite3
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta
from config import PRICES_DB_PATH
from logger import logger

# --- Adjustment-basis guard -------------------------------------------------
# Yahoo is queried with auto_adjust=True, so every split and dividend re-bases its
# ENTIRE history. save_prices only ever appends dates it has not seen, so without
# a guard the cache ends up as old-basis history welded to new-basis recent bars,
# with an invisible discontinuity at the seam. That corrupts the ATR, the 200-DMA,
# the volume profile, and — worst — highest_high_since, which feeds the trailing
# ratchet that writes a stop into the database permanently.
#
# The guard: re-fetch a few bars we already hold and compare. A re-basing shows up
# as disagreement on dates that cannot otherwise have changed.
PRICE_BASIS_OVERLAP_DAYS = 7      # calendar days of already-cached bars to re-verify
PRICE_BASIS_TOLERANCE = 0.001     # 0.1% — below this is rounding; above it, the basis moved


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices_meta (
                conid TEXT PRIMARY KEY,
                floor_date TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _get_floor_date(self, conid: str):
        conn = self._connect()
        row = conn.execute("SELECT floor_date FROM prices_meta WHERE conid = ?", (conid,)).fetchone()
        conn.close()
        return pd.to_datetime(row[0]).date() if row else None

    def _set_floor_date(self, conid: str, floor_date):
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO prices_meta (conid, floor_date) VALUES (?, ?)",
            (conid, str(floor_date))
        )
        conn.commit()
        conn.close()

    def get_date_range(self, conid: str):
        conn = self._connect()
        result = conn.execute(
            "SELECT MIN(date), MAX(date) FROM prices_daily WHERE conid = ?", (conid,)
        ).fetchone()
        conn.close()
        return (pd.to_datetime(result[0]) if result[0] else None, 
                pd.to_datetime(result[1]) if result[1] else None)

    @staticmethod
    def _normalize(conid: str, ticker: str, df: pd.DataFrame) -> pd.DataFrame:
        """A yfinance frame → the prices_daily column shape (flat lowercase columns,
        ISO date strings). Shared by save_prices and the basis check so the two can
        never compare differently-shaped dates."""
        df = df.copy()

        # --- MultiIndex Fix: Flatten columns if they are MultiIndex ---
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if 'Date' in df.columns:
            df = df.rename(columns={'Date': 'date'})
        elif 'date' not in df.columns:
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
        return df

    def basis_shifted(self, conid: str, fetched: pd.DataFrame, cached_latest) -> bool:
        """True when freshly fetched bars disagree with cached bars on the SAME dates.

        A settled daily bar cannot change — unless Yahoo re-based the series after a
        split or dividend, which is exactly the event that would otherwise leave a
        silent seam in the cache. The most recent cached bar is excluded from the
        comparison: mid-session it is a partial day and would flag on every intraday
        sync. Returns False whenever there is nothing comparable, so an empty or
        malformed fetch never triggers a rebuild.
        """
        if fetched is None or fetched.empty or cached_latest is None:
            return False
        cutoff = pd.to_datetime(cached_latest).strftime('%Y-%m-%d')
        settled = fetched[fetched['date'] < cutoff]
        if settled.empty:
            return False

        conn = self._connect()
        try:
            cached = pd.read_sql_query(
                "SELECT date, close FROM prices_daily WHERE conid = ? AND date BETWEEN ? AND ?",
                conn, params=(str(conid), settled['date'].min(), settled['date'].max()),
            )
        finally:
            conn.close()
        if cached.empty:
            return False

        merged = settled[['date', 'close']].merge(cached, on='date', suffixes=('_new', '_old'))
        merged = merged[merged['close_old'].notna() & (merged['close_old'] > 0)
                        & merged['close_new'].notna()]
        if merged.empty:
            return False

        drift = ((merged['close_new'] / merged['close_old']) - 1.0).abs().max()
        if drift > PRICE_BASIS_TOLERANCE:
            logger.warning(
                f"Price basis shift detected for conid {conid}: cached closes differ from a "
                f"fresh fetch by up to {drift * 100:.2f}% on settled dates."
            )
            return True
        return False

    def rebuild_series(self, conid: str, yf_ticker: str, days_back: int = 365 * 10) -> int:
        """Re-download the full window and REPLACE the cached series for one conid.

        The only way to put a whole series back on one adjustment basis. The cache
        is deleted only after a non-empty download succeeds, so a failed fetch
        leaves the existing (seamed but present) history intact rather than
        emptying it.
        """
        start = (datetime.now() - timedelta(days=days_back)).date()
        floor = self._get_floor_date(conid)
        if floor and floor > start:
            start = floor

        df = yf.download(yf_ticker, start=start.strftime('%Y-%m-%d'), interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            logger.warning(f"Rebuild aborted for {yf_ticker}: no data returned; cache left intact.")
            return 0

        conn = self._connect()
        try:
            conn.execute("DELETE FROM prices_daily WHERE conid = ?", (str(conid),))
            conn.commit()
        finally:
            conn.close()

        n = self.save_prices(conid, yf_ticker, df)
        logger.info(f"Rebuilt {yf_ticker}: {n} bars on the current adjustment basis.")
        return n

    def save_prices(self, conid: str, ticker: str, df: pd.DataFrame):
        if df.empty:
            return 0

        df = self._normalize(conid, ticker, df)

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
        conn.commit()
        conn.close()
        return len(df)

    def fetch_and_store(self, conid: str, yf_ticker: str, days_back: int = 365 * 10):
        """Fetches from Yahoo and saves to local DB, handling both gaps and updates."""
        first, latest = self.get_date_range(conid)
        required_start = (datetime.now() - timedelta(days=days_back)).date()

        # Clamp required_start to the known data floor (e.g. pre-IPO tickers)
        floor = self._get_floor_date(conid)
        if floor and floor > required_start:
            required_start = floor

        # 1. Check for Forward Update (Missing recent data)
        if latest:
            if latest.date() < datetime.now().date() - timedelta(days=1):
                # Start BEFORE the last cached bar, not after it: the overlap is what
                # makes a re-basing detectable. save_prices discards dates already
                # held, so re-fetching them costs nothing when the basis is unchanged.
                start_f = (latest - timedelta(days=PRICE_BASIS_OVERLAP_DAYS)).strftime('%Y-%m-%d')
                logger.info(f"Updating {yf_ticker} forward from {start_f}")
                df_f = yf.download(yf_ticker, start=start_f, interval="1d", progress=False, auto_adjust=True)
                if not df_f.empty:
                    if self.basis_shifted(conid, self._normalize(conid, yf_ticker, df_f), latest):
                        logger.warning(
                            f"{yf_ticker}: adjustment basis changed (split/dividend) — "
                            f"rebuilding the cached series so old and new bars stay comparable."
                        )
                        self.rebuild_series(conid, yf_ticker, days_back)
                    else:
                        self.save_prices(conid, yf_ticker, df_f)

        # 2. Check for Backward Gap (Missing historical data)
        if not first or first.date() > required_start:
            start_b = required_start.strftime('%Y-%m-%d')
            end_b = first.strftime('%Y-%m-%d') if first else datetime.now().strftime('%Y-%m-%d')

            logger.info(f"Fetching historical gap for {yf_ticker} from {start_b} to {end_b}")
            df_b = yf.download(yf_ticker, start=start_b, end=end_b, interval="1d", progress=False, auto_adjust=True)
            if not df_b.empty:
                self.save_prices(conid, yf_ticker, df_b)
            elif first:
                # Nothing exists before first — record the floor so we never retry this range
                self._set_floor_date(conid, first.date())
                logger.info(f"Floor date set for {yf_ticker}: no data before {first.date()}")

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

    def latest_close(self, conid: str):
        """Most recent cached daily close for a conid, or None if the cache is empty.

        Single-row lookup — the canonical fallback when a live quote is unavailable, so the
        price never degrades to the entry price (which would fabricate a stop breach for a
        winner whose stop sits above cost)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT close FROM prices_daily WHERE conid = ? ORDER BY date DESC LIMIT 1",
                (str(conid),)
            ).fetchone()
        finally:
            conn.close()
        return float(row[0]) if row and row[0] is not None else None

    def get_trend_analysis(self, conid: str, yf_ticker: str) -> dict:
        """
        Calculates the 200-DMA trend over the last 100 days.
        Finds the consecutive undisturbed trend direction.
        """
        # Ensure we have the latest data
        df = self.fetch_and_store(conid, yf_ticker)
        
        df = df.dropna(subset=['Close'])
        if df.empty or len(df) < 200:
            logger.warning(f"[get_trend_analysis] {yf_ticker} (conid={conid}): INSUFFICIENT_DATA rows={len(df)}")
            return {"status": "INSUFFICIENT_DATA"}

        # 1. Calculate 200-DMA for trend engine
        dma200 = df['Close'].rolling(window=200).mean()
        recent_dma = dma200.tail(100).dropna()
        
        if len(recent_dma) < 2:
            return {"status": "INSUFFICIENT_DATA"}
            
        diffs = recent_dma.diff().dropna()
        current_direction = 1 if diffs.iloc[-1] > 0 else -1
        consecutive_days = 0
        for val in diffs.iloc[::-1]:
            direction = 1 if val > 0 else -1
            if direction == current_direction:
                consecutive_days += 1
            else:
                break
                
        signal = "NEUTRAL"
        if consecutive_days >= 21:
            signal = "BUY" if current_direction == 1 else "SELL"
            
        # 2. Calculate Comprehensive Moving Averages (DMA & EMA)
        # We'll return 200, 100, 50, 10 for both Simple and Exponential
        tech = {}
        for window in [200, 100, 50, 10]:
            tech[f'DMA{window}'] = df['Close'].rolling(window=window).mean().iloc[-1]
            tech[f'EMA{window}'] = df['Close'].ewm(span=window, adjust=False).mean().iloc[-1]
            
        return {
            "status": "OK",
            "dmas": tech, # tech contains both DMA and EMA now
            "dma200_trend": {
                "direction": "UP" if current_direction == 1 else "DOWN",
                "consecutive_days": consecutive_days,
                "signal": signal
            }
        }
