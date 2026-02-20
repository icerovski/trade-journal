import pandas as pd
import os

csv_path = r'C:\Users\User\OneDrive\Accounts\HTC_EOOD\TradeJournalData\open_positions_lbd.csv'

if os.path.exists(csv_path):
    with open(csv_path, 'r') as f:
        print("--- FIRST 3 LINES ---")
        for _ in range(3):
            print(f.readline().strip())
    
    df = pd.read_csv(csv_path, skiprows=1, on_bad_lines='skip', low_memory=False)
    print("
--- COLUMNS ---")
    print(df.columns.tolist())
    
    print("
--- SAMPLE ROWS ---")
    tickers = ['AFG', 'CLR', 'OXY', 'PEMEX', 'KRE']
    # Check if 'Symbol' is in columns, if not try to find which one it is
    sym_col = 'Symbol' if 'Symbol' in df.columns else (df.columns[0] if len(df.columns) > 0 else None)
    
    if sym_col:
        mask = df[sym_col].isin(tickers)
        if mask.any():
            print(df[mask])
        else:
            # Check for partial matches or different case
            print("No exact matches, checking case-insensitive...")
            mask_lower = df[sym_col].astype(str).str.upper().isin([t.upper() for t in tickers])
            if mask_lower.any():
                print(df[mask_lower])
            else:
                print(f"Tickers {tickers} not found in column {sym_col}")
else:
    print("CSV not found")
