import shutil
import unittest
import sqlite3
import pandas as pd
import io
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

# Import components
import db
import ibkr
import portfolio_manager
import dashboard
from config import DB_PATH

class TestFullFeatures(unittest.TestCase):
    def setUp(self):
        # 1. Use a temporary directory for data
        self.test_dir = Path("./test_run_dir")
        self.test_dir.mkdir(exist_ok=True)
        self.test_db = self.test_dir / "test_journal.db"
        
        # 2. Patch paths in all modules
        self.patches = [
            patch("db.DB_PATH", self.test_db),
            patch("config.DB_PATH", self.test_db),
            patch("ibkr.DATA_DIR", self.test_dir),
            patch("portfolio_manager.get_conn", lambda: sqlite3.connect(self.test_db))
        ]
        for p in self.patches:
            p.start()
            
        # 3. Initialize fresh DB
        db.init_db()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_end_to_end_flow(self):
        """
        Tests: Sync -> Database -> Calculation -> Dashboard
        """
        # --- A. Preparation: Create mock IBKR CSV data ---
        current_year = datetime.now().year
        prev_year = current_year - 1
        
        # Create a CSV with a few trades including a Reset-on-Zero scenario
        csv_content = f"""Symbol,Buy/Sell,TradeDate,Quantity,TradePrice,AssetClass,Description,Conid,ListingExchange,CurrencyPrimary,UnderlyingSymbol
AAPL,BUY,{prev_year}0101,10,150,STK,Apple Inc,123,NASDAQ,USD,AAPL
AAPL,SELL,{prev_year}0601,-10,180,STK,Apple Inc,123,NASDAQ,USD,AAPL
AAPL,BUY,{current_year}0101,5,170,STK,Apple Inc,123,NASDAQ,USD,AAPL
MSFT,BUY,{current_year}0201,10,300,STK,Microsoft,456,NASDAQ,USD,MSFT
"""
        prev_fy_path = self.test_dir / f"{prev_year}_FY.csv"
        prev_fy_path.write_text(csv_content)
        
        # --- B. Test Sync Logic ---
        with patch("ibkr.download_flex_report") as mock_dl:
            # Simulate YTD download returning an empty but valid CSV
            ytd_path = self.test_dir / f"{current_year}_YTD.csv"
            ytd_path.write_text("Symbol,Buy/Sell,TradeDate,Quantity,TradePrice,AssetClass,Description,Conid,ListingExchange,CurrencyPrimary,UnderlyingSymbol")
            mock_dl.return_value = ytd_path
            
            ibkr.sync_ibkr_trades()
            
        # Verify trades in DB
        conn = sqlite3.connect(self.test_db)
        count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        conn.close()
        self.assertEqual(count, 4, "Should have imported 4 trades")

        # --- C. Test Portfolio Calculation ---
        pm = portfolio_manager.PortfolioManager() # Loads from DB
        positions = pm.calculate_positions()
        
        # Check AAPL: Should be 5 shares @ 170 (The 10 @ 150 was reset by the sell)
        aapl = positions[positions['Ticker'] == 'AAPL'].iloc[0]
        self.assertEqual(aapl['Qty'], 5)
        self.assertEqual(aapl['Entry'], 170.0)
        
        # Check MSFT: 10 shares @ 300
        msft = positions[positions['Ticker'] == 'MSFT'].iloc[0]
        self.assertEqual(msft['Qty'], 10)
        self.assertEqual(msft['Entry'], 300.0)

        # --- D. Test Dashboard Calculation ---
        # Mock yfinance to return fixed prices
        with patch("yfinance.Ticker") as mock_yf:
            # Use side_effect to return different values
            def yf_side_effect(ticker):
                m = MagicMock()
                if "AAPL" in ticker:
                    m.fast_info = {'last_price': 200.0}
                else:
                    m.fast_info = {'last_price': 350.0}
                return m
            
            mock_yf.side_effect = yf_side_effect
            
            # Mock NAV fetch
            with patch.object(portfolio_manager.PortfolioManager, 'fetch_nav_data', return_value=(5000.0, [], "2026-02-13")):
                df, nav, report_date = dashboard.calculate_dashboard_data(pm)
                
                # Assertions on Dashboard DataFrame
                self.assertEqual(nav, 5000.0)
                self.assertEqual(report_date, "2026-02-13")
                
                aapl_row = df[df['Ticker'] == 'AAPL'].iloc[0]
                self.assertEqual(aapl_row['P/L'], (200 - 170) * 5) # 150
                self.assertEqual(aapl_row['NavPct'], (200 * 5) / 5000 * 100) # 20% exposure

        print("\n✅ Integration Test Passed: Sync -> DB -> Position Logic -> Dashboard")

if __name__ == "__main__":
    unittest.main()
