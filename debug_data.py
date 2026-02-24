import pandas as pd
from pathlib import Path
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from services.ibkr_parser import IBKRParser
from data_loader import DataLoader

nav_path = r"C:/Users/User/OneDrive/Accounts/HTC_EOOD/TradeJournalData/last_business_day/nav_lbd.csv"
pos_path = r"C:/Users/User/OneDrive/Accounts/HTC_EOOD/TradeJournalData/last_business_day/open_positions_lbd.csv"

print("--- NAV PARSING ---")
try:
    total, accts, date = IBKRParser.parse_nav_csv(nav_path)
    print(f"Total: {total}")
    print(f"Date: {date}")
    print(f"Accounts Found: {len(accts)}")
except Exception as e:
    print(f"NAV Error: {e}")

print("\n--- POSITIONS PARSING ---")
try:
    data, r_date = DataLoader.get_broker_verified_snapshot()
    print(f"Positions Found: {len(data)}")
    print(f"Report Date: {r_date}")
    if data:
        first_key = list(data.keys())[0]
        print(f"Sample: {data[first_key]['Symbol']} - Qty: {data[first_key]['Qty']}")
except Exception as e:
    print(f"Positions Error: {e}")
