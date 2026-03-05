# config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Define Configuration Vault (Bootstrap)
# Priority: System Environment Variable > Local Fallback
# This path is used to find the backup .env if the local one is missing.
CONFIG_VAULT = Path(os.environ.get("CONFIG_VAULT", r"C:\Users\User\OneDrive\Documents\Logos\.repos\trade-journal"))

# 2. Load Environment Variables (Single Source of Truth)
# We look for .env in the repo root first, then the Vault.
local_env = Path(".env")
onedrive_env = CONFIG_VAULT / ".env"

if local_env.exists():
    load_dotenv(local_env, override=True)
elif onedrive_env.exists():
    load_dotenv(onedrive_env, override=True)

# 3. Define Storage Hub (Database/Logs/Market Data)
# Priority: .env DATA_PATH > Local "data" folder
DATA_DIR = Path(os.environ.get("DATA_PATH", "data"))

# Sub-directories for organization
BASE_DATA_DIR = DATA_DIR / "data_base"
LBD_DIR = DATA_DIR / "last_business_day"

# Ensure directories exist
for d in [DATA_DIR, BASE_DATA_DIR, LBD_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 3. Database Path
DB_PATH = DATA_DIR / "trade_journal.db"

# 4. IBKR Configuration (from .env)
IBKR_TOKEN = os.environ.get("IBKR_TOKEN", "")
IBKR_QUERY_ID_TRADES = os.environ.get("IBKR_QUERY_ID_TRADES", "0")
IBKR_QUERY_ID_NAV = os.environ.get("IBKR_QUERY_ID_NAV", "0")
IBKR_QUERY_ID_OPEN_POSITIONS = os.environ.get("IBKR_QUERY_ID_OPEN_POSITIONS", "0")
IBKR_QUERY_ID_CONFIRMATIONS = os.environ.get("IBKR_QUERY_ID_CONFIRMATIONS", "0")

# 5. File Paths
TICKER_MAP_PATH = CONFIG_VAULT / "ticker_map.json"
PRICES_DB_PATH = DATA_DIR / "prices.db"
SNAPSHOTS_JSON = DATA_DIR / "snapshots.json"

# Snapshots (Last Business Day)
IBKR_NAV_CSV = LBD_DIR / "nav_lbd.csv"
IBKR_OPEN_POSITIONS_CSV = LBD_DIR / "open_positions_lbd.csv"
IBKR_CONFIRMATIONS_CSV = LBD_DIR / "confirmations_today.csv"

# Historical Ledger Files (within data_base)
IBKR_TRADES_CSV = BASE_DATA_DIR / "trades_ytd.csv"

# 6. Kids Fund Configuration
KIDS_ACCOUNT_ID = "U21692599"
KIDS_ASSETS = {
    "GROWTH": {"ticker": "SXR8.DE", "currency": "EUR"}, 
    "SAFETY": {"ticker": "IB01.L",  "currency": "USD"}   
}
KIDS_GLIDE_PATH = {
    0:  0.00,
    14: 0.00,
    15: 0.20,
    16: 0.40,
    17: 0.60,
    18: 1.00
}
