import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from db import add_trade, trade_exists

class IBKRParser:
    """
    Handles interpreting IBKR-specific file formats (CSV and XML).
    Separates the 'Knowledge of Columns' from the 'Networking' layer.
    """

    @staticmethod
    def parse_trade_csv(file_path):
        """Parses an IBKR Trade Confirmation CSV and saves results to DB."""
        if not file_path or not Path(file_path).exists():
            return 0

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
            return count
        except Exception as e:
            print(f"ERROR: IBKR CSV Parsing Error: {e}")
            return 0

    @staticmethod
    def parse_nav_xml(file_path):
        """Parses an IBKR Equity Summary XML and returns (total_nav, account_list, report_date)."""
        if not file_path or not Path(file_path).exists():
            return 0.0, [], "Unknown"

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            accounts, total_nav, report_date = [], 0.0, "Unknown"
            rows = root.findall(".//EquitySummaryByReportDateInBase")
            
            for row in rows:
                if report_date == "Unknown": 
                    report_date = row.get("reportDate", "Unknown")
                
                alias = row.get("acctAlias") or row.get("accountId") or "Unknown"
                nav_val = float(row.get("total", 0)) 
                accounts.append({'alias': alias, 'nav': nav_val})
                total_nav += nav_val
                
            return total_nav, accounts, report_date
        except Exception as e:
            print(f"ERROR: IBKR NAV XML Parsing Error: {e}")
            return 0.0, [], "Unknown"
