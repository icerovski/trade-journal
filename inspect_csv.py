import pandas as pd
import os

csv_path = r'C:\Users\User\OneDrive\Accounts\HTC_EOOD\TradeJournalData\open_positions_lbd.csv'

if os.path.exists(csv_path):
    print(f"File exists: {csv_path}")
    # Read first 5 lines to see headers
    with open(csv_path, 'r') as f:
        for _ in range(5):
            print(f.readline().strip())
    
    # Try reading with pandas
    try:
        df = pd.read_csv(csv_path, on_bad_lines='skip', low_memory=False)
        print("
Pandas Columns:", df.columns.tolist())
    except Exception as e:
        print(f"Error reading CSV: {e}")
else:
    print(f"File not found: {csv_path}")
