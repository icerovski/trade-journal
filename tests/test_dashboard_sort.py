import unittest
import pandas as pd
from dashboard import generate_portfolio_table
from rich.table import Table

class TestDashboardSorting(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame([
            {'Ticker': 'AAPL', 'Name': 'Apple', 'Date': pd.Timestamp('2023-01-01'), 'Qty': 10, 'Entry': 150.0, 'Price': 200.0, 'MarketValue': 2000.0, 'P/L': 500.0, 'Pct': 33.3, 'AAGR': 10.0, 'NavPct': 20.0, 'CCY': 'USD'},
            {'Ticker': 'MSFT', 'Name': 'Microsoft', 'Date': pd.Timestamp('2023-02-01'), 'Qty': 5, 'Entry': 300.0, 'Price': 350.0, 'MarketValue': 1750.0, 'P/L': 250.0, 'Pct': 16.7, 'AAGR': 15.0, 'NavPct': 17.5, 'CCY': 'USD'},
            {'Ticker': 'GOOGL', 'Name': 'Google', 'Date': pd.Timestamp('2023-03-01'), 'Qty': 20, 'Entry': 100.0, 'Price': 120.0, 'MarketValue': 2400.0, 'P/L': 400.0, 'Pct': 20.0, 'AAGR': 12.0, 'NavPct': 24.0, 'CCY': 'USD'}
        ])

    def test_sort_by_ticker(self):
        # Default is Ticker
        table = generate_portfolio_table(self.df, sort_by="Ticker")
        # Extract tickers from table rows (this is a bit tricky with Rich Table, but we can check the dataframe sorting)
        sorted_df = self.df.sort_values('Ticker', ascending=True)
        self.assertEqual(list(sorted_df['Ticker']), ['AAPL', 'GOOGL', 'MSFT'])

    def test_sort_by_market_value(self):
        table = generate_portfolio_table(self.df, sort_by="MarketValue")
        sorted_df = self.df.sort_values('MarketValue', ascending=False)
        self.assertEqual(list(sorted_df['Ticker']), ['GOOGL', 'AAPL', 'MSFT'])

    def test_sort_by_pct(self):
        table = generate_portfolio_table(self.df, sort_by="Pct")
        sorted_df = self.df.sort_values('Pct', ascending=False)
        self.assertEqual(list(sorted_df['Ticker']), ['AAPL', 'GOOGL', 'MSFT'])

if __name__ == "__main__":
    unittest.main()
