import sqlite3
import pandas as pd
from pathlib import Path
import os

db_path = r'C:\Users\User\OneDrive\Accounts\HTC_EOOD\TradeJournalData\trade_journal.db'
csv_path = r'C:\Users\User\OneDrive\Accounts\HTC_EOOD\TradeJournalData\open_positions_lbd.csv'
trades_csv_path = r'C:\Users\User\OneDrive\Accounts\HTC_EOOD\TradeJournalData\trades_ytd.csv'

tickers = ['AFG', 'CLR', 'OXY', 'PEMEX', 'KRE']

print("--- Database Entries ---")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, side, quantity, price, multiplier, asset_category, description FROM trades WHERE ticker IN ('AFG', 'CLR', 'OXY', 'PEMEX', 'KRE')")
    rows = cursor.fetchall()
    for row in rows:
        print(dict(row))
    conn.close()
else:
    print(f"DB not found at {db_path}")

print("\n--- CSV Open Positions (Broker Snapshot) ---")
if os.path.exists(csv_path):
    df = pd.read_csv(csv_path, skiprows=1, on_bad_lines='skip', low_memory=False)
    # Search for tickers
    mask = df['Symbol'].isin(tickers)
    if mask.any():
        cols = ['Symbol', 'Description', 'Quantity', 'CostBasisPrice', 'AssetClass']
        if 'Multiplier' in df.columns:
            cols.append('Multiplier')
        print(df[mask][cols])
    else:
        print("No matches for tickers in open_positions_lbd.csv")
else:
    print(f"File not found: {csv_path}")

print("\n--- CSV Trade Confirmation (Broker Trades) ---")
if os.path.exists(trades_csv_path):
    # Flex CSV for trades might not have skiprows=1 if it's the standard export
    df_trades = pd.read_csv(trades_csv_path, on_bad_lines='skip', low_memory=False)
    mask_trades = df_trades['Symbol'].isin(tickers)
    if mask_trades.any():
        cols_trades = ['Symbol', 'Quantity', 'TradePrice', 'AssetClass']
        if 'Multiplier' in df_trades.columns:
            cols_trades.append('Multiplier')
        print(df_trades[mask_trades][cols_trades])
    else:
        print("No matches for tickers in trades_ytd.csv")
else:
    print(f"File not found: {trades_csv_path}")
