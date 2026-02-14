import requests
import xml.etree.ElementTree as ET
import pandas as pd
from pathlib import Path
from datetime import datetime
from dateutil.parser import parse
import csv
import io
import shutil

from config import (
    IBKR_TRADES_CSV,
    DATA_DIR
)
from db import add_trade, trade_exists

# --- 1. MASTER DOWNLOADER (Generic) ---
def download_flex_report(query_id, output_path, force_download=False):
    """
    Downloads a Flex Report (XML or CSV) and saves it to output_path.
    Returns the Path object if successful, or None if failed.
    Does NOT parse the final report (because it might be CSV or XML).
    """
    from config import IBKR_TOKEN
    file_path = Path(output_path)
    
    # A. Local Cache Check
    if not force_download and file_path.exists():
        try:
            file_date = pd.Timestamp(file_path.stat().st_mtime, unit='s').date()
            if file_date == pd.Timestamp.now().date():
                # print(f"📂 Found fresh local file: {file_path.name}")
                return file_path
        except Exception:
            pass 

    # B. Credential Check
    if query_id == "0" or not IBKR_TOKEN:
        print(f"❌ Error: IBKR Credentials/Query ID missing in .env (ID: {query_id})")
        return None
        
    # C. Step 1: Send Request (Always returns XML)
    url = f"https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={query_id}&v=3"
    print(f"⏳ Requesting report from IBKR (ID: {query_id})...")
    
    try:
        resp = requests.get(url)
        
        # Check if Step 1 response is valid XML
        if not resp.content.strip().startswith(b"<"):
            print(f"⚠️ IBKR Handshake Error: {resp.text}")
            return None

        root = ET.fromstring(resp.content)
        
        if root.find("Status") is not None and root.find("Status").text == "Success":
            code = root.find("ReferenceCode").text
            base_url = root.find("Url").text
            dl_url = f"{base_url}?q={code}&t={IBKR_TOKEN}&v=3"
            
            # Wait for generation
            import time
            time.sleep(1)
            
            # D. Step 2: Download Actual Report (CSV or XML)
            report_resp = requests.get(dl_url)
            if report_resp.status_code == 200:
                with open(file_path, "wb") as f:
                    f.write(report_resp.content)
                return file_path
            else:
                print(f"❌ Download Error: {report_resp.status_code}")
        else:
            err = root.find("ErrorMessage")
            print(f"❌ IBKR API Error: {err.text if err is not None else 'Unknown'}")
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        
    return None


# --- 2. CSV TRADE PARSER (New!) ---
def parse_csv_trades(file_path):
    """
    Reads the IBKR CSV format and saves to DB.
    """
    if not file_path or not Path(file_path).exists():
        return

    print(f"📂 Parsing CSV: {file_path}...")
    
    try:
        # IBKR CSVs usually have a header row. 
        # We assume standard headers based on your selection.
        df = pd.read_csv(file_path)
        
        # Clean column names (remove spaces)
        df.columns = df.columns.str.strip()
        
        # Filter for actual trades (DataDiscriminator is often 'Order')
        # Adjust this filter based on your specific CSV structure if needed.
        # Common valid rows have a proper 'Symbol' and 'Buy/Sell'
        if 'Symbol' in df.columns:
            df = df.dropna(subset=['Symbol'])
        
        count = 0
        
        for _, row in df.iterrows():
            # 1. Extract Fields (Handle typical IBKR column names)
            ticker = row.get('Symbol')
            side = str(row.get('Buy/Sell', '')).upper()
            date_raw = str(row.get('TradeDate', '')).replace('-', '')
            
            # Skip rows that aren't trades
            if not ticker or side not in ['BUY', 'SELL']:
                continue

            # 2. Date Parsing
            try:
                date_str = pd.to_datetime(date_raw).strftime("%Y-%m-%d")
            except:
                continue

            # 3. Numeric & Meta Fields
            try:
                qty = float(row.get('Quantity', 0))
                price = float(row.get('TradePrice', 0))
                asset = row.get('AssetClass', 'STK')
                desc = row.get('Description', '')
                
                # Metadata for Ticker Mapping & Position Calculation
                conid = str(row.get('Conid', ''))
                exchange = str(row.get('ListingExchange', ''))
                currency = str(row.get('CurrencyPrimary', ''))
                underlying = str(row.get('UnderlyingSymbol', ''))

                # Create Unique ID
                ib_id = row.get('IBOrderID') or row.get('TradeID')
                if ib_id:
                    ext_id = str(ib_id)
                else:
                    ext_id = f"MAN-{date_str}-{ticker}-{price}-{qty}"

            except ValueError:
                continue

            # 4. Save to DB
            if trade_exists(ext_id):
                continue

            add_trade(
                date=date_str, ticker=ticker, side=side, 
                quantity=abs(qty), price=price, asset_category=asset, 
                notes=f"IBKR CSV Import {datetime.now().date()}",
                source="IBKR_CSV",
                external_id=ext_id,
                description=desc,
                conid=conid,
                listing_exchange=exchange,
                currency=currency,
                underlying_symbol=underlying
            )
            count += 1
            
        print(f"✅ Successfully imported {count} new trades from CSV.")
        
    except Exception as e:
        print(f"❌ CSV Parsing Error: {e}")
        # Debug helper: print columns if failed
        try:
            print(f"   Available Columns: {list(pd.read_csv(file_path).columns)}")
        except:
            pass


