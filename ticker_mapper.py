import requests
import pandas as pd
import numpy as np
from config import DATA_DIR

class TickerMapper:
    """
    Handles mapping of IBKR tickers/ISINs to Yahoo Finance tickers.
    """
    
    @staticmethod
    def search_online_ticker(isin):
        if not isin or pd.isna(isin):
            return None
        try:
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('quotes'):
                    return data['quotes'][0].get('symbol')
        except Exception:
            pass
        return None

    @classmethod
    def resolve_yf_ticker(cls, ticker_ibkr, isin=None):
        """
        Public method to resolve an IBKR ticker to a Yahoo Finance ticker.
        Priority: 1. Provided ISIN, 2. ISIN from open_positions.csv, 3. Heuristics
        """
        # A. If ISIN not provided, try to find it in open_positions.csv
        if not isin:
            path = DATA_DIR / "open_positions.csv"
            if path.exists():
                try:
                    df_open = pd.read_csv(path, on_bad_lines='skip')
                    match = df_open[df_open['Symbol'].str.upper() == ticker_ibkr.upper()]
                    if not match.empty:
                        isin = match.iloc[0].get('ISIN')
                except Exception:
                    pass

        # B. Use ISIN to find YF Ticker
        if isin and not pd.isna(isin):
            online = cls.search_online_ticker(isin)
            if online:
                return online

        # C. Heuristics Fallback
        exchange, asset, ccy, underlying = "", "STK", "USD", ""
        path = DATA_DIR / "open_positions.csv"
        if path.exists():
            try:
                df_open = pd.read_csv(path, on_bad_lines='skip')
                match = df_open[df_open['Symbol'].str.upper() == ticker_ibkr.upper()]
                if not match.empty:
                    row = match.iloc[0]
                    exchange = str(row.get('ListingExchange', ''))
                    asset = str(row.get('AssetClass', 'STK'))
                    ccy = str(row.get('CurrencyPrimary', 'USD'))
                    underlying = str(row.get('UnderlyingSymbol', ''))
            except Exception:
                pass

        # Mapping logic
        if asset == 'OPT':
            return ticker_ibkr.replace(" ", "")
        
        if asset in ['STK', 'ETF', 'FUND']:
            if 'IBIS' in exchange: 
                t = underlying if (underlying and underlying != 'nan') else ticker_ibkr
                return f"{t}.DE"
            if exchange == 'AEB':
                return f"{ticker_ibkr}.AS"
            if 'LSE' in exchange:
                return f"{ticker_ibkr}.L"
            if ccy == 'USD':
                if ' PR' in ticker_ibkr:
                    return ticker_ibkr.replace(' PR ', '-P').replace(' PR', '-P').replace(' ', '-')
                return ticker_ibkr.replace(' ', '-').replace('.', '-')
            if ccy == 'EUR':
                return f"{ticker_ibkr}.DE"
        
        if asset == 'CRYPTO':
            return f"{ticker_ibkr}-USD"
        
        return ticker_ibkr # Final raw fallback
