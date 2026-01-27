# manager.py
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from dateutil.parser import parse
from fifo_engine import FIFOEngine 
from config import (
    EXCLUDED_ASSET_CATEGORIES, 
    EXCLUDED_TICKERS, 
    IBKR_PRICING_XML, 
    IBKR_YTD_XML 
)

# ---------------------------------------------------------
# 1. IBKR SNAPSHOT LOADER
# ---------------------------------------------------------
def load_ibkr_snapshot_data():
    if not IBKR_PRICING_XML.exists():
        return [], 0.0

    grand_total_nav = 0.0
    positions_list = []
    
    try:
        tree = ET.parse(IBKR_PRICING_XML)
        root = tree.getroot()
        
        # A. GRAND TOTAL NAV (Sum all accounts)
        summaries = root.findall(".//EquitySummaryByReportDateInBase")
        account_map = {}
        for s in summaries:
            acct_id = s.get('accountId')
            raw_total = s.get('total')
            if acct_id and raw_total:
                account_map[acct_id] = float(raw_total)
        
        grand_total_nav = sum(account_map.values())

        # B. OPEN POSITIONS
        ops = root.findall(".//OpenPosition")
        for p in ops:
            try:
                symbol = p.get('symbol')
                if p.get('assetCategory') == 'CASH':
                    symbol = p.get('currency')
                
                positions_list.append({
                    'ticker': symbol,
                    'total_qty': float(p.get('position', 0)),
                    'avg_entry': float(p.get('costBasisPrice', 0)),
                    'market_value': float(p.get('positionValue', 0)),
                    'unrealized_pl': float(p.get('fifoPnlUnrealized', 0)),
                    'asset_category': p.get('assetCategory', 'STK')
                })
            except:
                continue
    except Exception as e:
        print(f"⚠️ Error parsing Pricing XML: {e}")
        
    return positions_list, grand_total_nav

# ---------------------------------------------------------
# 2. CORE PORTFOLIO LOGIC
# ---------------------------------------------------------
def get_portfolio_data():
    ib_rows, official_nav = load_ibkr_snapshot_data()
    
    if not ib_rows:
        return pd.DataFrame(), 0.0

    df = pd.DataFrame(ib_rows)
    fifo = FIFOEngine(IBKR_YTD_XML)

    # --- 1. First Entry Date ---
    df['first_entry'] = df['ticker'].apply(lambda x: fifo.get_open_date(x))

    # --- 2. Calculations ---
    # Current Price
    mask_qty = df['total_qty'] != 0
    df.loc[mask_qty, 'current_price'] = df.loc[mask_qty, 'market_value'] / df.loc[mask_qty, 'total_qty']
    df['current_price'] = df['current_price'].fillna(0.0)

    # P/L %
    df['cost_basis'] = df['market_value'] - df['unrealized_pl']
    mask_valid = df['cost_basis'] != 0
    df.loc[mask_valid, 'pl_pct'] = (df.loc[mask_valid, 'unrealized_pl'] / df.loc[mask_valid, 'cost_basis']) * 100
    df['pl_pct'] = df['pl_pct'].fillna(0.0)

    # --- 3. Annualized Return (CAGR) ---
    def calculate_cagr(row):
        try:
            if row['first_entry'] == "N/A" or row['cost_basis'] <= 0:
                return 0.0
            
            start_date = datetime.strptime(row['first_entry'], '%Y-%m-%d')
            days_held = (datetime.now() - start_date).days
            
            if days_held < 365:
                # For < 1 year, Annualized is misleading. Return simple yield.
                return row['pl_pct'] 
            
            years = days_held / 365.25
            total_return = row['market_value'] / row['cost_basis']
            
            # CAGR Formula: (End/Start)^(1/years) - 1
            cagr = (total_return ** (1 / years)) - 1
            return cagr * 100
        except:
            return 0.0

    df['annualized_pct'] = df.apply(calculate_cagr, axis=1)

    # --- 4. Filters ---
    mask_cat = ~df['asset_category'].isin(EXCLUDED_ASSET_CATEGORIES)
    df = df[mask_cat].copy()
    mask_ticker = ~df['ticker'].isin(EXCLUDED_TICKERS)
    df = df[mask_ticker].copy()

    total_nav = official_nav if official_nav > 0 else df['market_value'].sum()

    return df, total_nav