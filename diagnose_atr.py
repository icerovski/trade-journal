import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

def diagnostic_atr(ticker_symbol, period="1y", window=14):
    print(f"\n--- ATR DIAGNOSTIC FOR {ticker_symbol} ---")
    
    # 1. Fetch Data
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period=period)
    
    if df.empty:
        print("No data found.")
        return

    # 2. Calculate True Range (TR)
    # TR = max(H-L, |H-Cp|, |L-Cp|)
    df['PrevClose'] = df['Close'].shift(1)
    df['H-L'] = df['High'] - df['Low']
    df['H-Cp'] = abs(df['High'] - df['PrevClose'])
    df['L-Cp'] = abs(df['Low'] - df['PrevClose'])
    df['TR'] = df[['H-L', 'H-Cp', 'L-Cp']].max(axis=1)

    # 3. Wilder's Smoothing (Industry Standard)
    # Initial ATR is the average of the first 14 TR values
    # Subsequent: ATR_today = (ATR_yesterday * 13 + TR_today) / 14
    # This is mathematically equivalent to an EWM with alpha = 1/N
    df['ATR_Wilder'] = df['TR'].ewm(alpha=1/window, min_periods=window, adjust=False).mean()
    
    # 4. SMA ATR (Alternative)
    df['ATR_SMA'] = df['TR'].rolling(window=window).mean()

    # Output last 15 days for comparison
    cols = ['Open', 'High', 'Low', 'Close', 'TR', 'ATR_Wilder', 'ATR_SMA']
    print(df[cols].tail(15))
    
    print("\nFinal Values (Latest):")
    print(f"Wilder's ATR (14): {df['ATR_Wilder'].iloc[-1]:.4f}")
    print(f"SMA ATR (14):      {df['ATR_SMA'].iloc[-1]:.4f}")

if __name__ == "__main__":
    diagnostic_atr("GOOGL")
