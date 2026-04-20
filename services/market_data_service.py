import warnings
import yfinance as yf
import pandas as pd
import numpy as np
import os
import sys
from contextlib import contextmanager
from typing import List
from models import Position
from logger import logger

# Suppress Pandas4Warning from yfinance (deprecated utcnow calls)
if hasattr(pd.errors, 'Pandas4Warning'):
    warnings.filterwarnings("ignore", category=pd.errors.Pandas4Warning)
# Also suppress FutureWarnings for general stability during library transitions
warnings.filterwarnings("ignore", category=FutureWarning)

@contextmanager
def silence_yfinance():
    """Swallows yfinance stdout/stderr prints that bypass the logging system."""
    new_target = open(os.devnull, "w")
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = new_target
    sys.stderr = new_target
    try:
        yield
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        new_target.close()

def fetch_fx_rate(from_ccy: str, to_ccy: str) -> float | None:
    """Fetches the latest spot rate for from_ccy/to_ccy via Yahoo Finance (e.g. EUR→USD)."""
    try:
        with silence_yfinance():
            return yf.Ticker(f"{from_ccy}{to_ccy}=X").fast_info['last_price']
    except Exception:
        return None


class MarketDataService:
    """
    Handles batch fetching of market data from Yahoo Finance.
    Optimized for performance and rate-limit avoidance.
    """

    def fetch_market_data(self, positions: List[Position], mapper, silent=False) -> List[Position]:
        """
        Enriches a list of positions with current prices and max-since-entry highs.
        Optimized for performance: Batch fetching for current prices and fast local lookups for highs.
        """
        if not positions:
            logger.warning("MarketDataService: No positions to enrich.")
            return []

        # 1. Map IBKR tickers to Yahoo Tickers
        yf_to_pos = {} 
        for p in positions:
            yf_ticker = mapper.resolve_yf_ticker(
                p.ticker, 
                isin=p.isin, 
                asset=p.asset_class, 
                exchange=p.listing_exchange, 
                ccy=p.ccy, 
                underlying=p.underlying_symbol,
                conid=p.conid
            )
            if yf_ticker not in yf_to_pos:
                yf_to_pos[yf_ticker] = []
            yf_to_pos[yf_ticker].append(p)

        yf_tickers = list(yf_to_pos.keys())
        if not silent:
            logger.info(f"Market Data: Fetching prices for {len(yf_tickers)} unique YF tickers: {yf_tickers}")

        try:
            # 2. BATCH FETCH: Current Prices
            # Use period="1d" interval="1m" for delayed current price.
            with silence_yfinance():
                intraday_data = yf.download(yf_tickers, period="1d", interval="1m", progress=False, group_by='ticker')
            
            from services.price_service import PriceService
            ps = PriceService()

            # 3. PROCESS RESULTS
            for yf_ticker, pos_list in yf_to_pos.items():
                price = np.nan
                
                # A. Try extract from intraday batch
                try:
                    if len(yf_tickers) == 1:
                        # yf.download(..., group_by='ticker') usually returns MultiIndex for 1 ticker when group_by is set
                        if isinstance(intraday_data.columns, pd.MultiIndex):
                            ticker_df = intraday_data[yf_ticker]
                        else:
                            ticker_df = intraday_data
                    else:
                        ticker_df = intraday_data[yf_ticker]
                    
                    if not ticker_df.empty:
                        valid_series = ticker_df['Close'].dropna()
                        if not valid_series.empty: 
                            price = valid_series.iloc[-1]
                except Exception as e:
                    logger.debug(f"MarketDataService: Batch extraction failed for {yf_ticker}: {e}")

                # B. Enrich with Individual Fast Fetch if Batch failed or is after-hours
                if np.isnan(price) or price <= 0:
                    try:
                        with silence_yfinance():
                            price = yf.Ticker(yf_ticker).fast_info['last_price']
                    except Exception:
                        pass

                for p in pos_list:
                    # Final fallback to IBKR mark price
                    p.current_price = price if (not np.isnan(price) and price > 0) else p.mark_price
                    
                    # 4. Update Max High using PriceService (Local Cache)
                    try:
                        # PROACTIVE SYNC: Ensure we have history since the (possibly healed) inception date
                        since_date = p.date_entry.strftime('%Y-%m-%d') if pd.notnull(p.date_entry) else None
                        
                        if since_date:
                            # Trigger a check/fetch to ensure prices.db has history since entry
                            ps.fetch_and_store(p.conid, yf_ticker)
                            
                            local_high = ps.highest_high_since(p.conid, since_date)
                            if local_high:
                                p.max_since_entry = max(local_high, p.current_price)
                            else:
                                p.max_since_entry = p.current_price
                        else:
                            p.max_since_entry = p.current_price
                    except Exception as e:
                        logger.debug(f"MarketDataService: High-Water Mark lookup failed for {p.ticker}: {e}")
                        p.max_since_entry = p.current_price

            if not silent:
                logger.info("Market Data: Enrichment complete.")

        except Exception as e:
            logger.error(f"Market Data Error: {e}")
            for p in positions:
                p.current_price = p.mark_price
                p.max_since_entry = max(p.max_since_entry, p.current_price)

        return positions
