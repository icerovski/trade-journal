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
    def parse_nav_csv(file_path):
        """
        Parses an IBKR Equity Summary CSV and returns (total_nav, account_list, report_date).
        IBKR Flex CSVs for NAV usually have sections like 'Equity Summary By Report Date In Base'.
        """
        if not file_path or not Path(file_path).exists():
            return 0.0, [], "Unknown"

        try:
            # Load CSV - usually has many sections. 
            # We look for rows where the first column indicates Equity Summary.
            df = pd.read_csv(file_path, low_memory=False, on_bad_lines='skip')
            
            # Clean columns
            df.columns = df.columns.str.strip()
            
            # Identify the correct section. 
            # In Flex CSV, Section Name is usually in the first column or 'SectionName'
            section_col = 'SectionName' if 'SectionName' in df.columns else df.columns[0]
            
            # Filter for Equity Summary rows
            nav_rows = df[df[section_col].str.contains('EquitySummary', na=False, case=False)]
            
            if nav_rows.empty:
                # Fallback: just look for 'Total' and 'ReportDate'
                nav_rows = df.dropna(subset=['Total', 'ReportDate'], how='all') if 'Total' in df.columns else pd.DataFrame()

            if nav_rows.empty:
                return 0.0, [], "Unknown"

            # Ensure numeric
            if 'Total' in nav_rows.columns:
                nav_rows['Total'] = pd.to_numeric(nav_rows['Total'], errors='coerce')
            
            total_nav = nav_rows['Total'].sum() if 'Total' in nav_rows.columns else 0.0
            report_date = str(nav_rows['ReportDate'].iloc[0]) if 'ReportDate' in nav_rows.columns else "Unknown"
            
            accounts = []
            # Map accounts if Alias or AccountId is present
            acct_col = 'AccountId' if 'AccountId' in nav_rows.columns else ('Account Alias' if 'Account Alias' in nav_rows.columns else None)
            if acct_col:
                for _, row in nav_rows.iterrows():
                    accounts.append({
                        'alias': row[acct_col],
                        'nav': float(row.get('Total', 0))
                    })
            
            return total_nav, accounts, report_date
        except Exception as e:
            print(f"ERROR: IBKR NAV CSV Parsing Error: {e}")
            return 0.0, [], "Unknown"
