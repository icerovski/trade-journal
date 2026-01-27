# config.py
import os
import sys
from pathlib import Path

# Get the folder where this code lives
BASE_DIR = Path(__file__).parent.resolve()

# --- 1. LOAD .ENV FILE ---
env_path = BASE_DIR / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                try:
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value.strip()
                except ValueError:
                    pass

# --- 2. DATA DIRECTORY SETUP ---
custom_path = os.environ.get("JOURNAL_DATA_DIR")
if custom_path:
    DATA_DIR = Path(custom_path)
    if not DATA_DIR.exists():
        print(f"⚠️  Warning: Custom data path not found: {DATA_DIR}")
        print("Creating it now...")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(exist_ok=True)

# --- 3. CONFIGURATION ---

# Database File
DB_PATH = DATA_DIR / "simple_journal.db"

# Risk Settings
DEFAULT_ATR_WINDOW = 21
RISK_REWARD_RATIO = 2.0

# IBKR Configuration
IBKR_TOKEN = os.environ.get("IBKR_TOKEN", "MISSING_TOKEN")
IBKR_QUERY_ID_OPENING = os.environ.get("IBKR_QUERY_ID_OPENING", "0")
IBKR_QUERY_ID_YTD = os.environ.get("IBKR_QUERY_ID_YTD", "0")
IBKR_QUERY_ID_NAV = os.environ.get("IBKR_QUERY_ID_NAV", "0")

# XML File Paths
IBKR_OPENING_XML = DATA_DIR / "ibkr_opening.xml"
IBKR_YTD_XML = DATA_DIR / "ibkr_ytd.xml"
IBKR_PRICING_XML = DATA_DIR / "ibkr_pricing.xml"
IBKR_NAV_XML = DATA_DIR / "ibkr_nav.xml"

# --- 4. VIEW SETTINGS ---
EXCLUDED_ASSET_CATEGORIES = ["OPT", "BOND", "BILL", "WAR", "CASH", "FOREX", "FX", "CURRENCY"]
EXCLUDED_TICKERS = ["EUR.USD", "USD.EUR"]