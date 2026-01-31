import pandas as pd
import numpy as np
import yfinance as yf
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from config import IBKR_TOKEN, IBKR_QUERY_ID_NAV, IBKR_NAV_XML

class PortfolioManager:
    """
    A class to process Interactive Brokers trade logs, calculate position
    metrics, fetch live market data, and retrieve Account NAV.
    """
    
    def __init__(self, file_path_or_dataframe):
        """
        Initialize with a path to the CSV or a pandas DataFrame.
        """
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

    def get_dashboard(self, asset_class_filter=None):
        """Fetches prices and returns the final formatted dashboard DataFrame."""
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
        
        # Calculations
        df['MarketValue'] = df['Price'] * df['Qty']
        df['P/L'] = (df['Price'] - df['Entry']) * df['Qty']
        df['Pct'] = ((df['Price'] - df['Entry']) / df['Entry']) * 100
        
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

        final_cols = ['Name', 'Ticker', 'Date', 'Qty', 'Entry', 'Price', 'MarketValue', 'P/L', 'CCY', 'Pct', 'AAGR']
        return df[final_cols]

    # --- PART 2: NAV & Cash Processing ---

    def fetch_nav_data(self, force_download=False):
        """
        Downloads or loads the NAV Flex Query XML. 
        Returns parsed (TotalNAV, AccountList).
        """
        # 1. Check local cache
        if not force_download and IBKR_NAV_XML.exists():
            # Check if file is from today
            file_date = pd.Timestamp(IBKR_NAV_XML.stat().st_mtime, unit='s').date()
            if file_date == pd.Timestamp.now().date():
                try:
                    tree = ET.parse(IBKR_NAV_XML)
                    return self.parse_nav_report(tree.getroot())
                except Exception:
                    pass # Fallback to download on error

        # 2. Download from IBKR
        if IBKR_QUERY_ID_NAV == "0" or not IBKR_TOKEN:
            print("❌ Error: IBKR Credentials/Query ID missing in .env")
            return None

        url = f"https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={IBKR_QUERY_ID_NAV}&v=3"
        print("⏳ Downloading NAV Report from IBKR...")
        
        try:
            resp = requests.get(url)
            if resp.status_code != 200:
                print(f"❌ HTTP Error: {resp.status_code}")
                return None
            
            # 3. Handle Reference Code (IBKR Async mechanism)
            root = ET.fromstring(resp.content)
            if root.find("Status") is not None and root.find("Status").text == "Success":
                code = root.find("ReferenceCode").text
                base_url = root.find("Url").text
                dl_url = f"{base_url}?q={code}&t={IBKR_TOKEN}&v=3"
                
                # Wait for generation
                import time
                time.sleep(1) # Short wait
                
                report_resp = requests.get(dl_url)
                if report_resp.status_code == 200:
                    # Save to file
                    with open(IBKR_NAV_XML, "wb") as f:
                        f.write(report_resp.content)
                    
                    # Parse
                    full_tree = ET.fromstring(report_resp.content)
                    return self.parse_nav_report(full_tree)
            else:
                err = root.find("ErrorMessage")
                print(f"❌ IBKR Error: {err.text if err is not None else 'Unknown'}")
        
        except Exception as e:
            print(f"❌ Connection Error: {e}")
            
        return None

    def parse_nav_report(self, root):
        """
        Parses the Flex Query XML to extract NAV per account and Total.
        Reads 'acctAlias' directly from the report.
        """
        accounts = []
        total_nav = 0.0

        # We look for "EquitySummaryByReportDateInBase" which contains the alias and total.
        for row in root.findall(".//EquitySummaryByReportDateInBase"):
            # Directly read the alias from the XML
            alias = row.get("acctAlias")
            
            # If alias is somehow missing, try accountId from the parent context or fallback
            if not alias:
                alias = row.get("accountId") or "Unknown"

            nav_val = float(row.get("total", 0)) 
            
            accounts.append({'alias': alias, 'nav': nav_val})
            total_nav += nav_val
            
        return total_nav, accounts