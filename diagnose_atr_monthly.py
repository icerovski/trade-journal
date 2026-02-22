import pandas as pd
import numpy as np
import yfinance as yf

def diagnostic_atr_monthly(ticker_symbol, window=24):
    print(f"\n--- MONTHLY ATR DIAGNOSTIC FOR {ticker_symbol} (Window: {window}, SMA) ---")
    
    # 1. Fetch Data (Need enough for 24 months + buffer)
    ticker = yf.Ticker(ticker_symbol)
    df_daily = ticker.history(period="10y") # Plenty of history
    
    if df_daily.empty:
        print("No data found.")
        return

    # 2. Resample to Monthly
    # We take High/Low/Close for the month
    df = df_daily.resample('ME').agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last'
    })

    # 3. Calculate True Range (TR)
    df['PrevClose'] = df['Close'].shift(1)
    df['H-L'] = df['High'] - df['Low']
    df['H-Cp'] = abs(df['High'] - df['PrevClose'])
    df['L-Cp'] = abs(df['Low'] - df['PrevClose'])
    df['TR'] = df[['H-L', 'H-Cp', 'L-Cp']].max(axis=1)

    # 4. SMA ATR
    df['ATR_SMA'] = df['TR'].rolling(window=window).mean()

    # Output last 12 months
    cols = ['High', 'Low', 'Close', 'TR', 'ATR_SMA']
    print(df[cols].tail(12))
    
    print("\nFinal Value (Latest):")
    print(f"Monthly SMA ATR ({window}): {df['ATR_SMA'].iloc[-1]:.4f}")

if __name__ == "__main__":
    diagnostic_atr_monthly("GOOGL", window=24)
