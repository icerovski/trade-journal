# config.py
import sys
from pathlib import Path

# Get the folder where this code lives
BASE_DIR = Path(__file__).parent.resolve()

# Database File
DB_PATH = BASE_DIR / "simple_journal.db"

# IBKR Configuration
IBKR_XML_PATH = BASE_DIR / "ibrk_import.xml"
IBKR_TOKEN = "179255757524928752008505"
IBKR_QUERY_ID = "1056708"

# Risk Settings
DEFAULT_ATR_WINDOW = 21
RISK_REWARD_RATIO = 2.0