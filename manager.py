# manager.py
import pandas as pd
import yfinance as yf
from datetime import datetime
from dateutil.parser import parse
from db import get_conn

# ---------------------------------------------------------
# 1. INPUT PARSING UTILS
# ---------------------------------------------------------

def parse_input_string(user_input):
    """
    Parses string like: 'AAPL, 24 Jun 2025, 180.50, 10'
    Returns dict: {'ticker': str, 'date': str (YYYY-MM-DD), 'price': float, 'quantity': float}
    """
    parts = [x.strip() for x in user_input.split(",")]
    if len(parts) < 3:
        raise ValueError("Input must have at least Ticker, Date, Price.")

    ticker = parts[0].upper()
    date_str = parts[1]
    price = float(parts[2])
    
    # Optional Quantity (default to 0 if not provided, useful for ATR check)
    qty = float(parts[3]) if len(parts) > 3 else 0.0

    # Robust Date Parsing
    try:
        dt = parse(date_str)
        # Handle cases where user types "24 Jun" without year -> defaults to current year
        if dt.year == 1900: 
            dt = dt.replace(year=datetime.now().year)
        formatted_date = dt.strftime('%Y-%m-%d')
    except Exception:
        raise ValueError(f"Could not parse date: {date_str}")

    return {
        "ticker": ticker,
        "date": formatted_date,
        "price": price,
        "quantity": qty
    }


# ---------------------------------------------------------
# 2. CORE PORTFOLIO LOGIC
# ---------------------------------------------------------

def get_portfolio_df():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM trades", conn)
    conn.close()

    if df.empty:
        return pd.DataFrame()

    df['signed_qty'] = df.apply(lambda x: x['quantity'] if x['side'] == 'BUY' else -x['quantity'], axis=1)
    
    # Calculate weighted average entry could be done here, 
    # but for simplicity we take simple mean for now.
    portfolio = df.groupby('ticker').agg(
        total_qty=('signed_qty', 'sum'),
        avg_entry=('price', 'mean') 
    ).reset_index()

    portfolio = portfolio[portfolio['total_qty'] > 0.001].copy()

    def get_live_price(ticker):
        try:
            return yf.Ticker(ticker).fast_info['last_price']
        except:
            return 0.0

    portfolio['current_price'] = portfolio['ticker'].apply(get_live_price)
    portfolio['market_value'] = portfolio['total_qty'] * portfolio['current_price']
    portfolio['unrealized_pl'] = portfolio['market_value'] - (portfolio['total_qty'] * portfolio['avg_entry'])
    
    # Avoid division by zero
    portfolio['pl_pct'] = 0.0
    mask = portfolio['avg_entry'] > 0
    portfolio.loc[mask, 'pl_pct'] = (
        portfolio.loc[mask, 'unrealized_pl'] / 
        (portfolio.loc[mask, 'total_qty'] * portfolio.loc[mask, 'avg_entry'])
    ) * 100

    return portfolio


# ---------------------------------------------------------
# 3. ATR & RISK LOGIC
# ---------------------------------------------------------

class ATRCalculator:
    @staticmethod
    def calculate(df, window=21, method='SMA'):
        if df.empty or len(df) < window + 1:
            return None
        
        df.columns = df.columns.str.lower()
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        if method == 'EMA':
            atr = tr.ewm(span=window, adjust=False).mean()
        else:
            atr = tr.rolling(window=window).mean()
        
        return float(atr.iloc[-1]) if not atr.dropna().empty else None

    @staticmethod
    def fetch_yf_data(ticker, timeframe):
        tf_map = {
            'daily':     {'interval': '1d',  'period': '1y'},
            'weekly':    {'interval': '1wk', 'period': '2y'},
            'monthly':   {'interval': '1mo', 'period': '5y'},
            'quarterly': {'interval': '3mo', 'period': '10y'},
        }
        cfg = tf_map.get(timeframe, tf_map['daily'])
        try:
            return yf.Ticker(ticker).history(period=cfg['period'], interval=cfg['interval'])
        except:
            return pd.DataFrame()

    @staticmethod
    def get_highest_high(ticker, since_date):
        try:
            df = yf.Ticker(ticker).history(start=since_date, interval="1d")
            return df['High'].max() if not df.empty else 0.0
        except:
            return 0.0

def get_atr_gauge(ticker, entry_price, entry_date_str):
    configs = [
        ('ATR_21d_SMA', 'daily', 21, 'SMA'),
        ('ATR_21d_EMA', 'daily', 21, 'EMA'),
        ('ATR_12w_SMA', 'weekly', 12, 'SMA'),
        ('ATR_12w_EMA', 'weekly', 12, 'EMA'),
        ('ATR_6m_SMA',  'monthly', 6, 'SMA'),
        ('ATR_6m_EMA',  'monthly', 6, 'EMA'),
        ('ATR_8q_SMA',  'quarterly', 8, 'SMA'),
        ('ATR_8q_EMA',  'quarterly', 8, 'EMA'),
    ]
    
    # 1. Trailing High Calculation
    highest_high = 0.0
    if entry_date_str:
        highest_high = ATRCalculator.get_highest_high(ticker, entry_date_str)
    
    # If highest_high is 0 or less than entry, treat Entry as High
    if highest_high < entry_price:
        highest_high = entry_price

    results = {}
    
    # Cache data to avoid duplicate fetches
    data_cache = {}

    for label, tf, win, meth in configs:
        if tf not in data_cache:
            data_cache[tf] = ATRCalculator.fetch_yf_data(ticker, tf)
        
        atr = ATRCalculator.calculate(data_cache[tf], window=win, method=meth)
        
        res = {'atr': atr, 'fsl': None, 'fpct': None, 'tsl': None, 'tpct': None}
        
        if atr:
            # Fixed Stop
            res['fsl'] = entry_price - atr
            res['fpct'] = (atr / entry_price) * 100
            
            # Trailing Stop
            res['tsl'] = highest_high - atr
            res['tpct'] = (atr / highest_high) * 100

        results[label] = res

    return results, highest_high