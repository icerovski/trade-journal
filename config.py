# config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load secrets from .env file (Token & IDs)
load_dotenv()

# --- PATHS ---
# We define the project root and data directory
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "portfolio.db"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# XML File Destinations (The "Source of Truth" files)
IBKR_PRICING_XML = DATA_DIR / "ibkr_pricing.xml"  # Stores Option 2 (Snapshot)
IBKR_YTD_XML = DATA_DIR / "ibkr_ytd.xml"          # Stores Option 3 (History)
IBKR_OPENING_XML = DATA_DIR / "ibkr_opening.xml"  # Stores Option 4 (Opening)

# --- IBKR API SECRETS ---
# You must set these in your .env file!
IBKR_TOKEN = os.environ.get("IBKR_TOKEN", "MISSING_TOKEN")
IBKR_QUERY_ID_NAV = os.environ.get("IBKR_QUERY_ID_NAV", "0")       # Maps to Option 2
IBKR_QUERY_ID_YTD = os.environ.get("IBKR_QUERY_ID_YTD", "0")       # Maps to Option 3
IBKR_QUERY_ID_OPENING = os.environ.get("IBKR_QUERY_ID_OPENING", "0") # Maps to Option 4

# --- FILTERS ---
EXCLUDED_TICKERS = {'EUR', 'USD', 'GBP'}  # Currencies to hide from the table
EXCLUDED_ASSET_CATEGORIES = {'CASH'}      # Categories to hide