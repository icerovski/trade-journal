import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path

class PortfolioManager:
    """
    A class to process Interactive Brokers trade logs, calculate position
    metrics, fetch live market data, and retrieve Account NAV.
    """
    
    # 1. MANUAL OVERRIDES
    TICKER_OVERRIDES = {
        "BRK B": "BRK-B",
        "FOUR PRA": "FOUR-PA",
        "JPM PR C": "JPM-PC",
    }
    
    def __init__(self, file_path_or_dataframe):
        if isinstance(file_path_or_dataframe, (Path, str)):
            self.raw_data = pd.read_csv(file_path_or_dataframe)
        elif isinstance(file_path_or_dataframe, pd.DataFrame):
            self.raw_data = file_path_or_dataframe
        else:
            raise ValueError("Input must be a file path (str/Path) or a DataFrame.")
            
        self.positions = pd.DataFrame()

    # --- PART 1: CSV / Position Processing ---

    def _clean_data(self):
        """Internal method to clean and type-cast the raw data."""
        df = self.raw_data.copy()
        df.columns = df.columns.str.strip()
        df['TradeDate'] = pd.to_datetime(df['TradeDate'], errors='coerce')
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
        df['Price'] = pd.to_numeric(df['Price'], errors='coerce')
        
        if 'Conid' in df.columns:
            df['Conid'] = df['Conid'].astype(str)
        
        df = df.dropna(subset=['TradeDate', 'Quantity', 'Price'])
        df = df[df['Buy/Sell'].isin(['BUY', 'SELL'])]
        
        return df.sort_values('TradeDate')

    def _map_to_yahoo_ticker(self, row):
        """Heuristic to map IBKR symbols to Yahoo Finance tickers."""
        symbol = row['Ticker']
        exchange = str(row['ListingExchange'])
        asset = row['AssetClass']
        ccy = row['CCY']
        underlying = str(row['UnderlyingSymbol'])

        # Check Manual Overrides first
        if symbol in self.TICKER_OVERRIDES:
            return self.TICKER_OVERRIDES[symbol]

        # Asset Specific Logic
        if asset == 'OPT':
            return symbol.replace(" ", "")

        if asset in ['STK', 'ETF', 'FUND']:
            if 'IBIS' in exchange:
                ticker = underlying if (underlying and underlying != 'nan') else symbol
                return f"{ticker}.DE"
            if exchange == 'AEB':
                return f"{symbol}.AS"
            if 'LSE' in exchange:
                return f"{symbol}.L"
            
            if ccy == 'USD':
                # Map IBKR formats to Yahoo (e.g., " PR" -> "-P", space -> "-")
                if ' PR' in symbol:
                    clean = symbol.replace(' PR ', '-P').replace(' PR', '-P')
                    return clean.replace(' ', '-')
                if ' ' in symbol:
                    return symbol.replace(' ', '-')
                if '.' in symbol:
                    return symbol.replace('.', '-')
                return symbol
            
            if ccy == 'EUR':
                return f"{symbol}.DE"

        if asset == 'CRYPTO':
            return f"{symbol}-USD"
            
        return None 

    def calculate_positions(self, asset_class_filter=None):
        """Aggregates trades by 'Conid' to calculate current Quantity and Entry Price."""
        df = self._clean_data()

        if asset_class_filter:
            ac_filter = asset_class_filter.upper()
            df = df[df['AssetClass'] == ac_filter]
        
        grouped = df.groupby('Conid')
        position_list = []

        for conid, group in grouped:
            qty = 0.0
            total_cost = 0.0
            first_entry_date = None
            
            for _, row in group.iterrows():
                side = str(row['Buy/Sell']).strip().upper()
                q = abs(row['Quantity'])
                p = row['Price']
                
                if side == 'BUY':
                    if qty == 0:
                        first_entry_date = row['TradeDate']
                    total_cost += q * p
                    qty += q
                elif side == 'SELL':
                    if qty > 0:
                        avg_price = total_cost / qty
                        qty -= q
                        total_cost -= q * avg_price
                    if qty <= 0.0001:
                        qty = 0
                        total_cost = 0
                        first_entry_date = None

            if qty > 0.0001:
                avg_entry = total_cost / qty
                latest_data = group.iloc[-1]
                position_list.append({
                    'Name': latest_data['Description'],
                    'Ticker': latest_data['Symbol'],
                    'Conid': conid,
                    'ListingExchange': latest_data['ListingExchange'],
                    'AssetClass': latest_data['AssetClass'],
                    'UnderlyingSymbol': latest_data['UnderlyingSymbol'],
                    'CCY': latest_data['CurrencyPrimary'],
                    'Date': first_entry_date,
                    'Qty': qty,
                    'Entry': avg_entry
                })

        self.positions = pd.DataFrame(position_list)
        return self.positions

    def get_dashboard(self, asset_class_filter=None, total_nav=None):
        """
        Fetches prices and returns the final formatted dashboard DataFrame.
        
        Args:
            asset_class_filter (str): Filter by Asset Class (e.g. 'STK')
            total_nav (float): Total Net Liquidation Value (Cash + Equity). 
                               Used to calculate % NAV.
        """
        self.calculate_positions(asset_class_filter=asset_class_filter)
        df = self.positions.copy()
        
        if df.empty:
            return pd.DataFrame()
        
        # Fetch Prices
        current_prices = []
        for _, row in df.iterrows():
            ticker = self._map_to_yahoo_ticker(row)
            price = np.nan
            if ticker:
                try:
                    data = yf.Ticker(ticker)
                    hist = data.history(period="1d")
                    if not hist.empty:
                        price = hist['Close'].iloc[-1]
                    else:
                        price = data.info.get('regularMarketPrice', np.nan)
                except Exception:
                    pass
            current_prices.append(price)
            
        df['Price'] = current_prices
        
        # --- Calculations ---
        df['MarketValue'] = df['Price'] * df['Qty']
        df['P/L'] = (df['Price'] - df['Entry']) * df['Qty']
        df['Pct'] = ((df['Price'] - df['Entry']) / df['Entry']) * 100
        
        # AAGR
        today = pd.Timestamp.now()
        df['Years'] = (today - df['Date']).dt.days / 365.25
        
        def _calc_aagr(row):
            if pd.isna(row['Price']) or row['Entry'] <= 0:
                return 0.0
            years = max(row['Years'], 0.04) 
            try:
                return ((row['Price'] / row['Entry']) ** (1 / years)) - 1
            except:
                return 0.0

        df['AAGR'] = df.apply(_calc_aagr, axis=1) * 100

        # --- NEW: % NAV Calculation ---
        # If total_nav is provided (from IBKR), use it.
        # Otherwise, use the sum of visible Market Value (Pure Equity %)
        if total_nav and total_nav > 0:
            denominator = total_nav
        else:
            denominator = df['MarketValue'].sum()
            
        df['NavPct'] = (df['MarketValue'] / denominator) * 100

        final_cols = ['Name', 'Ticker', 'Date', 'Qty', 'Entry', 'Price', 'MarketValue', 'P/L', 'CCY', 'Pct', 'AAGR', 'NavPct']
        return df[final_cols]

    def fetch_nav_data(self, force_download=False):
            """
            Uses the shared downloader from ibkr.py to get the NAV report.
            """
            from config import IBKR_QUERY_ID_NAV, IBKR_NAV_XML
            from ibkr import download_flex_report
            import xml.etree.ElementTree as ET # Import needed here
            
            # 1. Call the master downloader
            # Returns a Path object to the file
            file_path = download_flex_report(
                query_id=IBKR_QUERY_ID_NAV, 
                output_path=IBKR_NAV_XML, 
                force_download=force_download
            )
            
            if not file_path:
                return None
                
            # 2. Parse the result (NAV is still XML)
            try:
                tree = ET.parse(file_path)
                return self.parse_nav_report(tree.getroot())
            except Exception as e:
                print(f"❌ Error parsing NAV XML: {e}")
                return None

    def parse_nav_report(self, root):
        accounts = []
        total_nav = 0.0
        # Check if root exists
        if root is None: return 0.0, []

        for row in root.findall(".//EquitySummaryByReportDateInBase"):
            alias = row.get("acctAlias")
            if not alias: alias = row.get("accountId") or "Unknown"
            nav_val = float(row.get("total", 0)) 
            accounts.append({'alias': alias, 'nav': nav_val})
            total_nav += nav_val
        return total_nav, accounts