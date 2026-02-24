import pandas as pd
from core.portfolio_manager import PortfolioManager
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

pm = PortfolioManager()
print("Starting get_dashboard_df test...")
df = pm.get_dashboard_df(asset_class_filter='STK', total_nav=1848981.91)
print(f"DF Rows: {len(df)}")
if not df.empty:
    print(df.head())
else:
    print("DataFrame is empty!")
