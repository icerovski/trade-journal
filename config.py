# config.py
import sys
from pathlib import Path

# Get the folder where this code lives
BASE_DIR = Path(__file__).parent.resolve()

# Database File
DB_PATH = BASE_DIR / "simple_journal.db"

# Yahoo/Price Config
# (Assuming you still want to keep your separate price collector logic, 
# point this to wherever that database lives)
PRICES_DB_PATH = Path("C:/repos/price_collector/db/prices.db") 

# Risk Settings
DEFAULT_ATR_WINDOW = 21
RISK_REWARD_RATIO = 2.0