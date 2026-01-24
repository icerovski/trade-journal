# manager.py
import pandas as pd
import sqlite3
import yfinance as yf
from datetime import datetime, timedelta
from db import get_conn

# ---------------------------------------------------------
# 1. CORE PORTFOLIO LOGIC
# ---------------------------------------------------------

def get_portfolio_df():
    """
    Reads all trades and calculates current positions.
    Returns a DataFrame of OPEN positions only.
    """
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM trades", conn)
    conn.close()

    if df.empty:
        return pd.DataFrame()

    # Adjust Quantity Signs (Buy = +, Sell = -)
    df['signed_qty'] = df.apply(lambda x: x['quantity'] if x['side'] == 'BUY' else -x['quantity'], axis=1)
    
    # Calculate Cost Basis (Simple Weighted Average)
    df['cost_value'] = df['signed_qty'] * df['price']

    # Group by Ticker
    portfolio = df.groupby('ticker').agg(
        total_qty=('signed_qty', 'sum'),
        avg_entry=('price', 'mean') 
    ).reset_index()

    # Filter out closed positions
    portfolio = portfolio[portfolio['total_qty'] > 0.001].copy()

    # Enrich with Live Prices
    def get_live_price(ticker):
        try:
            return yf.Ticker(ticker).fast_info['last_price']
        except:
            return 0.0

    portfolio['current_price'] = portfolio['ticker'].apply(get_live_price)
    portfolio['market_value'] = portfolio['total_qty'] * portfolio['current_price']
    portfolio['unrealized_pl'] = portfolio['market_value'] - (portfolio['total_qty'] * portfolio['avg_entry'])
    portfolio['pl_pct'] = (portfolio['unrealized_pl'] / (portfolio['total_qty'] * portfolio['avg_entry'])) * 100

    return portfolio


# ---------------------------------------------------------
# 2. ATR & RISK LOGIC (Ported & Adapted)
# ---------------------------------------------------------

class ATRCalculator:
    @staticmethod
    def calculate(df, window=21, method='SMA'):
        """Your original ATR calculation logic."""
        if df.empty or len(df) < window + 1:
            return None
        
        # Ensure column names are lower case for consistency
        df.columns = df.columns.str.lower()
        
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        if method.upper() == 'EMA':
            atr = tr.ewm(span=window, adjust=False).mean()
        else:
            atr = tr.rolling(window=window).mean()
        
        atr = atr.dropna()
        return float(round(atr.iloc[-1], 4)) if not atr.empty else None

    @staticmethod
    def fetch_yf_data(ticker, timeframe):
        """Helper to fetch history from Yahoo Finance."""
        # Map timeframes to YF intervals and periods
        tf_map = {
            'daily':     {'interval': '1d',  'period': '1y'},
            'weekly':    {'interval': '1wk', 'period': '2y'},
            'monthly':   {'interval': '1mo', 'period': '5y'},
            'quarterly': {'interval': '3mo', 'period': '10y'},
        }
        cfg = tf_map.get(timeframe, tf_map['daily'])
        
        try:
            df = yf.Ticker(ticker).history(period=cfg['period'], interval=cfg['interval'])
            return df
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_highest_high(ticker, since_date):
        """Finds the highest high since the entry date (Daily resolution)."""
        try:
            # We add a small buffer to start date to ensure coverage
            df = yf.Ticker(ticker).history(start=since_date, interval="1d")
            if df.empty:
                return 0.0
            return df['High'].max()
        except:
            return 0.0

def get_atr_gauge(ticker, entry_price, entry_date_str):
    """
    Main entry point for the UI.
    Returns the dictionary of risk levels (Fixed SL, Trailing SL, etc).
    """
    configs = [
        ('ATR_21d_SMA', 'daily', 21, 'SMA'),
        ('ATR_21d_EMA', 'daily', 21, 'EMA'),
        ('ATR_12w_SMA', 'weekly', 12, 'SMA'),
        ('ATR_12w_EMA', 'weekly', 12, 'EMA'),
        ('ATR_6m_SMA',  'monthly', 6, 'SMA'),
        # ('ATR_8q_SMA',  'quarterly', 8, 'SMA'), # YF 3mo data can be spotty, keeping it safe
    ]
    
    results = {}
    
    # 1. Get the "Highest High" for Trailing Stop calculations
    # If no date provided, assume today (no trail possible really)
    if not entry_date_str:
        entry_date_str = datetime.today().strftime('%Y-%m-%d')
        
    highest_high = ATRCalculator.get_highest_high(ticker, entry_date_str)
    
    # 2. Run calculations for each config
    for label, tf, win, meth in configs:
        # Fetch data
        df = ATRCalculator.fetch_yf_data(ticker, tf)
        atr = ATRCalculator.calculate(df, window=win, method=meth)
        
        stop = pct = trail_stop = trail_pct = None

        if atr:
            # Fixed Stop Logic
            if entry_price:
                stop = round(entry_price - atr, 2)
                pct = round((atr / entry_price) * 100, 2)
            
            # Trailing Stop Logic
            if highest_high > 0:
                trail_stop = round(highest_high - atr, 2)
                trail_pct = round((atr / highest_high) * 100, 2)

        results[label] = (atr, stop, pct, trail_stop, trail_pct)

    return results, highest_high