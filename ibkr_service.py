# ibkr_service.py
import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from config import IBKR_TOKEN, IBKR_QUERY_ID, IBKR_XML_PATH
from db import add_trade, trade_exists

def fetch_ibkr_xml():
    """
    Step 1: Fetch data from IBKR and save to local XML file.
    Does NOT update the database.
    """
    print("⏳ Connecting to IBKR Flex Service...")
    
    # 1. Send Request
    req_url = f"https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={IBKR_QUERY_ID}&v=3"
    try:
        response = requests.get(req_url)
        response.raise_for_status()
        
        # Parse Reference Code
        root = ET.fromstring(response.content)
        if root.find('Status').text != 'Success':
            print(f"❌ Error from IBKR: {root.find('ErrorMessage').text}")
            return False

        ref_code = root.find('ReferenceCode').text
        print(f"✅ Request Accepted. Reference: {ref_code}")
        
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        return False

    # 2. Wait for Report Generation (IBKR requires a delay)
    print("⏳ Waiting for report generation (approx 10s)...")
    time.sleep(10)

    # 3. Get Actual Report
    fetch_url = f"https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement?q={ref_code}&t={IBKR_TOKEN}&v=3"
    try:
        report_resp = requests.get(fetch_url)
        report_resp.raise_for_status()
        
        # Save to File
        with open(IBKR_XML_PATH, 'wb') as f:
            f.write(report_resp.content)
            
        print(f"✅ XML Saved successfully to: {IBKR_XML_PATH}")
        return True

    except Exception as e:
        print(f"❌ Failed to download report: {e}")
        return False

def parse_and_import_xml():
    """
    Step 2: Read local XML file and import trades to DB.
    """
    if not IBKR_XML_PATH.exists():
        print(f"❌ File not found: {IBKR_XML_PATH}")
        print("   Please 'Fetch Data' first.")
        return

    print(f"📂 Parsing {IBKR_XML_PATH.name}...")
    
    try:
        tree = ET.parse(IBKR_XML_PATH)
        root = tree.getroot()
        
        # Standard IBKR Flex Query Structure: FlexStatements -> FlexStatement -> Trades -> Trade
        trades_imported = 0
        trades_skipped = 0
        
        # We look for any 'Trade' tag in the document
        for trade in root.iter('Trade'):
            try:
                # Extract Fields (Adjust attribute names if your Flex Query is customized)
                ticker = trade.attrib.get('symbol')
                date_raw = trade.attrib.get('tradeDate') # Usually YYYYMMDD
                side_raw = trade.attrib.get('buySell')   # BUY or SELL
                qty = abs(float(trade.attrib.get('quantity', 0)))
                price = float(trade.attrib.get('tradePrice', 0))
                
                # Normalize Date (20250624 -> 2025-06-24)
                if len(date_raw) == 8:
                    date_fmt = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
                else:
                    date_fmt = date_raw

                # Normalize Side
                side = side_raw.upper()

                # Duplicate Check
                if trade_exists(date_fmt, ticker, side, qty, price):
                    trades_skipped += 1
                    continue

                # Add to DB
                add_trade(date_fmt, ticker, side, qty, price, notes="IBKR Import")
                trades_imported += 1

            except Exception as e:
                print(f"⚠️ Skipped a row due to error: {e}")
                continue

        print(f"\n📊 Import Summary:")
        print(f"   ✅ Imported: {trades_imported}")
        print(f"   ⏭️  Skipped (Duplicates): {trades_skipped}")

    except Exception as e:
        print(f"❌ Failed to parse XML: {e}")