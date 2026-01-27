# ibkr.py
import requests
import time
import xml.etree.ElementTree as ET
from config import (
    IBKR_TOKEN,
    IBKR_QUERY_ID_NAV,
    IBKR_QUERY_ID_YTD,
    IBKR_QUERY_ID_OPENING,
    IBKR_PRICING_XML,
    IBKR_YTD_XML,
    IBKR_OPENING_XML
)

def download_flex_report(query_id, save_path):
    """
    Generic function to download ANY Flex Query and save it to a file.
    Returns True if successful, False otherwise.
    """
    # 1. Validation
    if "MISSING" in IBKR_TOKEN or query_id == "0":
        print("❌ Error: IBKR Token or Query ID is missing in .env")
        return False

    print(f"⏳ Connecting to IBKR (Query {query_id})...")
    
    # 2. Initiate Generation Request
    base_url = "https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
    req_url = f"{base_url}?t={IBKR_TOKEN}&q={query_id}&v=3"
    
    try:
        response = requests.get(req_url)
        
        # Check for API errors immediately
        if "ErrorCode" in response.text:
            root = ET.fromstring(response.content)
            code = root.findtext("ErrorCode")
            msg = root.findtext("ErrorMessage")
            print(f"❌ IBKR API Error {code}: {msg}")
            return False

        # 3. Get Reference Code
        root = ET.fromstring(response.content)
        code_elem = root.find('ReferenceCode')
        if code_elem is None:
            print("❌ Error: No ReferenceCode returned.")
            return False
            
        reference_code = code_elem.text
        print(f"✅ Report initiated (Ref: {reference_code}). Waiting 5s...")
        
        # 4. Wait for IBKR to generate the file
        # (Small reports take 1-2s, larger ones might take 5-10s)
        time.sleep(5)

        # 5. Download the Actual File
        dl_url = "https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"
        dl_req = f"{dl_url}?q={reference_code}&t={IBKR_TOKEN}&v=3"
        
        file_response = requests.get(dl_req)
        
        if file_response.status_code != 200:
            print("❌ Failed to download report.")
            return False
        
        # 6. Save to Disk
        with open(save_path, 'wb') as f:
            f.write(file_response.content)
            
        print(f"✅ File saved to: {save_path.name}")
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

# --- WRAPPER FUNCTIONS (Called by main.py) ---

def fetch_latest_prices():
    """Option 2: Downloads NAV & Prices Snapshot"""
    print("\n--- Fetching Snapshot ---")
    return download_flex_report(IBKR_QUERY_ID_NAV, IBKR_PRICING_XML)

def fetch_ytd_trades():
    """Option 3: Downloads Trade History (for FIFO dates)"""
    print("\n--- Fetching Trade History ---")
    return download_flex_report(IBKR_QUERY_ID_YTD, IBKR_YTD_XML)

def fetch_opening_balance():
    """Option 4: Downloads Opening Balance (Archive)"""
    print("\n--- Fetching Opening Balance ---")
    return download_flex_report(IBKR_QUERY_ID_OPENING, IBKR_OPENING_XML)