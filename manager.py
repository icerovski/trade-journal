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
    parts = [x.strip() for x in user_input.split(",")]
    if len(parts) < 3:
        raise ValueError("Input must have at least Ticker, Date, Price.")

    ticker = parts[0].upper()
    date_str = parts[1]
    price = float(parts[2])
    qty = float(parts[3]) if len(parts) > 3 else 0.0

    try:
        dt = parse(date_str)
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

def calculate_ticker_stats(group):
    # Sort Chronologically
    group = group.sort_values(['date', 'id'])
    
    net_qty = 0.0
    avg_cost = 0.0
    
    for _, row in group.iterrows():
        trade_qty = float(row['quantity'])
        trade_price = float(row['price'])
        side = str(row['side']).upper().strip()

        if side in ['EXP', 'EXPIRE']:
            side = 'SELL' if net_qty > 0 else 'BUY'

        # Logic for Long/Short/Flat states
        if abs(net_qty) < 0.000001:
            if side == 'BUY':
                net_qty = trade_qty
                avg_cost = trade_price
            elif side == 'SELL':
                net_qty = -trade_qty
                avg_cost = trade_price
        elif net_qty > 0:
            if side == 'BUY':
                total_val = (net_qty * avg_cost) + (trade_qty * trade_price)
                net_qty += trade_qty
                avg_cost = total_val / net_qty
            elif side == 'SELL':
                net_qty -= trade_qty
        elif net_qty < 0:
            if side == 'SELL':
                current_short_qty = abs(net_qty)
                total_val = (current_short_qty * avg_cost) + (trade_qty * trade_price)
                net_qty -= trade_qty
                avg_cost = total_val / abs(net_qty)
            elif side == 'BUY':
                net_qty += trade_qty

        if abs(net_qty) < 0.000001:
            net_qty = 0.0
            avg_cost = 0.0

    return pd.Series({'total_qty': net_qty, 'avg_entry': avg_cost})


def get_portfolio_df():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM trades", conn)
    conn.close()

    if df.empty:
        return pd.DataFrame()

    df['signed_qty'] = df.apply(lambda x: x['quantity'] if x['side'] == 'BUY' else -x['quantity'], axis=1)
    
    # Pre-filter closed positions to optimize performance
    qty_check = df.groupby('ticker')['signed_qty'].sum()
    active_tickers = qty_check[qty_check.abs() > 0.001].index.tolist()
    
    if not active_tickers:
        return pd.DataFrame()

    df = df[df['ticker'].isin(active_tickers)].copy()

    # Apply core logic
    portfolio = df.groupby('ticker').apply(calculate_ticker_stats).reset_index()
    portfolio = portfolio[portfolio['total_qty'].abs() > 0.001].copy()

    if portfolio.empty:
        return pd.DataFrame()

    def get_live_price(ticker):
        try:
            return yf.Ticker(ticker).fast_info['last_price']
        except:
            return 0.0

    portfolio['current_price'] = portfolio['ticker'].apply(get_live_price)
    portfolio['market_value'] = portfolio['total_qty'] * portfolio['current_price']
    portfolio['unrealized_pl'] = portfolio['market_value'] - (portfolio['total_qty'] * portfolio['avg_entry'])
    
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
            'daily': {'interval': '1d', 'period': '1y'},
            'weekly': {'interval': '1wk', 'period': '2y'},
            'monthly': {'interval': '1mo', 'period': '5y'},
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
    ]
    
    highest_high = 0.0
    if entry_date_str:
        highest_high = ATRCalculator.get_highest_high(ticker, entry_date_str)
    
    if highest_high < entry_price:
        highest_high = entry_price

    results = {}
    data_cache = {}

    for label, tf, win, meth in configs:
        if tf not in data_cache:
            data_cache[tf] = ATRCalculator.fetch_yf_data(ticker, tf)
        atr = ATRCalculator.calculate(data_cache[tf], window=win, method=meth)
        
        res = {'atr': atr, 'fsl': None, 'fpct': None, 'tsl': None, 'tpct': None}
        if atr:
            res['fsl'] = entry_price - atr
            res['fpct'] = (atr / entry_price) * 100
            res['tsl'] = highest_high - atr
            res['tpct'] = (atr / highest_high) * 100
        results[label] = res

    return results, highest_high