# --- 3. WRAPPER FUNCTIONS ---

def fetch_trade_history(days=365):
    """
    Downloads the Trade CSV and imports it.
    """
    from config import IBKR_QUERY_ID_TRADES
    print(f"📥 Fetching Trade History (CSV)...")
    
    # 1. Download (Saves to trades.csv)
    # Note: Ensure IBKR_TRADES_CSV ends in .csv in config.py
    file_path = download_flex_report(IBKR_QUERY_ID_TRADES, IBKR_TRADES_CSV, force_download=True)
    
    # 2. Parse (As CSV)
    if file_path:
        parse_csv_trades(file_path)

def import_trades_from_file(filename):
    """
    Manual import override.
    """
    file_path = Path(filename)
    if not file_path.exists():
        file_path = DATA_DIR / filename
        
    if str(filename).endswith('.xml'):
        # Legacy XML support if needed
        tree = ET.parse(file_path)
        # Call the old parse_and_store_trades(tree.getroot()) if you still have XMLs
        # (For now assuming only CSV moving forward)
        print("⚠️ XML import deprecated for trades. Please use CSV.")
    else:
        parse_csv_trades(file_path)

def sync_ibkr_trades():
    """
    Incremental Sync Logic:
    1. Always check for previous year's Full Year file (e.g., 2025_FY.csv).
    2. Archive existing YTD file for the current year.
    3. Download fresh YTD file.
    4. Process both files. The trade_exists() check ensures no duplicates.
    """
    from config import IBKR_QUERY_ID_TRADES
    
    now = datetime.now()
    current_year = now.year
    prev_year = current_year - 1
    
    archive_dir = DATA_DIR / "Archive"
    archive_dir.mkdir(exist_ok=True)
    
    print(f"🔄 Starting Sync for {current_year} (including {prev_year} history)...")

    # 1. Process Historical Data (Migration/Fill Gaps)
    prev_fy_path = DATA_DIR / f"{prev_year}_FY.csv"
    if prev_fy_path.exists():
        print(f"📂 Checking historical data for gaps: {prev_fy_path.name}")
        parse_csv_trades(prev_fy_path)
    
    # 2. Archive old YTD if it exists
    ytd_filename = f"{current_year}_YTD.csv"
    ytd_path = DATA_DIR / ytd_filename
    
    if ytd_path.exists():
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        archive_path = archive_dir / f"{current_year}_YTD_{timestamp}.csv"
        print(f"📦 Archiving current YTD to {archive_path.name}")
        shutil.move(str(ytd_path), str(archive_path))

    # 3. Download Fresh YTD
    print(f"📥 Downloading fresh YTD for {current_year}...")
    downloaded_path = download_flex_report(IBKR_QUERY_ID_TRADES, ytd_path, force_download=True)
    
    if not downloaded_path:
        print("❌ Failed to download fresh YTD data.")
        return

    # 4. Process new YTD
    print(f"📂 Processing current year data: {ytd_filename}")
    parse_csv_trades(downloaded_path)
    
    print("✅ Sync Complete.")
