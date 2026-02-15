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
                return file_path
        except Exception:
            pass 

    # B. Credential Check
    if query_id == "0" or not IBKR_TOKEN:
        print(f"ERROR: IBKR Credentials/Query ID missing in .env (ID: {query_id})")
        return None
        
    # C. Step 1: Send Request (Always returns XML)
    url = f"https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={query_id}&v=3"
    print(f"-> Requesting report from IBKR (ID: {query_id})...")
    
    try:
        resp = requests.get(url)
        
        # Check if Step 1 response is valid XML
        if not resp.content.strip().startswith(b"<"):
            print(f"WARNING: IBKR Handshake Error: {resp.text}")
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
                print(f"ERROR: Download Error: {report_resp.status_code}")
        else:
            err = root.find("ErrorMessage")
            print(f"ERROR: IBKR API Error: {err.text if err is not None else 'Unknown'}")
            
    except Exception as e:
        print(f"ERROR: Connection Error: {e}")
        
    return None


# --- 2. CSV TRADE PARSER ---
def parse_csv_trades(file_path):
    """
    Reads the IBKR CSV format and saves to DB.
    """
    if not file_path or not Path(file_path).exists():
        return

    print(f"-> Parsing CSV: {file_path}...")
    
    try:
        # IBKR CSVs usually have a header row. 
        df = pd.read_csv(file_path)
        
        # Clean column names (remove spaces)
        df.columns = df.columns.str.strip()
        
        # Filter for actual trades
        if 'Symbol' in df.columns:
            df = df.dropna(subset=['Symbol'])
        
        count = 0
        
        for _, row in df.iterrows():
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
            
        print(f"SUCCESS: Successfully imported {count} new trades from CSV.")
        
    except Exception as e:
        print(f"ERROR: CSV Parsing Error: {e}")


# --- 3. WRAPPER FUNCTIONS ---

def fetch_trade_history(days=365):
    """
    Downloads the Trade CSV (Restored working default).
    """
    from config import IBKR_QUERY_ID_TRADES
    print(f"-> Fetching Current Year YTD into trades.csv...")
    file_path = download_flex_report(IBKR_QUERY_ID_TRADES, IBKR_TRADES_CSV, force_download=True)
    return file_path

def download_trade_report(year=None, is_ytd=True):
    """
    Downloads a trade report for a specific year.
    """
    from config import IBKR_QUERY_ID_TRADES
    now = datetime.now()
    if year is None:
        year = now.year
    
    suffix = "YTD" if is_ytd else "FY"
    filename = f"{year}_{suffix}.csv"
    output_path = DATA_DIR / filename

    print(f"-> Downloading {filename} from IBKR...")
    downloaded = download_flex_report(IBKR_QUERY_ID_TRADES, output_path, force_download=True)
    if downloaded:
        print(f"SUCCESS: {filename} saved to data folder.")
    return downloaded

def import_trades_from_file(filename):
    """
    Manual import override.
    """
    file_path = Path(filename)
    if not file_path.exists():
        file_path = DATA_DIR / filename
    parse_csv_trades(file_path)

def migrate_opening_positions():
    """
    Migrates data from open_positions.csv if it exists in Archive.
    """
    file_path = DATA_DIR / "Archive" / "open_positions.csv"
    if not file_path.exists():
        return

    print(f"-> Migrating opening positions from {file_path.name}...")
    try:
        # Using cp1251 encoding to handle potential cyrillic characters
        df = pd.read_csv(file_path, sep=';', encoding='cp1251')
        df.columns = df.columns.str.strip()
        
        count = 0
        for _, row in df.iterrows():
            # Skip header or invalid quantity
            try:
                qty = float(row.get('Quantity', 0))
            except (ValueError, TypeError):
                continue
                
            # Use OpenDateTime for specific lots, otherwise ReportDate for SUMMARY row
            date_raw = row.get('OpenDateTime')
            if pd.isna(date_raw) or str(date_raw).strip() == "" or str(date_raw).strip() == "OpenDateTime":
                if str(row.get('LevelOfDetail', '')).upper() == 'SUMMARY':
                    date_raw = row.get('ReportDate')
                else:
                    continue
            
            if pd.isna(date_raw) or str(date_raw).strip() == "":
                continue
                
            ticker = row.get('Symbol')
            price = float(row.get('OpenPrice', 0))
            conid = str(row.get('Conid', ''))
            ext_id = f"OPEN-{ticker}-{conid}-{date_raw}-{qty}"
            
            if trade_exists(ext_id):
                continue
                
            try:
                date_str = pd.to_datetime(date_raw, dayfirst=True).strftime("%Y-%m-%d")
            except:
                continue

            add_trade(
                date=date_str, ticker=ticker, side='BUY',
                quantity=qty, price=price,
                asset_category=row.get('AssetClass', 'STK'),
                notes="Migrated from Opening Positions",
                source="OPENING_BALANCE",
                external_id=ext_id,
                description=row.get('Description'),
                conid=conid,
                listing_exchange=row.get('ListingExchange'),
                currency=row.get('CurrencyPrimary'),
                underlying_symbol=row.get('UnderlyingSymbol')
            )
            count += 1
        print(f"SUCCESS: Migrated {count} entries from opening positions.")
    except Exception as e:
        print(f"ERROR: Opening positions migration failed: {e}")

def process_local_csvs():
    """
    Scans the data directory for all relevant CSV files and incorporates them into the DB.
    """
    print("-> Incorporating local data into database (skipping duplicates)...")
    
    # 1. Opening Positions (Important for XLB and other starting balances)
    migrate_opening_positions()

    # 2. Main trades.csv
    if IBKR_TRADES_CSV.exists():
        parse_csv_trades(IBKR_TRADES_CSV)

    # 3. Year-specific files
    csv_files = list(DATA_DIR.glob("*_FY.csv")) + list(DATA_DIR.glob("*_YTD.csv"))
    csv_files.sort()

    for file_path in csv_files:
        parse_csv_trades(file_path)
    
    print("SUCCESS: Database up to date with all local CSVs.")

def sync_ibkr_trades():
    """
    Legacy convenience function.
    """
    fetch_trade_history()
    process_local_csvs()
