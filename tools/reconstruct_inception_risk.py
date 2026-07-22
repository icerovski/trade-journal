import pandas as pd
import numpy as np
import yfinance as yf
from db import get_conn, set_position_risk
from core.portfolio_manager import PortfolioManager
from logger import logger

def calculate_wilder_atr(df, window=12):
    """Wilder ATR over the full `window`, or 0.0 when history cannot fill it.
    A shrunken-window value keeps the timeframe label only nominally and must never
    be frozen as an inception R unit (same invariant as ATRDiscoveryRow.window_shrunk)."""
    if len(df) - 1 < window:
        return 0.0

    actual_window = window

    df = df.copy()
    df['PrevClose'] = df['Close'].shift(1)
    df['TR'] = np.maximum(df['High'] - df['Low'], 
                np.maximum(abs(df['High'] - df['PrevClose']), 
                           abs(df['Low'] - df['PrevClose'])))

    atr = df['TR'].ewm(com=actual_window - 1, min_periods=actual_window, adjust=False).mean().iloc[-1]
    return float(atr)

def heal_inception_anchors():
    """
    Option B Healing: Reconstructs Inception Stop/ATR using 12q volatility 
    at the time of the original entry.
    """
    logger.info("Starting Institutional Inception Anchor Reconstruction (Option B)...")
    pm = PortfolioManager()
    
    # 1. Identify active positions needing healing
    conn = get_conn()
    cursor = conn.execute("""
        SELECT conid, ticker, status, start_date, inception_stop, inception_atr, 
               atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct
        FROM risk_profiles 
        WHERE status IN ('ACTIVE', 'WATCH') 
        AND (inception_stop IS NULL OR inception_atr IS NULL)
    """)
    profiles = cursor.fetchall()
    conn.close()

    if not profiles:
        logger.info("All positions already have risk anchors. No healing required.")
        return

    # 2. Get live portfolio context for Inception Prices and Dates
    _, positions = pm.get_dashboard_df(silent=True, include_watch=True)
    pos_map = {str(p.conid): p for p in positions}

    for prof in profiles:
        conid = str(prof['conid'])
        ticker = prof['ticker']
        
        pos = pos_map.get(conid)
        if not pos or not pos.date_entry:
            logger.warning(f"Skipping {ticker}: No entry date found in ledger.")
            continue

        entry_date = pos.date_entry
        entry_price = pos.entry_price if pos.entry_price > 0 else pos.mark_price
        
        if entry_price <= 0:
            logger.warning(f"Skipping {ticker}: Invalid entry price ({entry_price}).")
            continue

        logger.info(f"Reconstructing {ticker} (Entry: {entry_date.strftime('%Y-%m-%d')} @ {entry_price:,.2f})")
        
        try:
            # 3. Fetch 12 quarters (3 years) of data ending AT entry date
            # We fetch a bit more to ensure we have enough for the Wilder calculation
            start_search = entry_date - pd.DateOffset(years=4)
            end_search = entry_date + pd.DateOffset(days=5) # Buffer for quarterly close
            
            yf_ticker = pm.mapper.resolve_yf_ticker(ticker, conid=conid)
            hist = yf.Ticker(yf_ticker).history(start=start_search, end=end_search, interval="3mo")
            
            if len(hist) < 13:  # needs window+1 quarterly bars for a full 12q ATR
                logger.warning(f"Insufficient quarterly history for {ticker}. Falling back to 12w ATR.")
                hist = yf.Ticker(yf_ticker).history(start=entry_date - pd.DateOffset(weeks=20), end=end_search, interval="1wk")

            if hist.empty:
                logger.error(f"Failed to fetch history for {ticker}. Skipping.")
                continue

            # 4. Calculate ATR at that point in time
            i_atr = calculate_wilder_atr(hist, window=12)
            if i_atr <= 0:
                logger.warning(f"Skipping {ticker}: history too thin for a full-window ATR — "
                               f"never freeze a shrunken-window value as the inception R unit.")
                continue
            i_stop = entry_price - i_atr
            
            # 5. Commit to DB
            set_position_risk(
                conid, ticker, prof['atr_value'], prof['stop_type'],
                start_date=prof['start_date'],
                entry_type='SINGLE',
                scale_step=0.5,
                status=prof['status'],
                max_r_pct=prof['max_r_pct'],
                max_exp_pct=prof['max_exp_pct'],
                inception_stop=i_stop,
                inception_atr=i_atr
            )
            logger.info(f"  -> SUCCESS: Inception ATR {i_atr:.2f} | Stop {i_stop:,.2f}")
            
        except Exception as e:
            logger.error(f"Error healing {ticker}: {e}")

if __name__ == "__main__":
    heal_inception_anchors()
