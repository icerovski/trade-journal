# config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Load Environment Variables
# We use override=True so that .env values take precedence over system env vars
load_dotenv(override=True)

# 2. Define Data Directory
# We look for 'DATA_PATH' in the .env file. 
# If not found, we default to a local "data" folder in the project directory.
env_data_path = os.environ.get("DATA_PATH")

if env_data_path:
    DATA_DIR = Path(env_data_path)
else:
    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data"

# Ensure the directory exists (create it if missing)
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    print(f"⚠️ Warning: Could not create data directory at {DATA_DIR}: {e}")

# 3. Database Path
DB_PATH = DATA_DIR / "simple_journal.db"

# 4. IBKR Configuration
IBKR_TOKEN = os.environ.get("IBKR_TOKEN", "")
IBKR_QUERY_ID_TRADES = os.environ.get("IBKR_QUERY_ID_TRADES", "0")
IBKR_QUERY_ID_NAV = os.environ.get("IBKR_QUERY_ID_NAV", "0")
IBKR_QUERY_ID_OPEN_POSITIONS = os.environ.get("IBKR_QUERY_ID_OPEN_POSITIONS", "0")

# 5. XML File Paths
IBKR_TRADES_CSV = DATA_DIR / "trades.csv"
IBKR_NAV_XML = DATA_DIR / "ibkr_nav.xml"
IBKR_OPEN_POSITIONS_CSV = DATA_DIR / "open_positions.csv"