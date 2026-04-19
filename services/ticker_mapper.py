import requests
import pandas as pd
from functools import lru_cache
from config import IBKR_OPEN_POSITIONS_CSV
import db

class TickerMapper:
    """
    Handles mapping of IBKR tickers/ISINs to Yahoo Finance tickers.
    Uses 'ticker_info' DB table as the Asset Master.
    """
    _positions_df = None

    # --- Heuristic Configuration ---
    EXCHANGE_SUFFIXES = {
        'IBIS': '.DE',
        'AEB': '.AS',
        'LSE': '.L',
    }

    CURRENCY_SUFFIXES = {
        'EUR': '.DE',
    }

    ASSET_RULES = {
        'CRYPTO': lambda t, d: f"{t}-USD",
        'OPT': lambda t, d: t.replace(" ", ""),
    }

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
    def resolve_yf_ticker(cls, ticker_ibkr, isin=None, asset=None, exchange=None, ccy=None, underlying=None, conid=None):
        """
        Resolves an IBKR ticker to a Yahoo Finance ticker.
        Priority: 1. ticker_info table (conid PK), 2. Online Search (via ISIN), 3. Heuristics
        """
        ticker_upper = ticker_ibkr.upper()
        
        # 1. Check DB via Conid (Primary Source of Truth)
        if conid:
            info = db.get_ticker_info(conid)
            if info: 
                # If we have both ticker and ISIN, we are done
                if info['ticker_yfinance'] and info['isin'] and not pd.isna(info['isin']):
                    return info['ticker_yfinance']
                # Otherwise, continue to see if we can enrich it
                if not isin:
                    isin = info['isin']
                if not asset:
                    asset = info['asset_class']
            
        # 2. Check DB via IBKR Ticker (Secondary fallback)
        yf_direct = db.get_yf_ticker(ticker_upper)
        if yf_direct and not conid: 
            # If we don't have conid, we can't easily check for ISIN enrichment here
            return yf_direct

        # 3. Gather details for search and heuristics
        details = {
            'isin': isin,
            'asset': asset,
            'exchange': exchange,
            'ccy': ccy,
            'underlying': underlying
        }

        # If any detail is missing, try to fill from Trades table (New Priority)
        if conid and not all(details.values()):
            trade_info = db.get_asset_details_from_trades(conid)
            if trade_info:
                details['isin'] = details['isin'] or trade_info['isin']
                details['asset'] = details['asset'] or trade_info['asset_category']
                details['exchange'] = details['exchange'] or trade_info['listing_exchange']
                details['ccy'] = details['ccy'] or trade_info['currency']
                details['underlying'] = details['underlying'] or trade_info['underlying_symbol']

        # If still missing, try to fill from cached positions CSV
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
                    if not conid:
                        conid = row.get('Conid')

        # Clean up details (remove 'nan' strings)
        for k, v in details.items():
            if str(v).lower() in ['nan', 'none', '']:
                details[k] = None

        # 4. Online Search (via ISIN)
        yf_ticker = None
        if details['isin']:
            yf_ticker = cls.search_online_ticker(details['isin'])

        # 5. Heuristics Fallback
        if not yf_ticker:
            # If we already have a yf_ticker from DB but were just looking for ISIN, use it
            if conid and info:
                yf_ticker = info['ticker_yfinance']
            else:
                yf_ticker = cls._apply_heuristics(ticker_ibkr, details)
        
        # 6. Save result to Asset Master (DB) for future persistence
        if yf_ticker and conid:
            db.save_ticker_info(
                conid=conid,
                ticker_ibkr=ticker_upper,
                ticker_yfinance=yf_ticker,
                isin=details['isin'],
                asset_class=details['asset']
            )
            
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
