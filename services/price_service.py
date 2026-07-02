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

    def save_prices(self, conid: str, ticker: str, df: pd.DataFrame):
        if df.empty:
            return 0

        # Prepare for DB
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
                start_f = (latest + timedelta(days=1)).strftime('%Y-%m-%d')
                logger.info(f"Updating {yf_ticker} forward from {start_f}")
                df_f = yf.download(yf_ticker, start=start_f, interval="1d", progress=False, auto_adjust=True)
                if not df_f.empty:
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

    @staticmethod
    def _series_trend(series: pd.Series, confirm_days: int = 21) -> dict:
        """Slope direction + consecutive undisturbed days of a moving-average series
        (last 100 bars). Returns {} when there is not enough data. The `signal`
        flips to BUY/SELL once the run reaches `confirm_days` (21 for the 200-DMA;
        faster lenses confirm sooner — see constants.REGIME_LENS_BANDS)."""
        recent = series.tail(100).dropna()
        if len(recent) < 2:
            return {}
        diffs = recent.diff().dropna()
        current_direction = 1 if diffs.iloc[-1] > 0 else -1
        consecutive_days = 0
        for val in diffs.iloc[::-1]:
            direction = 1 if val > 0 else -1
            if direction == current_direction:
                consecutive_days += 1
            else:
                break
        signal = "NEUTRAL"
        if consecutive_days >= confirm_days:
            signal = "BUY" if current_direction == 1 else "SELL"
        return {
            "direction": "UP" if current_direction == 1 else "DOWN",
            "consecutive_days": consecutive_days,
            "signal": signal,
        }

    @staticmethod
    def _wilder_atr_daily(df: pd.DataFrame, window: int = 14) -> float:
        """Daily Wilder ATR via the same EWM method as core/stop_loss.py and
        core/zone_scan.py (com=window-1, adjust=False), on the capitalized OHLC
        columns this service loads. 0.0 when High/Low are unavailable."""
        if not {'High', 'Low', 'Close'}.issubset(df.columns):
            return 0.0
        high, low, close = df['High'], df['Low'], df['Close']
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr = tr.ewm(com=window - 1, min_periods=window, adjust=False).mean()
        val = atr.iloc[-1]
        return float(val) if pd.notna(val) else 0.0

    def get_trend_analysis(self, conid: str, yf_ticker: str) -> dict:
        """
        Calculates the 200-DMA trend over the last 100 days.
        Finds the consecutive undisturbed trend direction.
        Also returns per-window (50/100/200) trends and a daily ATR14 for the
        opt-in horizon regime lens — additive keys; `dma200_trend` is unchanged.
        """
        from constants import REGIME_LENS_BANDS

        # Ensure we have the latest data
        df = self.fetch_and_store(conid, yf_ticker)

        df = df.dropna(subset=['Close'])
        if df.empty or len(df) < 200:
            logger.warning(f"[get_trend_analysis] {yf_ticker} (conid={conid}): INSUFFICIENT_DATA rows={len(df)}")
            return {"status": "INSUFFICIENT_DATA"}

        # 1. Calculate 200-DMA for trend engine
        trend200 = self._series_trend(df['Close'].rolling(window=200).mean())
        if not trend200:
            return {"status": "INSUFFICIENT_DATA"}

        # 1b. Faster-lens trends (horizon regime lens). Each window confirms at its
        # own threshold so the displayed signal matches the lens's clock.
        lens_confirm = {window: trend_min for _, window, trend_min, _ in REGIME_LENS_BANDS}
        dma_trends = {200: trend200}
        for window, confirm in lens_confirm.items():
            t = self._series_trend(df['Close'].rolling(window=window).mean(), confirm_days=confirm)
            if t:
                dma_trends[window] = t

        # 2. Calculate Comprehensive Moving Averages (DMA & EMA)
        # We'll return 200, 100, 50, 10 for both Simple and Exponential
        tech = {}
        for window in [200, 100, 50, 10]:
            tech[f'DMA{window}'] = df['Close'].rolling(window=window).mean().iloc[-1]
            tech[f'EMA{window}'] = df['Close'].ewm(span=window, adjust=False).mean().iloc[-1]

        return {
            "status": "OK",
            "dmas": tech, # tech contains both DMA and EMA now
            "dma200_trend": trend200,
            "dma_trends": dma_trends,              # {50: {...}, 100: {...}, 200: {...}}
            "atr14_daily": self._wilder_atr_daily(df),  # lens-selection yardstick
        }
