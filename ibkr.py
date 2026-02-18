import requests
import xml.etree.ElementTree as ET
import pandas as pd
from pathlib import Path
from datetime import datetime

from config import (
    IBKR_TRADES_CSV,
    DATA_DIR
)
from db import add_trade, trade_exists

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
        print(f"ERROR: IBKR Credentials/Query ID missing in .env (ID: {query_id})")
        return None
        
    url = f"https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={query_id}&v=3"
    print(f"-> Requesting report from IBKR (ID: {query_id})...")
    
    try:
        resp = requests.get(url)
        if not resp.content.strip().startswith(b"<"):
            print(f"WARNING: IBKR Handshake Error: {resp.text}")
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
        print(f"ERROR: Connection Error: {e}")
    return None

# --- 2. CSV PARSER ---
def parse_csv_trades(file_path):
    if not file_path or not Path(file_path).exists():
        return

    print(f"-> Parsing CSV: {file_path.name}...")
    try:
        df = pd.read_csv(file_path)
        df.columns = df.columns.str.strip()
        
        if 'Symbol' in df.columns:
            df = df.dropna(subset=['Symbol'])
        if 'LevelOfDetail' in df.columns:
            df = df[df['LevelOfDetail'] == 'EXECUTION']
        
        count = 0
        for _, row in df.iterrows():
            ticker = row.get('Symbol')
            side = str(row.get('Buy/Sell', '')).upper()
            date_raw = str(row.get('TradeDate', '')).replace('-', '')
            
            if not ticker or side not in ['BUY', 'SELL']:
                continue

            try:
                date_str = pd.to_datetime(date_raw).strftime("%Y-%m-%d")
                qty = abs(float(row.get('Quantity', 0)))
                price = float(row.get('TradePrice', 0))
                
                ib_id = row.get('IBOrderID') or row.get('TradeID')
                ext_id = str(ib_id) if ib_id else f"MAN-{date_str}-{ticker}-{price}-{qty}"

                if trade_exists(ext_id):
                    continue

                add_trade(
                    date=date_str, ticker=ticker, side=side, 
                    quantity=qty, price=price, asset_category=row.get('AssetClass', 'STK'), 
                    notes=f"IBKR CSV Import {datetime.now().date()}",
                    source="IBKR_CSV", external_id=ext_id,
                    description=row.get('Description', ''),
                    conid=str(row.get('Conid', '')),
                    listing_exchange=str(row.get('ListingExchange', '')),
                    currency=str(row.get('CurrencyPrimary', '')),
                    underlying_symbol=str(row.get('UnderlyingSymbol', ''))
                )
                count += 1
            except:
                continue
        print(f"SUCCESS: Imported {count} trades.")
    except Exception as e:
        print(f"ERROR: CSV Parsing Error: {e}")

# --- 3. WRAPPERS ---

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
        parse_csv_trades(IBKR_TRADES_CSV)
    
    for f in list(DATA_DIR.glob("*_FY.csv")) + list(DATA_DIR.glob("*_YTD.csv")):
        parse_csv_trades(f)
