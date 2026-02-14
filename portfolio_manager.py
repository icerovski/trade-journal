import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
from db import get_conn

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
    
    def __init__(self, source=None):
        """
        source can be:
        - None (loads from SQLite DB)
        - Path/str (loads from CSV)
        - pd.DataFrame
        """
        if source is None:
            self.raw_data = self._load_from_db()
        elif isinstance(source, (Path, str)):
            self.raw_data = pd.read_csv(source)
        elif isinstance(source, pd.DataFrame):
            self.raw_data = source
        else:
            raise ValueError("Input must be None (for DB), a file path, or a DataFrame.")
            
        self.positions = pd.DataFrame()

    def _load_from_db(self):
        """Loads all trades from the SQLite database."""
        conn = get_conn()
        df = pd.read_sql_query("SELECT * FROM trades", conn)
        conn.close()
        
        # Rename DB columns to match internal processing expectations
        rename_map = {
            'date': 'TradeDate',
            'ticker': 'Symbol',
            'side': 'Buy/Sell',
            'quantity': 'Quantity',
            'price': 'Price',
            'asset_category': 'AssetClass',
            'description': 'Description',
            'conid': 'Conid',
            'listing_exchange': 'ListingExchange',
            'currency': 'CurrencyPrimary',
            'underlying_symbol': 'UnderlyingSymbol'
        }
        return df.rename(columns=rename_map)

    # --- PART 1: CSV / Position Processing ---

    def _clean_data(self):
        """Internal method to clean and type-cast the raw data."""
        df = self.raw_data.copy()
        df.columns = df.columns.str.strip()
        df['TradeDate'] = pd.to_datetime(df['TradeDate'], errors='coerce')
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
        df['Price'] = pd.to_numeric(df['Price'], errors='coerce')
        
        # Ensure we have essential columns even if empty
        for col in ['Conid', 'ListingExchange', 'CurrencyPrimary', 'UnderlyingSymbol']:
            if col not in df.columns:
                df[col] = np.nan

        if 'Conid' in df.columns:
            # For manual trades, we use Symbol as Conid if Conid is missing
            df['Conid'] = df['Conid'].fillna(df['Symbol']).astype(str)
        
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
            # Option tickers in Yahoo usually look like: AAPL230616C00150000
            # IBKR symbols for options are often already in a similar format or need cleanup
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

    def identify_open_positions(self, asset_class_filter=None):
        """
        Clocked Open Logic: 
        Replays the ledger for each asset. If quantity hits zero, the position is 'clocked' closed.
        Returns a list of dictionaries representing currently open positions.
        
        Args:
            asset_class_filter (str or list): Category to include (e.g. 'STK' or ['STK', 'ETF'])
        """
        df = self._clean_data()

        if asset_class_filter:
            if isinstance(asset_class_filter, str):
                df = df[df['AssetClass'] == asset_class_filter.upper()]
            elif isinstance(asset_class_filter, list):
                upper_filters = [f.upper() for f in asset_class_filter]
                df = df[df['AssetClass'].isin(upper_filters)]
        
        grouped = df.groupby('Conid')
        open_positions = []

        for conid, group in grouped:
            qty = 0.0
            total_cost = 0.0
            first_entry_date = None
            
            # Sort chronologically to replay accurately
            for _, row in group.iterrows():
                side = str(row['Buy/Sell']).strip().upper()
                q = abs(row['Quantity'])
                p = row['Price']
                source = str(row.get('source', '')).upper()
                
                # RESET ON OPENING BALANCE: 
                # If we encounter an opening balance, it represents the state at that date.
                # We wipe previous history for this asset to avoid double counting.
                if 'OPENING_BALANCE' in source:
                    qty = q
                    total_cost = q * p
                    first_entry_date = row['TradeDate']
                    continue

                if side == 'BUY':
                    if qty == 0:
                        # Position was closed or is brand new, clocking start date
                        first_entry_date = row['TradeDate']
                    total_cost += q * p
                    qty += q
                elif side == 'SELL':
                    if qty > 0:
                        # Weighted Average Cost logic
                        avg_price = total_cost / qty
                        qty -= q
                        total_cost -= q * avg_price
                    
                    # CLOCKED CLOSED: Reset if quantity hits zero
                    if qty <= 0.0001:
                        qty = 0
                        total_cost = 0
                        first_entry_date = None

            # If after replaying history we have a residual quantity, it is OPEN
            if qty > 0.0001:
                latest_data = group.iloc[-1]
                open_positions.append({
                    'Name': latest_data['Description'],
                    'Ticker': latest_data['Symbol'],
                    'Conid': conid,
                    'ListingExchange': latest_data['ListingExchange'],
                    'AssetClass': latest_data['AssetClass'],
                    'UnderlyingSymbol': latest_data['UnderlyingSymbol'],
                    'CCY': latest_data.get('CurrencyPrimary') or latest_data.get('CCY') or 'EUR', 
                    'Date': first_entry_date,
                    'Qty': qty,
                    'Entry': total_cost / qty
                })

        return open_positions

    def calculate_positions(self, asset_class_filter=None):
        """Wrapper that sets self.positions based on identified open positions."""
        open_list = self.identify_open_positions(asset_class_filter=asset_class_filter)
        self.positions = pd.DataFrame(open_list)
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
                    # Use fast_info if available for efficiency, fallback to history
                    price = data.fast_info.get('last_price', np.nan)
                    if np.isnan(price):
                        hist = data.history(period="1d")
                        if not hist.empty:
                            price = hist['Close'].iloc[-1]
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
        report_date = "Unknown"
        # Check if root exists
        if root is None: return 0.0, [], report_date

        rows = root.findall(".//EquitySummaryByReportDateInBase")
        for row in rows:
            if report_date == "Unknown":
                report_date = row.get("reportDate", "Unknown")
            alias = row.get("acctAlias")
            if not alias: alias = row.get("accountId") or "Unknown"
            nav_val = float(row.get("total", 0)) 
            accounts.append({'alias': alias, 'nav': nav_val})
            total_nav += nav_val
        return total_nav, accounts, report_date