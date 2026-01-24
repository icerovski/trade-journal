# ibkr.py
import requests
import time
import xml.etree.ElementTree as ET
from db import add_trade, trade_exists
from config import IBKR_TOKEN, IBKR_QUERY_ID, IBKR_REPORT_PATH

def fetch_and_import_flex():
    """
    Orchestrates the fetch, download, and database import.
    """
    if "YOUR_LONG_TOKEN" in IBKR_TOKEN:
        print("❌ Error: Please update IBKR_TOKEN in config.py")
        return

    print("--- Connecting to IBKR ---")
    
    # 1. Request Report
    base_url = "https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
    req_url = f"{base_url}?t={IBKR_TOKEN}&q={IBKR_QUERY_ID}&v=3"
    
    try:
        print("Requesting report generation...")
        response = requests.get(req_url)
        
        if "ErrorCode" in response.text:
            print(f"❌ API Error: {response.text}")
            return

        root = ET.fromstring(response.content)
        code_elem = root.find('ReferenceCode')
        if code_elem is None:
            print("❌ Error: No ReferenceCode returned.")
            return
            
        reference_code = code_elem.text
        print(f"✅ Report initiated (Ref: {reference_code}). Waiting 10s...")
        
        time.sleep(10)

        # 2. Download Report
        dl_url = "https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"
        dl_req = f"{dl_url}?q={reference_code}&t={IBKR_TOKEN}&v=3"
        
        file_response = requests.get(dl_req)
        
        if file_response.status_code != 200:
            print("❌ Failed to download report.")
            return
            
        with open(IBKR_REPORT_PATH, 'wb') as f:
            f.write(file_response.content)
            
        print("✅ XML downloaded. Scanning for new trades...")
        scan_and_import_xml(IBKR_REPORT_PATH)
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")

def scan_and_import_xml(file_path):
    """
    Scans the XML, checks for unique IDs, and adds only new trades.
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        trades = root.findall(".//Trade")
        
        if not trades:
            print("ℹ️  No trades found in this report.")
            return

        added_count = 0
        skipped_count = 0

        for t in trades:
            # 1. Extract the Unique ID
            # IBKR uses 'tradeID' for executions. 
            # If checking cash transactions, you might use 'transactionID'.
            external_id = t.get('tradeID') or t.get('ibOrderId')

            # 2. CHECK: Does this trade already exist?
            if external_id and trade_exists(external_id):
                skipped_count += 1
                continue

            # 3. Extract Data
            ticker = t.get('symbol')
            raw_date = t.get('tradeDate') # Format usually YYYYMMDD
            side = t.get('buySell')
            qty = t.get('quantity')
            price = t.get('tradePrice')

            # Validation
            if not (ticker and raw_date and side and qty and price):
                continue
            
            # Format Date
            if len(raw_date) == 8:
                formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            else:
                formatted_date = raw_date

            # Clean Data
            clean_qty = abs(float(qty))
            
            # 4. Add to DB
            add_trade(
                date=formatted_date, 
                ticker=ticker, 
                side=side, 
                quantity=clean_qty, 
                price=price, 
                notes="IBKR Import",
                external_id=external_id
            )
            added_count += 1

        print(f"\nSummary: {added_count} new trades added. {skipped_count} duplicates skipped.")
        
    except Exception as e:
        print(f"❌ Error parsing XML: {e}")