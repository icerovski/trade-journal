# ibkr.py
import requests
import time
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from dateutil.parser import parse
from db import add_trade, trade_exists
from config import (
    IBKR_TOKEN, 
    IBKR_QUERY_ID_OPENING, 
    IBKR_QUERY_ID_YTD, 
    IBKR_QUERY_ID_NAV,
    IBKR_NAV_XML,
    IBKR_OPENING_XML, 
    IBKR_YTD_XML,
    IBKR_PRICING_XML # <--- Imported
)

# --- GENERIC DOWNLOADER ---
def download_flex_report(query_id, save_path):
    if "YOUR_" in IBKR_TOKEN or "YOUR_" in str(query_id):
        print("❌ Error: Please update IBKR config in config.py")
        return False

    print(f"--- Connecting to IBKR (Query {query_id}) ---")
    base_url = "https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
    req_url = f"{base_url}?t={IBKR_TOKEN}&q={query_id}&v=3"
    
    try:
        print("Requesting report generation...")
        response = requests.get(req_url)
        
        if "ErrorCode" in response.text:
            print(f"❌ API Error: {response.text}")
            return False

        root = ET.fromstring(response.content)
        code_elem = root.find('ReferenceCode')
        if code_elem is None:
            print("❌ Error: No ReferenceCode returned.")
            return False
            
        reference_code = code_elem.text
        print(f"✅ Report initiated (Ref: {reference_code}). Waiting 10s...")
        time.sleep(10)

        dl_url = "https://www.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"
        dl_req = f"{dl_url}?q={reference_code}&t={IBKR_TOKEN}&v=3"
        
        file_response = requests.get(dl_req)
        
        if file_response.status_code != 200:
            print("❌ Failed to download report.")
            return False
            
        with open(save_path, 'wb') as f:
            f.write(file_response.content)
            
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

# --- NEW: FETCH PRICES ONLY ---
def fetch_latest_prices():
    """
    Downloads the Open Positions report (Query 1) to use as a Pricing Snapshot.
    Does NOT import trades to DB.
    """
    print("🔄 Fetching Pricing Snapshot (using Open Positions Query)...")
    if download_flex_report(IBKR_QUERY_ID_OPENING, IBKR_PRICING_XML):
        print("✅ Pricing snapshot saved.")
        return True
    return False

# --- 1. OPENING BALANCE LOGIC ---
def fetch_opening_balance(target_date_str=None):
    if download_flex_report(IBKR_QUERY_ID_OPENING, IBKR_OPENING_XML):
        print("✅ XML downloaded. Parsing Opening Positions...")
        parse_opening_positions(IBKR_OPENING_XML, target_date_str)

def parse_opening_positions(file_path, target_date_str=None):
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        positions = root.findall(".//OpenPosition")
        
        if not positions:
            print("ℹ️  No positions found.")
            return

        count = 0
        if target_date_str:
            opening_date = target_date_str
        else:
            current_year = datetime.now().year
            opening_date = f"{current_year}-01-01"

        print(f"ℹ️  Importing positions as of: {opening_date}")

        for p in positions:
            ticker = p.get('symbol')
            position = float(p.get('position', 0))
            cost_basis = float(p.get('costBasisPrice', 0))
            asset_cat = p.get('assetCategory', 'STK')
            
            if position == 0: continue

            side = 'BUY' if position > 0 else 'SELL'
            qty = abs(position)
            
            syn_id = f"OPEN-{opening_date}-{ticker}"
            
            if trade_exists(syn_id): continue

            add_trade(
                date=opening_date,
                ticker=ticker,
                side=side,
                quantity=qty,
                price=cost_basis,
                asset_category=asset_cat,
                notes="Opening Balance",
                source="IBKR_SNAPSHOT",
                external_id=syn_id
            )
            count += 1

        print(f"✅ Imported {count} opening positions.")

    except Exception as e:
        print(f"❌ Error parsing Opening XML: {e}")

# --- 2. YTD TRADES LOGIC ---
def fetch_ytd_trades(start_date_str=None, end_date_str=None):
    if download_flex_report(IBKR_QUERY_ID_YTD, IBKR_YTD_XML):
        print("✅ XML downloaded. Parsing Trades...")
        parse_ytd_trades(IBKR_YTD_XML, start_date_str, end_date_str)

