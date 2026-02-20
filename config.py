# config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Define Paths & Vaults
# Storage Hub (Database/Logs/Market Data)
DATA_DIR = Path(r"C:\Users\User\OneDrive\Accounts\HTC_EOOD\TradeJournalData")

# Configuration Vault (Secrets/Metadata)
CONFIG_VAULT = Path(r"C:\Users\User\OneDrive\Documents\Logos\.repos\trade-journal")

# 2. Load Environment Variables (Single Source of Truth)
# Prioritize the local repo .env, fallback to OneDrive vault
local_env = Path(".env")
onedrive_env = CONFIG_VAULT / ".env"

if local_env.exists():
    load_dotenv(local_env, override=True)
elif onedrive_env.exists():
    load_dotenv(onedrive_env, override=True)

# Ensure the data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 3. Database Path
DB_PATH = DATA_DIR / "trade_journal.db"

# 4. IBKR Configuration (from .env)
IBKR_TOKEN = os.environ.get("IBKR_TOKEN", "")
IBKR_QUERY_ID_TRADES = os.environ.get("IBKR_QUERY_ID_TRADES", "0")
IBKR_QUERY_ID_NAV = os.environ.get("IBKR_QUERY_ID_NAV", "0")
IBKR_QUERY_ID_OPEN_POSITIONS = os.environ.get("IBKR_QUERY_ID_OPEN_POSITIONS", "0")

# 5. File Paths
IBKR_TRADES_CSV = DATA_DIR / "trades_ytd.csv"
IBKR_NAV_CSV = DATA_DIR / "nav_lbd.csv"
IBKR_OPEN_POSITIONS_CSV = DATA_DIR / "open_positions_lbd.csv"
