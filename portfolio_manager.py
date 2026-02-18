import pandas as pd
import numpy as np
import yfinance as yf
import xml.etree.ElementTree as ET
from data_loader import DataLoader
from ticker_mapper import TickerMapper
from db import get_all_risk_settings

class PortfolioManager:
    """
    Core engine for calculating portfolio metrics and risk.
    """
    
    def __init__(self, loader=None, mapper=None):
        self._loader = loader
        self._mapper = mapper

    @property
    def loader(self):
        return self._loader or DataLoader()

    @property
    def mapper(self):
        return self._mapper or TickerMapper()

    def calculate_positions(self, trades_df):
        """
        Unified engine for "Reset-on-Zero" ledger replay.
        Expects a cleaned DataFrame of trades.
        """
        if trades_df.empty:
            return []
            
        open_positions = []
        for conid, group in trades_df.groupby('Conid'):
            qty, total_cost, first_date = 0.0, 0.0, None
            
            for _, row in group.iterrows():
                side = str(row['Buy/Sell']).strip().upper()
                q = abs(row['Quantity'])
                p = row['Price']
                
                # Special handling for opening balance reset
                if 'OPENING_BALANCE' in str(row.get('source', '')).upper():
                    qty, total_cost, first_date = q, q * p, row['TradeDate']
                    continue
                
                if side == 'BUY':
                    if qty <= 0.0001:
                        first_date = row['TradeDate']
                    total_cost += q * p
                    qty += q
                elif side == 'SELL' and qty > 0:
                    # Cost basis reduction (FIFO/WAC style)
                    total_cost -= q * (total_cost / qty)
                    qty -= q
                    
                    # RESET ON ZERO logic
                    if qty <= 0.0001:
                        qty, total_cost, first_date = 0.0, 0.0, None
            
            if qty > 0.0001:
                latest = group.iloc[-1]
                open_positions.append({
                    'Name': latest.get('Description', latest['Symbol']),
                    'Ticker': latest['Symbol'],
                    'Conid': conid,
                    'ListingExchange': latest.get('ListingExchange'),
                    'AssetClass': latest.get('AssetClass', 'STK'),
                    'UnderlyingSymbol': latest.get('UnderlyingSymbol'),
                    'CCY': latest.get('CurrencyPrimary', 'USD'),
                    'Date': first_date,
                    'Qty': qty,
                    'Entry': total_cost / qty,
                    'ISIN': latest.get('ISIN', np.nan),
                    'MarkPrice': latest.get('Price', np.nan)
                })
        return open_positions

    def get_open_positions_hybrid(self, asset_class_filter=None):
        """
        Hybrid Mode: Starts from IBKR Snapshot + pending MANUAL trades.
        """
        broker_verified, report_date = self.loader.get_broker_verified_snapshot()
        all_trades = self.loader.load_trades_from_db()
        
        # Filter for manual trades occurring AFTER the report date
        pending_manual = all_trades[
            (all_trades['source'] == 'MANUAL') & 
            (all_trades['TradeDate'] > report_date)
        ] if report_date else all_trades[all_trades['source'] == 'MANUAL']

        open_list = []
        matched_conids = set()

        # 1. Start with Broker Verified
        for conid, v in broker_verified.items():
            ticker, qty, entry, first_date = v['Symbol'], v['Qty'], v['Entry'], v['Date']
            
            # Apply any pending manual adjustments
            adjustments = pending_manual[pending_manual['Conid'] == conid]
            for _, row in adjustments.iterrows():
                side, q, p = row['Buy/Sell'], row['Quantity'], row['Price']
                if side == 'BUY':
                    new_qty = qty + q
                    entry = ((qty * entry) + (q * p)) / new_qty if new_qty != 0 else 0
                    qty = new_qty
                    if not first_date: first_date = row['TradeDate']
                else:
                    qty = max(0, qty - q)
                    if qty <= 0: qty, entry, first_date = 0, 0, None

            if qty > 0.0001:
                open_list.append({
                    'Name': v['Description'], 'Ticker': ticker, 'Conid': conid,
                    'ListingExchange': v['ListingExchange'], 'AssetClass': v['AssetClass'],
                    'UnderlyingSymbol': v['UnderlyingSymbol'], 'CCY': v['Currency'], 'ISIN': v['ISIN'],
                    'Date': first_date, 'Qty': qty, 'Entry': entry, 'MarkPrice': v['MarkPrice']
                })
            matched_conids.add(conid)

        # 2. Add manual trades for assets NOT in IBKR snapshot
        remaining_manual = pending_manual[~pending_manual['Conid'].isin(matched_conids)]
        if not remaining_manual.empty:
            open_list.extend(self.calculate_positions(remaining_manual))

        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            open_list = [p for p in open_list if p['AssetClass'].upper() in filters]
            
        return open_list

    def get_open_positions_ledger(self, asset_class_filter=None):
        """
        Ledger Mode: Full database replay.
        """
        all_trades = self.loader.load_trades_from_db()
        if asset_class_filter:
            filters = [asset_class_filter.upper()] if isinstance(asset_class_filter, str) else [f.upper() for f in asset_class_filter]
            all_trades = all_trades[all_trades['AssetClass'].isin(filters)]
            
        return self.calculate_positions(all_trades)

    def get_dashboard_df(self, asset_class_filter=None, total_nav=None, use_ledger=False):
        """
        Enriches open positions with market data and risk metrics.
        """
        risk_settings = get_all_risk_settings()
        
        if use_ledger:
            open_list = self.get_open_positions_ledger(asset_class_filter)
        else:
            open_list = self.get_open_positions_hybrid(asset_class_filter)
            
        df = pd.DataFrame(open_list)
        if df.empty: return pd.DataFrame()
        
        # Market Data Enrichment
        prices, max_prices = [], []
        for _, row in df.iterrows():
            yf_ticker = self.mapper.resolve_yf_ticker(row['Ticker'], row.get('ISIN'))
            price, max_p = np.nan, np.nan
            if yf_ticker:
                try:
                    data = yf.Ticker(yf_ticker)
                    price = data.fast_info.get('last_price', np.nan)
                    if np.isnan(price):
                        hist = data.history(period="1d")
                        if not hist.empty: price = hist['Close'].iloc[-1]
                    
                    entry_date = pd.to_datetime(row['Date'])
                    full_hist = data.history(start=entry_date)
                    if not full_hist.empty:
                        max_p = full_hist['High'].max()
                except Exception: pass
            
            if np.isnan(price): price = row.get('MarkPrice', np.nan)
            if np.isnan(max_p): max_p = price
            prices.append(price); max_prices.append(max_p)
            
        df['Price'], df['MaxSinceEntry'] = prices, max_prices
        df['MarketValue'] = df['Price'] * df['Qty']
        df['P/L'] = (df['Price'] - df['Entry']) * df['Qty']
        df['Pct'] = ((df['Price'] - df['Entry']) / df['Entry']) * 100
        
        # Apply Risk Metrics
        df = self._apply_risk_metrics(df, risk_settings)

        # Performance Metrics
        today = pd.Timestamp.now()
        df['Years'] = (today - pd.to_datetime(df['Date'])).dt.days / 365.25
        df['AAGR'] = df.apply(self._calc_aagr, axis=1) * 100
        
        denominator = total_nav if (total_nav and total_nav > 0) else df['MarketValue'].sum()
        df['NavPct'] = (df['MarketValue'] / denominator) * 100
        
        return df[['Name', 'Ticker', 'Date', 'Qty', 'Entry', 'Price', 'MarketValue', 'P/L', 'CCY', 'Pct', 
                   'AAGR', 'NavPct', 'AssetClass', 'ATR_Disp', 'SL_Price', 'TP_Price', 
                   'Down_Pct', 'Up_Pct', 'Risk_Val', 'RR_Ratio', 'MaxSinceEntry']]

    def _apply_risk_metrics(self, df, risk_settings):
        def _row_risk(row):
            ticker = row['Ticker']
            price = row['Price']
            if ticker in risk_settings:
                atr, s_type = risk_settings[ticker]
                sl = (row['MaxSinceEntry'] if s_type == 'TRAILING' else row['Entry']) - atr
                tp = sl + (3 * atr)
                
                down_pct = ((price - sl) / price * 100) if price > 0 else 0
                up_pct = ((tp - price) / price * 100) if price > 0 else 0
                risk_amt = (price - sl) * row['Qty']
                rr = (tp - price) / (price - sl) if (price - sl) != 0 else 0
                
                return f"{atr:.2f} ({s_type[0]})", sl, tp, down_pct, up_pct, risk_amt, rr
            return "---", np.nan, np.nan, 0, 0, 0, 0

        risk_res = df.apply(_row_risk, axis=1)
        df['ATR_Disp'] = [r[0] for r in risk_res]
        df['SL_Price'] = [r[1] for r in risk_res]
        df['TP_Price'] = [r[2] for r in risk_res]
        df['Down_Pct'] = [r[3] for r in risk_res]
        df['Up_Pct'] = [r[4] for r in risk_res]
        df['Risk_Val'] = [r[5] for r in risk_res]
        df['RR_Ratio'] = [r[6] for r in risk_res]
        return df

    def _calc_aagr(self, row):
        if pd.isna(row['Price']) or row['Entry'] <= 0: return 0.0
        years = max(row['Years'], 0.04) 
        try: return ((row['Price'] / row['Entry']) ** (1 / years)) - 1
        except: return 0.0

    # --- Account / NAV Methods ---
    def fetch_nav_data(self, force_download=False):
        from config import IBKR_QUERY_ID_NAV, IBKR_NAV_XML
        from ibkr import download_flex_report
        file_path = download_flex_report(IBKR_QUERY_ID_NAV, IBKR_NAV_XML, force_download=force_download)
        if not file_path: return None
        try:
            tree = ET.parse(file_path)
            return self.parse_nav_report(tree.getroot())
        except Exception as e:
            print(f"❌ Error parsing NAV XML: {e}")
            return None

    def parse_nav_report(self, root):
        accounts, total_nav, report_date = [], 0.0, "Unknown"
        if root is None: return 0.0, [], report_date
        rows = root.findall(".//EquitySummaryByReportDateInBase")
        for row in rows:
            if report_date == "Unknown": report_date = row.get("reportDate", "Unknown")
            alias = row.get("acctAlias") or row.get("accountId") or "Unknown"
            nav_val = float(row.get("total", 0)) 
            accounts.append({'alias': alias, 'nav': nav_val})
            total_nav += nav_val
        return total_nav, accounts, report_date
