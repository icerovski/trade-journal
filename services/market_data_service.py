import warnings
import yfinance as yf
import pandas as pd
import numpy as np
import os
import sys
from contextlib import contextmanager

# Suppress Pandas4Warning from yfinance (deprecated utcnow calls)
warnings.filterwarnings("ignore", category=pd.errors.Pandas4Warning) if hasattr(pd.errors, 'Pandas4Warning') else None
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

from typing import List, Dict
from models import Position
from logger import logger

class MarketDataService:
    """
    Handles batch fetching of market data from Yahoo Finance.
    Optimized for performance and rate-limit avoidance.
    """

    def fetch_market_data(self, positions: List[Position], mapper) -> List[Position]:
        """
        Enriches a list of positions with current prices and max-since-entry highs.
        Uses batch fetching for efficiency.
        """
        if not positions:
            return []

        # 1. Map IBKR tickers to Yahoo Tickers
        yf_to_pos = {} # Map YF_Ticker -> List of Position objects
        for p in positions:
            yf_ticker = mapper.resolve_yf_ticker(
                p.ticker, 
                isin=p.isin,
                asset=p.asset_class,
                exchange=p.listing_exchange,
                ccy=p.ccy,
                underlying=p.underlying_symbol
            )
            if yf_ticker not in yf_to_pos:
                yf_to_pos[yf_ticker] = []
            yf_to_pos[yf_ticker].append(p)

        yf_tickers = list(yf_to_pos.keys())
        logger.info(f"Batch fetching market data for {len(yf_tickers)} unique YF tickers...")

        try:
            # 2. Batch Fetch Current Prices (fastest way)
            # We use group_by='ticker' to get a MultiIndex DataFrame
            with silence_yfinance():
                data = yf.download(yf_tickers, period="1d", interval="1m", progress=False, group_by='ticker')
            
            for yf_ticker, pos_list in yf_to_pos.items():
                price = np.nan
                try:
                    if len(yf_tickers) == 1:
                        # yf.download returns a flat DataFrame for a single ticker
                        if not data.empty:
                            price = data['Close'].iloc[-1]
                    else:
                        ticker_data = data[yf_ticker]
                        if not ticker_data.empty:
                            price = ticker_data['Close'].iloc[-1]
                except Exception:
                    pass

                # 3. Fetch Historical Max High (Needs individual calls for varying start dates)
                # Note: While we could batch this, start dates differ per position.
                # However, we can optimize by only calling history() once per unique YF ticker
                # using the OLDEST entry date among positions sharing that ticker.
                oldest_date = min(p.date_entry for p in pos_list)
                
                try:
                    with silence_yfinance():
                        hist_data = yf.Ticker(yf_ticker).history(start=oldest_date)
                    for p in pos_list:
                        p.current_price = price if not np.isnan(price) else p.mark_price
                        
                        # Filter history for this specific position's entry date
                        if not hist_data.empty:
                            p_hist = hist_data[hist_data.index >= p.date_entry.tz_localize(hist_data.index.tz) if hist_data.index.tz else hist_data.index >= p.date_entry]
                            if not p_hist.empty:
                                p.max_since_entry = p_hist['High'].max()
                            else:
                                p.max_since_entry = p.current_price
                        else:
                            p.max_since_entry = p.current_price
                except Exception as e:
                    logger.debug(f"Failed historical fetch for {yf_ticker}: {e}")
                    for p in pos_list:
                        p.current_price = p.current_price or p.mark_price
                        p.max_since_entry = p.max_since_entry or p.current_price

        except Exception as e:
            logger.error(f"Batch download failed: {e}")
            # Fallback to mark prices
            for p in positions:
                p.current_price = p.mark_price
                p.max_since_entry = p.current_price

        return positions
