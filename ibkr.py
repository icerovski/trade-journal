import requests
import xml.etree.ElementTree as ET
import pandas as pd
from pathlib import Path
from datetime import datetime

from config import (
    IBKR_TRADES_CSV,
    DATA_DIR
)
from ibkr_parser import IBKRParser
from logger import logger, log_system_milestone

# Log the recent improvement
log_system_milestone("Separated Networking (ibkr.py) from Parsing (ibkr_parser.py)")

# --- 1. MASTER DOWNLOADER (Generic) ---
def download_flex_report(query_id, output_path, force_download=False):
    """
    Downloads a Flex Report (XML or CSV) and saves it to output_path.
    """
    from config import IBKR_TOKEN
    file_path = Path(output_path)
    
    # Local Cache Check
    if not force_download and file_path.exists():
        try:
            file_date = pd.Timestamp(file_path.stat().st_mtime, unit='s').date()
            if file_date == pd.Timestamp.now().date():
                return file_path
        except Exception:
            pass 

    if query_id == "0" or not IBKR_TOKEN:
        logger.error(f"IBKR Credentials/Query ID missing in .env (ID: {query_id})")
        return None
        
    url = f"https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={query_id}&v=3"
    logger.info(f"Requesting report from IBKR (ID: {query_id})...")
    
    try:
        resp = requests.get(url)
        if not resp.content.strip().startswith(b"<"):
            logger.warning(f"IBKR Handshake Error: {resp.text}")
            return None

        root = ET.fromstring(resp.content)
        if root.find("Status") is not None and root.find("Status").text == "Success":
            code = root.find("ReferenceCode").text
            base_url = root.find("Url").text
            dl_url = f"{base_url}?q={code}&t={IBKR_TOKEN}&v=3"
            
            import time
            time.sleep(1)
            
            report_resp = requests.get(dl_url)
            if report_resp.status_code == 200:
                with open(file_path, "wb") as f:
                    f.write(report_resp.content)
                return file_path
    except Exception as e:
        logger.error(f"Connection Error: {e}")
    return None

# --- 2. WRAPPERS ---

def sync_ibkr_trades():
    """Main entry point for syncing - expected by tests."""
    fetch_trade_history()
    process_local_csvs()

def fetch_trade_history():
    from config import IBKR_QUERY_ID_TRADES
    return download_flex_report(IBKR_QUERY_ID_TRADES, IBKR_TRADES_CSV, force_download=True)

def fetch_open_positions():
    from config import IBKR_QUERY_ID_OPEN_POSITIONS, IBKR_OPEN_POSITIONS_CSV
    return download_flex_report(IBKR_QUERY_ID_OPEN_POSITIONS, IBKR_OPEN_POSITIONS_CSV, force_download=True)

def download_trade_report(year=None, is_ytd=True):
    from config import IBKR_QUERY_ID_TRADES
    now = datetime.now()
    year = year or now.year
    suffix = "YTD" if is_ytd else "FY"
    output_path = DATA_DIR / f"{year}_{suffix}.csv"
    return download_flex_report(IBKR_QUERY_ID_TRADES, output_path, force_download=True)

def process_local_csvs():
    """Incorporate all found CSVs into DB."""
    if IBKR_TRADES_CSV.exists():
        logger.info(f"Parsing: {IBKR_TRADES_CSV.name}")
        IBKRParser.parse_trade_csv(IBKR_TRADES_CSV)
    
    for f in list(DATA_DIR.glob("*_FY.csv")) + list(DATA_DIR.glob("*_YTD.csv")):
        logger.info(f"Parsing: {f.name}")
        IBKRParser.parse_trade_csv(f)
    
    logger.info("Database up to date.")
