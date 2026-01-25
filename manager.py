# manager.py
import pandas as pd
import yfinance as yf
import xml.etree.ElementTree as ET
from datetime import datetime
from dateutil.parser import parse
from db import get_conn
from config import EXCLUDED_ASSET_CATEGORIES, EXCLUDED_TICKERS, IBKR_PRICING_XML # <--- Imported

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

def load_ibkr_prices():
    """
    Parses the ibkr_pricing.xml file to get 'markPrice' for tickers.
    Returns a dict: {'AAPL': 150.25, 'BOND_XYZ': 98.5}
    """
    if not IBKR_PRICING_XML.exists():
        return {}
    
    price_map = {}
    try:
        tree = ET.parse(IBKR_PRICING_XML)
        root = tree.getroot()
        positions = root.findall(".//OpenPosition")
        for p in positions:
            sym = p.get('symbol')
            # 'markPrice' is the standard field for current value
            price = p.get('markPrice') or p.get('positionValue') # Fallback if markPrice missing
            
            # If markPrice is missing, try calculating: value / position
            if not price and p.get('position') and p.get('position') != '0':
                 val = float(p.get('positionValue') or 0)
                 qty = float(p.get('position'))
                 price = val / qty
            
            if sym and price:
                price_map[sym] = float(price)
    except Exception:
        pass # Fail silently, we have other fallbacks
    return price_map

def calculate_ticker_stats(group):
    group = group.sort_values(['date', 'id'])
    net_qty = 0.0
    avg_cost = 0.0
    
    for _, row in group.iterrows():
        trade_qty = float(row['quantity'])
        trade_price = float(row['price'])
        side = str(row['side']).upper().strip()

        if side in ['EXP', 'EXPIRE']:
            side = 'SELL' if net_qty > 0 else 'BUY'

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


def get_portfolio_data():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM trades", conn)
    conn.close()

    if df.empty:
        return pd.DataFrame(), 0.0

    # 1. PASS ONE: Calculate Everything
    df['signed_qty'] = df.apply(lambda x: x['quantity'] if x['side'] == 'BUY' else -x['quantity'], axis=1)
    qty_check = df.groupby('ticker')['signed_qty'].sum()
    active_tickers = qty_check[qty_check.abs() > 0.001].index.tolist()
    
    if not active_tickers:
        return pd.DataFrame(), 0.0

    master_df = df[df['ticker'].isin(active_tickers)].copy()
    portfolio = master_df.groupby('ticker').apply(calculate_ticker_stats).reset_index()
    portfolio = portfolio[portfolio['total_qty'].abs() > 0.001].copy()

    # --- PRICE SOURCES ---
    # 1. IBKR Snapshot (The most accurate for Bonds/Options)
    ibkr_prices = load_ibkr_prices()

    # 2. Valuation Logic
    def get_valuation_price(row):
        ticker = row['ticker']
        if ticker in ['USD', 'EUR', 'GBP']: return 1.0
        
        # Priority 1: IBKR Snapshot (If available)
        # This solves the "Yahoo doesn't know Bonds" problem
        if ticker in ibkr_prices and ibkr_prices[ticker] > 0:
            return ibkr_prices[ticker]

        # Priority 2: Live Price (Yahoo Finance)
        try:
            price = yf.Ticker(ticker).fast_info['last_price']
            if price and price > 0:
                return price
        except:
            pass
            
        # Priority 3: Average Entry Cost (Cost Basis)
        return row['avg_entry'] if row['avg_entry'] > 0 else 1.0

    portfolio['current_price'] = portfolio.apply(get_valuation_price, axis=1)
    portfolio['market_value'] = portfolio['total_qty'] * portfolio['current_price']
    
    # True NAV
    total_nav = portfolio['market_value'].sum()

    # 3. PASS TWO: View Filters
    cat_map = master_df.drop_duplicates('ticker').set_index('ticker')['asset_category']
    portfolio['asset_category'] = portfolio['ticker'].map(cat_map).fillna('STK')

    if not portfolio.empty:
        mask_cat = ~portfolio['asset_category'].isin(EXCLUDED_ASSET_CATEGORIES)
        portfolio = portfolio[mask_cat].copy()

    if not portfolio.empty:
        mask_ticker = ~portfolio['ticker'].isin(EXCLUDED_TICKERS)
        portfolio = portfolio[mask_ticker].copy()

    portfolio['unrealized_pl'] = portfolio['market_value'] - (portfolio['total_qty'] * portfolio['avg_entry'])
    portfolio['pl_pct'] = 0.0
    mask = portfolio['avg_entry'] > 0
    portfolio.loc[mask, 'pl_pct'] = (
        portfolio.loc[mask, 'unrealized_pl'] / 
        (portfolio.loc[mask, 'total_qty'] * portfolio.loc[mask, 'avg_entry'])
    ) * 100

    return portfolio, total_nav

# ---------------------------------------------------------
# 3. ATR & RISK LOGIC
# ---------------------------------------------------------

class ATRCalculator:
    @staticmethod
    def calculate(df, window=21, method='SMA'):
        if df.empty or len(df) < window + 1: return None
        df.columns = df.columns.str.lower()
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        if method == 'EMA': atr = tr.ewm(span=window, adjust=False).mean()
        else: atr = tr.rolling(window=window).mean()
        return float(atr.iloc[-1]) if not atr.dropna().empty else None

    @staticmethod
    def fetch_yf_data(ticker, timeframe):
        tf_map = {'daily': {'interval': '1d', 'period': '1y'}, 'weekly': {'interval': '1wk', 'period': '2y'}, 'monthly': {'interval': '1mo', 'period': '5y'}}
        cfg = tf_map.get(timeframe, tf_map['daily'])
        try: return yf.Ticker(ticker).history(period=cfg['period'], interval=cfg['interval'])
        except: return pd.DataFrame()

    @staticmethod
    def get_highest_high(ticker, since_date):
        try:
            df = yf.Ticker(ticker).history(start=since_date, interval="1d")
            return df['High'].max() if not df.empty else 0.0
        except: return 0.0

def get_atr_gauge(ticker, entry_price, entry_date_str):
    configs = [
        ('ATR_21d_SMA', 'daily', 21, 'SMA'), ('ATR_21d_EMA', 'daily', 21, 'EMA'),
        ('ATR_12w_SMA', 'weekly', 12, 'SMA'), ('ATR_12w_EMA', 'weekly', 12, 'EMA'),
        ('ATR_6m_SMA',  'monthly', 6, 'SMA'), ('ATR_6m_EMA',  'monthly', 6, 'EMA'),
    ]
    highest_high = 0.0
    if entry_date_str:
        highest_high = ATRCalculator.get_highest_high(ticker, entry_date_str)
    if highest_high < entry_price: highest_high = entry_price

    results = {}
    data_cache = {}
    for label, tf, win, meth in configs:
        if tf not in data_cache: data_cache[tf] = ATRCalculator.fetch_yf_data(ticker, tf)
        atr = ATRCalculator.calculate(data_cache[tf], window=win, method=meth)
        res = {'atr': atr, 'fsl': None, 'fpct': None, 'tsl': None, 'tpct': None}
        if atr:
            res['fsl'] = entry_price - atr
            res['fpct'] = (atr / entry_price) * 100
            res['tsl'] = highest_high - atr
            res['tpct'] = (atr / highest_high) * 100
        results[label] = res
    return results, highest_high