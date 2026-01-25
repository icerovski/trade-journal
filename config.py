# config.py
import sys
from pathlib import Path

# Get the folder where this code lives
BASE_DIR = Path(__file__).parent.resolve()

# Database File
DB_PATH = BASE_DIR / "simple_journal.db"

# Risk Settings
DEFAULT_ATR_WINDOW = 21
RISK_REWARD_RATIO = 2.0

# IBKR Configuration
IBKR_TOKEN = "179255757524928752008505"

# Query 1: "Open Positions" (Snapshot)
# Configure in IBKR: 'Open Positions' section.
IBKR_QUERY_ID_OPENING = "1383737"

# Query 2: "Trades" (Activity)
# Configure in IBKR: 'Trades' section.
IBKR_QUERY_ID_YTD = "1056708"

# Temporary file paths
IBKR_OPENING_XML = BASE_DIR / "ibkr_opening.xml"
IBKR_YTD_XML = BASE_DIR / "ibkr_ytd.xml"