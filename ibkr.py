import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from dateutil.parser import parse
from pathlib import Path

from config import (
    IBKR_TOKEN, 
    IBKR_QUERY_ID_TRADES, 
    IBKR_TRADES_XML
)
from db import add_trade, trade_exists

# --- 1. GENERIC DOWNLOADER ---
def download_flex_report(query_id):
    """
    Generic helper to download any Flex Query by ID.
    Returns the XML Root Element or None.
    """
    if query_id == "0" or not IBKR_TOKEN:
        print("❌ Error: IBKR Credentials/Query ID missing in .env")
        return None
        
    url = f"https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={query_id}&v=3"
    
    print(f"⏳ Requesting report (ID: {query_id})...")
    try:
        resp = requests.get(url)
        if resp.status_code != 200:
            print(f"❌ HTTP Error: {resp.status_code}")
            return None
            
        root = ET.fromstring(resp.content)
        if root.find("Status") is not None and root.find("Status").text == "Success":
            code = root.find("ReferenceCode").text
            base_url = root.find("Url").text
            dl_url = f"{base_url}?q={code}&t={IBKR_TOKEN}&v=3"
            
            # Wait for generation (IBKR async)
            import time
            time.sleep(1)
            
            report_resp = requests.get(dl_url)
            if report_resp.status_code == 200:
                return ET.fromstring(report_resp.content)
            else:
                print(f"❌ Download Error: {report_resp.status_code}")
        else:
            err = root.find("ErrorMessage")
            print(f"❌ IBKR API Error: {err.text if err is not None else 'Unknown'}")
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        
    return None

# --- 2. TRADE HISTORY IMPORT (Legacy DB) ---

def parse_and_store_trades(root):
    """
    Parses 'Trade' elements from the XML and stores them in the SQLite DB.
    """
    count = 0
    trades = root.findall(".//Trade")
    print(f"🔍 Found {len(trades)} trades in XML...")

    for t in trades:
        # 1. Date
        raw_date = t.get('tradeDate')
        if not raw_date: continue
        
        try:
            # Handle YYYYMMDD
            if len(raw_date) == 8 and raw_date.isdigit():
                date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            else:
                date_str = parse(raw_date).strftime("%Y-%m-%d")
        except:
            continue

        # 2. ID & Existence Check
        ext_id = t.get('tradeID') or t.get('ibOrderId')
        # Fallback ID for robustness
        if not ext_id: 
            ext_id = f"MAN-{date_str}-{t.get('symbol')}-{t.get('tradePrice')}"
        
        if trade_exists(ext_id): continue

        # 3. Attributes
        ticker = t.get('symbol')
        side = t.get('buySell')
        qty = float(t.get('quantity', 0))
        price = float(t.get('tradePrice', 0))
        asset = t.get('assetCategory', 'STK')
        desc = t.get('description') or t.get('listingExchange')

        if not ticker or not side: continue

        add_trade(
            date=date_str, ticker=ticker, side=side, 
            quantity=abs(qty), price=price, asset_category=asset, 
            notes=f"IBKR Import {datetime.now().date()}",
            source="IBKR_XML",
            external_id=ext_id,
            description=desc
        )
        count += 1
    
    print(f"✅ Successfully imported {count} new trades.")

def fetch_trade_history(days=365):
    """
    Downloads the Trade History Flex Query and imports it.
    """
    print(f"📥 Fetching Trade History (Last {days} days)...")
    
    # 1. Download
    root = download_flex_report(IBKR_QUERY_ID_TRADES)
    if not root: return

    # 2. Save XML for backup
    try:
        tree = ET.ElementTree(root)
        tree.write(IBKR_TRADES_XML)
        print(f"💾 Saved XML backup to {IBKR_TRADES_XML}")
    except Exception as e:
        print(f"⚠️ Could not save backup XML: {e}")

    # 3. Parse & Import
    parse_and_store_trades(root)

def import_trades_from_file(filename):
    """
    Imports trades from a local XML file (e.g., 'trades_manual.xml').
    """
    file_path = Path(filename)
    if not file_path.exists():
        # Try looking in data dir
        from config import DATA_DIR
        file_path = DATA_DIR / filename
        
    if not file_path.exists():
        print(f"❌ File not found: {filename}")
        return

    print(f"📂 Importing from {file_path}...")
    try:
        tree = ET.parse(file_path)
        parse_and_store_trades(tree.getroot())
    except Exception as e:
        print(f"❌ Error parsing file: {e}")