def parse_ytd_trades(file_path, start_date_str=None, end_date_str=None):
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        trades = root.findall(".//Trade")
        
        if not trades:
            print("ℹ️  No trades found.")
            return

        start_dt = parse(start_date_str) if start_date_str else None
        end_dt = parse(end_date_str) if end_date_str else None

        if start_dt:
            print(f"🔎 Filtering for trades after: {start_date_str}")

        added_count = 0
        skipped_count = 0
        date_skip_count = 0

        for t in trades:
            raw_date = t.get('tradeDate')
            if not raw_date: continue
            
            if len(raw_date) == 8:
                t_date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            else:
                t_date_str = raw_date
            
            t_dt = parse(t_date_str)

            if start_dt and t_dt < start_dt:
                date_skip_count += 1
                continue
            if end_dt and t_dt > end_dt:
                date_skip_count += 1
                continue

            external_id = t.get('tradeID') or t.get('ibOrderId')
            if external_id and trade_exists(external_id):
                skipped_count += 1
                continue

            ticker = t.get('symbol')
            side = t.get('buySell')
            qty = t.get('quantity')
            price = t.get('tradePrice')
            asset_cat = t.get('assetCategory') or "STK"
            raw_expiry = t.get('expiry')

            fmt_expiry = None
            if raw_expiry and len(raw_expiry) == 8:
                fmt_expiry = f"{raw_expiry[:4]}-{raw_expiry[4:6]}-{raw_expiry[6:]}"

            if not (ticker and side and qty and price): continue
            
            add_trade(
                date=t_date_str, 
                ticker=ticker, 
                side=side, 
                quantity=abs(float(qty)), 
                price=price, 
                asset_category=asset_cat,
                expiry=fmt_expiry,
                notes="IBKR YTD",
                source="IBKR_YTD",
                external_id=external_id
            )
            added_count += 1

        print(f"\nSummary: {added_count} new trades added.")
        print(f"Skipped: {skipped_count} duplicates, {date_skip_count} outside date range.")
        
    except Exception as e:
        print(f"❌ Error parsing YTD XML: {e}")
    
# --- 3. NAV / ACCOUNT BALANCE LOGIC ---
def fetch_nav_data(force_download=False):
    """
    Orchestrates getting the NAV/Cash report using IBKR_QUERY_ID_NAV.
    1. Downloads fresh data if force_download=True.
    2. Parses the XML.
    Returns: (total_nav, list_of_accounts)
    """
    if force_download:
        print("🔄 Downloading fresh NAV report...")
        if not download_flex_report(IBKR_QUERY_ID_NAV, IBKR_NAV_XML):
            print("❌ Download failed.")
            return None

    # Parse whatever file we have (fresh or cached)
    return parse_nav_report(IBKR_NAV_XML)

    # print("--- Fetching Account NAV ---")
    # if download_flex_report(IBKR_QUERY_ID_NAV, IBKR_NAV_XML):
    #     print("✅ NAV Report downloaded. Parsing...")
    #     return parse_nav_report(IBKR_NAV_XML)
    # return None

def parse_nav_report(file_path):
    """
    Parses the NAV report for MULTIPLE sub-accounts.
    Extracts Account ID, Alias, and Net Liquidation Value (total).
    Returns list of account dicts.
    """
    if not file_path.exists():
        return None
    
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # IBKR creates a separate FlexStatement for each sub-account
        statements = root.findall(".//FlexStatement")
        
        if not statements:
            print("❌ No account statements found in XML.")
            return None

        accounts = []
        grand_total_nav = 0.0
        
        for stmt in statements:
            # 1. Get Account ID
            acct_id = stmt.get('accountId', 'Unknown')
            
            # 2. Find the Equity Summary (Base Currency)
            summary = stmt.find(".//EquitySummaryByReportDateInBase")
            
            if summary is not None:
                # 3. Extract Details
                alias = summary.get('acctAlias', '-')
                nav = float(summary.get('total', 0.0))
                cash = float(summary.get('cash', 0.0))
                
                # 4. Accumulate
                accounts.append({
                    'id': acct_id,
                    'alias': alias,
                    'nav': nav,
                    'cash': cash
                })
                grand_total_nav += nav

        # 5. Sort by Alias for consistency
        accounts.sort(key=lambda x: x['alias'])

        return grand_total_nav, accounts

    except Exception as e:
        print(f"❌ Error parsing NAV XML: {e}")
        return None