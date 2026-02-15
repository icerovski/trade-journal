import pandas as pd
import numpy as np
import yfinance as yf
import requests
from pathlib import Path
from db import get_conn

class PortfolioManager:
    """
    A class to process Interactive Brokers trade logs, calculate position
    metrics, fetch live market data, and retrieve Account NAV.
    """
    
    def __init__(self, source=None):
        if source is None:
            self.raw_data = self._load_from_db()
        elif isinstance(source, (Path, str)):
            self.raw_data = pd.read_csv(source)
        elif isinstance(source, pd.DataFrame):
            self.raw_data = source
        else:
            raise ValueError("Input must be None (for DB), a file path, or a DataFrame.")

    def _get_active_conids_from_csv(self):
        """Helper to find which Conids are currently active in IBKR."""
        from config import DATA_DIR
        path = DATA_DIR / "open_positions.csv"
        if not path.exists(): return []
        try:
            # IBKR CSVs have repeating headers. We filter for rows where 'Conid' is numeric.
            df = pd.read_csv(path, on_bad_lines='skip')
            df['Conid_Clean'] = pd.to_numeric(df['Conid'], errors='coerce')
            active_conids = df[(df['LevelOfDetail'] == 'SUMMARY') & (df['Conid_Clean'].notna())]['Conid'].unique().tolist()
            return [str(int(float(c))) for c in active_conids]
        except Exception: return []

    def _load_from_db(self, all_trades=False):
        """
        Loads trades from the SQLite database.
        Optimized: Only loads trades for active Conids or MANUAL entries unless all_trades is True.
        """
        active_conids = self._get_active_conids_from_csv()
        conn = get_conn()
        
        if not all_trades and active_conids:
            placeholders = ', '.join(['?'] * len(active_conids))
            query = f"SELECT * FROM trades WHERE conid IN ({placeholders}) OR source = 'MANUAL' OR source = 'OPENING_BALANCE'"
            df = pd.read_sql_query(query, conn, params=active_conids)
        else:
            # Load everything for full ledger replay
            df = pd.read_sql_query("SELECT * FROM trades", conn)
            
        conn.close()
        
        rename_map = {
            'date': 'TradeDate', 'ticker': 'Symbol', 'side': 'Buy/Sell',
            'quantity': 'Quantity', 'price': 'Price', 'asset_category': 'AssetClass',
            'description': 'Description', 'conid': 'Conid', 'listing_exchange': 'ListingExchange',
            'currency': 'CurrencyPrimary', 'underlying_symbol': 'UnderlyingSymbol'
        }
        return df.rename(columns=rename_map)

    def _clean_data(self):
        df = self.raw_data.copy()
        df.columns = df.columns.str.strip()
        df['TradeDate'] = pd.to_datetime(df['TradeDate'], errors='coerce')
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
        df['Price'] = pd.to_numeric(df['Price'], errors='coerce')
        for col in ['Conid', 'ListingExchange', 'CurrencyPrimary', 'UnderlyingSymbol']:
            if col not in df.columns: df[col] = np.nan
        if 'Conid' in df.columns:
            df['Conid'] = df['Conid'].fillna(df['Symbol']).astype(str)
        df = df.dropna(subset=['TradeDate', 'Quantity', 'Price'])
        df = df[df['Buy/Sell'].isin(['BUY', 'SELL'])]
        return df.sort_values('TradeDate')

    def _search_online_ticker(self, isin):
        if not isin or pd.isna(isin): return None
        try:
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('quotes'): return data['quotes'][0].get('symbol')
        except Exception: pass
        return None

    def _map_to_yahoo_ticker(self, row):
        symbol, exchange, asset, ccy, underlying = row['Ticker'], str(row['ListingExchange']), row['AssetClass'], row['CCY'], str(row['UnderlyingSymbol'])
        
        if asset == 'OPT':
            return symbol.replace(" ", "")

        if 'ISIN' in row and not pd.isna(row['ISIN']):
            online = self._search_online_ticker(row['ISIN'])
            if online: return online

        if asset in ['STK', 'ETF', 'FUND']:
            if 'IBIS' in exchange: 
                t = underlying if (underlying and underlying != 'nan') else symbol
                return f"{t}.DE"
            if exchange == 'AEB': return f"{symbol}.AS"
            if 'LSE' in exchange: return f"{symbol}.L"
            if ccy == 'USD':
                if ' PR' in symbol: return symbol.replace(' PR ', '-P').replace(' PR', '-P').replace(' ', '-')
                return symbol.replace(' ', '-').replace('.', '-')
            if ccy == 'EUR': return f"{symbol}.DE"
        if asset == 'CRYPTO': return f"{symbol}-USD"
        return None 

    def _get_broker_verified_positions(self):
        from config import DATA_DIR
        path = DATA_DIR / "open_positions.csv"
        if not path.exists(): return {}, None
        try:
            df = pd.read_csv(path, on_bad_lines='skip')
            df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
            df['CostBasisPrice'] = pd.to_numeric(df['CostBasisPrice'], errors='coerce')
            df['MarkPrice'] = pd.to_numeric(df['MarkPrice'], errors='coerce')
            df['PercentOfNAV'] = pd.to_numeric(df['PercentOfNAV'], errors='coerce')
            df = df.dropna(subset=['Quantity', 'CostBasisPrice', 'Conid'])

            lots = df[df['LevelOfDetail'] == 'LOT'].copy()
            lots['OpenDateClean'] = pd.to_datetime(lots['OpenDateTime'].str.split(';').str[0], errors='coerce')
            earliest_dates = lots.groupby('Conid')['OpenDateClean'].min().to_dict()
            
            summaries = df[df['LevelOfDetail'] == 'SUMMARY'].copy()
            broker_data = {}
            report_date = pd.to_datetime(summaries['ReportDate'].iloc[0], errors='coerce')
            for conid, group in summaries.groupby('Conid'):
                qty = group['Quantity'].sum()
                total_cost_money = (group['CostBasisPrice'] * group['Quantity']).sum()
                broker_data[str(conid)] = {
                    'Qty': qty, 'Entry': total_cost_money / qty if abs(qty) > 0 else 0,
                    'Date': earliest_dates.get(conid) or report_date,
                    'Description': group['Description'].iloc[0], 'Symbol': group['Symbol'].iloc[0],
                    'AssetClass': group['AssetClass'].iloc[0], 'Currency': group['CurrencyPrimary'].iloc[0],
                    'ListingExchange': group['ListingExchange'].iloc[0], 'UnderlyingSymbol': group['UnderlyingSymbol'].iloc[0],
                    'ISIN': group.get('ISIN', [np.nan]).iloc[0],
                    'MarkPrice': group['MarkPrice'].iloc[0],
                    'NavPct': group['PercentOfNAV'].sum()
                }
            return broker_data, report_date
        except Exception as e:
            return {}, None

    def identify_open_positions(self, asset_class_filter=None):
        ledger_df = self._clean_data()
        broker_verified, report_date = self._get_broker_verified_positions()
        
        # Normalize filters
        filters = []
        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            ledger_df = ledger_df[ledger_df['AssetClass'].isin(filters)]
        
        manual_trades = ledger_df[ledger_df['source'] == 'MANUAL'].copy()
        pending_manual = manual_trades[manual_trades['TradeDate'] > report_date] if report_date else manual_trades
        open_positions, matched_tickers = [], set()

        for conid, v in broker_verified.items():
            # 1. Apply Asset Class Filter to Broker Data
            if filters and v['AssetClass'].upper() not in filters:
                continue

            ticker, qty, entry, first_date = v['Symbol'], v['Qty'], v['Entry'], v['Date']
            adjustments = pending_manual[pending_manual['Symbol'] == ticker]
            for _, row in adjustments.iterrows():
                side, q, p = row['Buy/Sell'], row['Quantity'], row['Price']
                if side == 'BUY':
                    new_qty = qty + q
                    entry = ((qty * entry) + (q * p)) / new_qty if new_qty != 0 else 0
                    qty = new_qty
                else: qty = max(0, qty - q)
                if row['TradeDate'] < first_date: first_date = row['TradeDate']
            
            if qty > 0.0001:
                open_positions.append({
                    'Name': v['Description'], 'Ticker': ticker, 'Conid': conid,
                    'ListingExchange': v['ListingExchange'], 'AssetClass': v['AssetClass'],
                    'UnderlyingSymbol': v['UnderlyingSymbol'], 'CCY': v['Currency'], 'ISIN': v['ISIN'],
                    'Date': first_date, 'Qty': qty, 'Entry': entry, 'MarkPrice': v['MarkPrice'], 'NavPctVerified': v['NavPct']
                })
            matched_tickers.add(ticker)

        remaining_manual = pending_manual[~pending_manual['Symbol'].isin(matched_tickers)]
        for ticker, group in remaining_manual.groupby('Symbol'):
            qty, total_cost, first_date = 0.0, 0.0, None
            for _, row in group.iterrows():
                side, q, p = row['Buy/Sell'], row['Quantity'], row['Price']
                if side == 'BUY':
                    if qty == 0: first_date = row['TradeDate']
                    total_cost += q * p
                    qty += q
                elif side == 'SELL' and qty > 0:
                    total_cost -= q * (total_cost / qty)
                    qty -= q
            if qty > 0.0001:
                latest = group.iloc[-1]
                open_positions.append({
                    'Name': latest.get('Description', ticker), 'Ticker': ticker, 'Conid': ticker,
                    'ListingExchange': latest['ListingExchange'], 'AssetClass': latest['AssetClass'],
                    'UnderlyingSymbol': latest['UnderlyingSymbol'], 'CCY': latest.get('CurrencyPrimary', 'USD'),
                    'Date': first_date, 'Qty': qty, 'Entry': total_cost / qty, 'MarkPrice': group.iloc[-1]['Price'], 'ISIN': np.nan
                })
        return open_positions

    def identify_open_positions_ledger(self, asset_class_filter=None):
        """
        Pure Ledger Replay Logic:
        Identifies open positions by replaying the entire trade history.
        """
        full_df = self._clean_data() 
        
        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            full_df = full_df[full_df['AssetClass'].isin(filters)]
            
        grouped = full_df.groupby('Conid')
        open_positions = []

        for conid, group in grouped:
            qty = 0.0
            total_cost = 0.0
            first_date = None
            
            for _, row in group.iterrows():
                side, q, p = str(row['Buy/Sell']).strip().upper(), abs(row['Quantity']), row['Price']
                source = str(row.get('source', '')).upper()
                
                if 'OPENING_BALANCE' in source:
                    qty, total_cost, first_date = q, q * p, row['TradeDate']
                    continue

                if side == 'BUY':
                    if qty <= 0.0001: first_date = row['TradeDate']
                    total_cost += q * p
                    qty += q
                elif side == 'SELL':
                    if qty > 0:
                        avg_price = total_cost / qty
                        qty -= q
                        total_cost -= q * avg_price
                    
                    if qty <= 0.0001:
                        qty, total_cost, first_date = 0, 0, None

            if qty > 0.0001:
                latest = group.iloc[-1]
                open_positions.append({
                    'Name': latest['Description'], 'Ticker': latest['Symbol'], 'Conid': conid,
                    'ListingExchange': latest['ListingExchange'], 'AssetClass': latest['AssetClass'],
                    'UnderlyingSymbol': latest['UnderlyingSymbol'], 'CCY': latest.get('CurrencyPrimary') or 'EUR',
                    'Date': first_date, 'Qty': qty, 'Entry': total_cost / qty,
                    'ISIN': latest.get('ISIN', np.nan), 'MarkPrice': latest['Price']
                })

        return open_positions

    def get_dashboard(self, asset_class_filter=None, total_nav=None, use_ledger=False):
        """
        Fetches prices and returns the final formatted dashboard DataFrame.
        """
        if use_ledger:
            self.raw_data = self._load_from_db(all_trades=True)
            open_list = self.identify_open_positions_ledger(asset_class_filter=asset_class_filter)
        else:
            open_list = self.identify_open_positions(asset_class_filter=asset_class_filter)
            
        df = pd.DataFrame(open_list)
        if df.empty: return pd.DataFrame()
        
        current_prices = []
        for _, row in df.iterrows():
            ticker = self._map_to_yahoo_ticker(row)
            price = np.nan
            if ticker:
                try:
                    data = yf.Ticker(ticker)
                    price = data.fast_info.get('last_price', np.nan)
                    if np.isnan(price):
                        hist = data.history(period="1d")
                        if not hist.empty: price = hist['Close'].iloc[-1]
                except Exception: pass
            if np.isnan(price): price = row.get('MarkPrice', np.nan)
            current_prices.append(price)
            
        df['Price'] = current_prices
        df['MarketValue'] = df['Price'] * df['Qty']
        df['P/L'] = (df['Price'] - df['Entry']) * df['Qty']
        df['Pct'] = ((df['Price'] - df['Entry']) / df['Entry']) * 100
        today = pd.Timestamp.now()
        df['Years'] = (today - pd.to_datetime(df['Date'])).dt.days / 365.25
        df['AAGR'] = df.apply(self._calc_aagr, axis=1) * 100
        denominator = total_nav if (total_nav and total_nav > 0) else df['MarketValue'].sum()
        df['NavPct'] = (df['MarketValue'] / denominator) * 100
        return df[['Name', 'Ticker', 'Date', 'Qty', 'Entry', 'Price', 'MarketValue', 'P/L', 'CCY', 'Pct', 'AAGR', 'NavPct', 'AssetClass']]

    def _calc_aagr(self, row):
        if pd.isna(row['Price']) or row['Entry'] <= 0: return 0.0
        years = max(row['Years'], 0.04) 
        try: return ((row['Price'] / row['Entry']) ** (1 / years)) - 1
        except: return 0.0

    def fetch_nav_data(self, force_download=False):
            from config import IBKR_QUERY_ID_NAV, IBKR_NAV_XML
            from ibkr import download_flex_report
            import xml.etree.ElementTree as ET
            file_path = download_flex_report(IBKR_QUERY_ID_NAV, IBKR_NAV_XML, force_download=force_download)
            if not file_path: return None
            try:
                tree = ET.parse(file_path)
                return self.parse_nav_report(tree.getroot())
            except Exception as e:
                print(f"❌ Error parsing NAV XML: {e}")
                return None

    def parse_nav_report(self, root):
        accounts, total_nav, report_date = [], 0.0, "Unknown"
        if root is None: return 0.0, [], report_date
        rows = root.findall(".//EquitySummaryByReportDateInBase")
        for row in rows:
            if report_date == "Unknown": report_date = row.get("reportDate", "Unknown")
            alias = row.get("acctAlias") or row.get("accountId") or "Unknown"
            nav_val = float(row.get("total", 0)) 
            accounts.append({'alias': alias, 'nav': nav_val})
            total_nav += nav_val
        return total_nav, accounts, report_date
