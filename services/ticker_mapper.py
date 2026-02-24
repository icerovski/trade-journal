import json
import requests
import pandas as pd
from functools import lru_cache
from config import TICKER_MAP_PATH, IBKR_OPEN_POSITIONS_CSV

class TickerMapper:
    """
    Handles mapping of IBKR tickers/ISINs to Yahoo Finance tickers.
    Features: Persistent caching, In-memory reference caching, and Rule-based heuristics.
    """
    _cache = None
    _positions_df = None

    # --- Heuristic Configuration ---
    # Maps exchange substrings to Yahoo Finance suffixes
    EXCHANGE_SUFFIXES = {
        'IBIS': '.DE',
        'AEB': '.AS',
        'LSE': '.L',
    }

    # Maps currencies to default suffixes if exchange match fails
    CURRENCY_SUFFIXES = {
        'EUR': '.DE',
    }

    # Special handling rules for specific asset classes
    ASSET_RULES = {
        'CRYPTO': lambda t, d: f"{t}-USD",
        'OPT': lambda t, d: t.replace(" ", ""),
    }

    @classmethod
    def _load_cache(cls):
        if cls._cache is None:
            if TICKER_MAP_PATH.exists():
                try:
                    with open(TICKER_MAP_PATH, 'r') as f:
                        cls._cache = json.load(f)
                except Exception:
                    cls._cache = {}
            else:
                cls._cache = {}
        return cls._cache

    @classmethod
    def _save_cache(cls):
        if cls._cache is not None:
            try:
                TICKER_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(TICKER_MAP_PATH, 'w') as f:
                    json.dump(cls._cache, f, indent=4)
            except Exception:
                pass

    @classmethod
    def _get_positions_df(cls):
        """Caches the positions CSV in memory to avoid repeated disk I/O."""
        if cls._positions_df is None:
            if IBKR_OPEN_POSITIONS_CSV.exists():
                try:
                    cls._positions_df = pd.read_csv(IBKR_OPEN_POSITIONS_CSV, on_bad_lines='skip')
                    if 'Symbol' in cls._positions_df.columns:
                        cls._positions_df['Symbol_Upper'] = cls._positions_df['Symbol'].str.upper()
                except Exception:
                    cls._positions_df = pd.DataFrame()
            else:
                cls._positions_df = pd.DataFrame()
        return cls._positions_df

    @staticmethod
    def search_online_ticker(isin):
        """Searches Yahoo Finance for a ticker based on ISIN."""
        if not isin or pd.isna(isin) or isin == "":
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
    @lru_cache(maxsize=128)
    def resolve_yf_ticker(cls, ticker_ibkr, isin=None, asset=None, exchange=None, ccy=None, underlying=None):
        """
        Resolves an IBKR ticker to a Yahoo Finance ticker.
        Priority: 1. Persistent Cache, 2. Online Search (via ISIN), 3. Heuristics
        """
        cache = cls._load_cache()
        ticker_upper = ticker_ibkr.upper()
        
        # 1. Check Cache
        if ticker_upper in cache:
            return cache[ticker_upper]

        # 2. Gather details for search and heuristics
        details = {
            'isin': isin,
            'asset': asset,
            'exchange': exchange,
            'ccy': ccy,
            'underlying': underlying
        }

        # If any detail is missing, try to fill from cached positions CSV
        if not all(details.values()):
            df_open = cls._get_positions_df()
            if not df_open.empty and 'Symbol_Upper' in df_open.columns:
                match = df_open[df_open['Symbol_Upper'] == ticker_upper]
                if not match.empty:
                    row = match.iloc[0]
                    details['isin'] = details['isin'] or row.get('ISIN')
                    details['asset'] = details['asset'] or row.get('AssetClass', 'STK')
                    details['exchange'] = details['exchange'] or row.get('ListingExchange', '')
                    details['ccy'] = details['ccy'] or row.get('CurrencyPrimary', 'USD')
                    details['underlying'] = details['underlying'] or row.get('UnderlyingSymbol', '')

        # 3. Online Search (via ISIN)
        if details['isin'] and not pd.isna(details['isin']):
            yf_ticker = cls.search_online_ticker(details['isin'])
            if yf_ticker:
                cache[ticker_upper] = yf_ticker
                cls._save_cache()
                return yf_ticker

        # 4. Heuristics Fallback
        yf_ticker = cls._apply_heuristics(ticker_ibkr, details)
        
        # Save heuristics result to cache for consistency
        cache[ticker_upper] = yf_ticker
        cls._save_cache()
        return yf_ticker

    @classmethod
    def _apply_heuristics(cls, ticker, details):
        """Applies rule-based mapping when online search fails."""
        asset = details.get('asset') or 'STK'
        exchange = details.get('exchange') or ''
        ccy = details.get('ccy') or 'USD'
        underlying = details.get('underlying') or ''

        # A. Check Asset-Specific Lambda Rules (Crypto/Options)
        if asset in cls.ASSET_RULES:
            return cls.ASSET_RULES[asset](ticker, details)
        
        # B. STK/ETF/FUND Logic
        if asset in ['STK', 'ETF', 'FUND']:
            # 1. Exchange Suffixes
            for key, suffix in cls.EXCHANGE_SUFFIXES.items():
                if key in exchange:
                    # Special Case: IBIS often uses underlying for the YF ticker
                    t = underlying if (key == 'IBIS' and underlying and str(underlying) != 'nan') else ticker
                    return f"{t}{suffix}"
            
            # 2. Currency Fallbacks
            if ccy == 'USD':
                # Renaming rule for preferred stocks or complex symbols
                if ' PR' in ticker:
                    return ticker.replace(' PR ', '-P').replace(' PR', '-P').replace(' ', '-')
                return ticker.replace(' ', '-').replace('.', '-')
            
            if ccy in cls.CURRENCY_SUFFIXES:
                return f"{ticker}{cls.CURRENCY_SUFFIXES[ccy]}"
        
        return ticker
