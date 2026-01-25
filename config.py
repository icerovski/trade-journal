# config.py
import os
import sys
from pathlib import Path

# Get the folder where this code lives
BASE_DIR = Path(__file__).parent.resolve()

# --- SECURITY: LOAD .ENV FILE ---
# This tiny function loads variables from .env without needing 'python-dotenv'
env_path = BASE_DIR / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            # Skip comments and empty lines
            if line.strip() and not line.startswith("#"):
                try:
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value.strip()
                except ValueError:
                    pass # Skip malformed lines

# --- CONFIGURATION ---

# Database File
DB_PATH = BASE_DIR / "simple_journal.db"

# Risk Settings
DEFAULT_ATR_WINDOW = 21
RISK_REWARD_RATIO = 2.0

# IBKR Configuration (Loaded from Environment)
# We use .get() so the script doesn't crash if keys are missing, 
# but we check validity in ibkr.py
IBKR_TOKEN = os.environ.get("IBKR_TOKEN", "MISSING_TOKEN")
IBKR_QUERY_ID_OPENING = os.environ.get("IBKR_QUERY_ID_OPENING", "0")
IBKR_QUERY_ID_YTD = os.environ.get("IBKR_QUERY_ID_YTD", "0")

# Temporary file paths
IBKR_OPENING_XML = BASE_DIR / "ibkr_opening.xml"
IBKR_YTD_XML = BASE_DIR / "ibkr_ytd.xml"