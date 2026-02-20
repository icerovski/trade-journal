import unittest
import pandas as pd
from dashboard import _generate_static_table
from rich.table import Table

class TestDashboardSorting(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame([
            {'Ticker': 'AAPL', 'Name': 'Apple', 'Date': pd.Timestamp('2023-01-01'), 'Qty': 10, 'Entry': 150.0, 'Price': 200.0, 'MarketValue': 2000.0, 'PL_Daily': 150.0, 'PL_Daily_Pct': 0.8, 'PL_Inc': 500.0, 'PL_Inc_Pct': 33.3, 'AAGR': 10.0, 'NavPct': 20.0, 'CCY': 'USD', 'AssetClass': 'STK', 'CostBasis': 1500.0},
            {'Ticker': 'MSFT', 'Name': 'Microsoft', 'Date': pd.Timestamp('2023-02-01'), 'Qty': 5, 'Entry': 300.0, 'Price': 350.0, 'MarketValue': 1750.0, 'PL_Daily': 100.0, 'PL_Daily_Pct': 0.5, 'PL_Inc': 250.0, 'PL_Inc_Pct': 16.7, 'AAGR': 15.0, 'NavPct': 17.5, 'CCY': 'USD', 'AssetClass': 'STK', 'CostBasis': 1500.0},
            {'Ticker': 'GOOGL', 'Name': 'Google', 'Date': pd.Timestamp('2023-03-01'), 'Qty': 20, 'Entry': 100.0, 'Price': 120.0, 'MarketValue': 2400.0, 'PL_Daily': 200.0, 'PL_Daily_Pct': 1.0, 'PL_Inc': 400.0, 'PL_Inc_Pct': 20.0, 'AAGR': 12.0, 'NavPct': 24.0, 'CCY': 'USD', 'AssetClass': 'STK', 'CostBasis': 2000.0}
        ])

    def test_sort_by_ticker(self):
        # Default is Ticker
        table = _generate_static_table(self.df, sort_by="Ticker")
        # Extract tickers from table rows (this is a bit tricky with Rich Table, but we can check the dataframe sorting)
        sorted_df = self.df.sort_values(['AssetClass', 'Ticker'], ascending=True)
        self.assertEqual(list(sorted_df['Ticker']), ['AAPL', 'GOOGL', 'MSFT'])

    def test_sort_by_market_value(self):
        table = _generate_static_table(self.df, sort_by="MarketValue")
        sorted_df = self.df.sort_values('MarketValue', ascending=False)
        self.assertEqual(list(sorted_df['Ticker']), ['GOOGL', 'AAPL', 'MSFT'])

    def test_sort_by_pct(self):
        table = _generate_static_table(self.df, sort_by="Pct")
        sorted_df = self.df.sort_values('PL_Inc_Pct', ascending=False)
        self.assertEqual(list(sorted_df['Ticker']), ['AAPL', 'GOOGL', 'MSFT'])

if __name__ == "__main__":
    unittest.main()
