# fifo_engine.py
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime

class FIFOEngine:
    def __init__(self, xml_path):
        self.xml_path = xml_path
        self.trades_df = self._load_trades()

    def _load_trades(self):
        """
        Parses Trades.xml into a strictly sorted DataFrame.
        """
        if not self.xml_path.exists():
            return pd.DataFrame()

        trades = []
        try:
            tree = ET.parse(self.xml_path)
            root = tree.getroot()
            
            # Find all Trade elements
            for t in root.findall(".//Trade"):
                try:
                    # Parse critical fields
                    symbol = t.get('symbol')
                    date_str = t.get('tradeDate') # Format: 20230130 or 2023-01-30
                    qty = float(t.get('quantity', 0))
                    price = float(t.get('tradePrice', 0))
                    side = t.get('buySell') # 'BUY' or 'SELL'
                    
                    # Skip noise
                    if qty == 0 or not symbol: continue

                    # Normalize Date
                    if len(date_str) == 8:
                        dt = datetime.strptime(date_str, "%Y%m%d")
                    else:
                        dt = datetime.strptime(date_str, "%Y-%m-%d")

                    trades.append({
                        'symbol': symbol,
                        'date': dt,
                        'quantity': abs(qty),
                        'price': price,
                        'side': side.upper()
                    })
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"⚠️ Error parsing trades XML: {e}")
            return pd.DataFrame()

        df = pd.DataFrame(trades)
        if df.empty: return df
        
        # CRITICAL: Sort by Date ASC for FIFO to work
        df = df.sort_values('date', ascending=True)
        return df

    def get_open_date(self, ticker):
        """
        Replays history for a single ticker.
        Returns the date (YYYY-MM-DD) of the oldest surviving Buy lot.
        """
        if self.trades_df.empty: return "N/A"

        # Filter for this specific stock
        df = self.trades_df[self.trades_df['symbol'] == ticker]
        if df.empty: return "N/A"

        # FIFO Inventory: List of dicts {'date': ..., 'qty': ...}
        inventory = []

        for _, row in df.iterrows():
            if row['side'] == 'BUY':
                inventory.append({'date': row['date'], 'qty': row['quantity']})
            
            elif row['side'] == 'SELL':
                qty_to_sell = row['quantity']
                
                # Eat from the oldest lots first
                while qty_to_sell > 0 and inventory:
                    oldest = inventory[0]
                    
                    if oldest['qty'] > qty_to_sell:
                        # Partial match: Reduce the lot, done selling
                        oldest['qty'] -= qty_to_sell
                        qty_to_sell = 0
                    else:
                        # Full match: Remove the lot entirely, keep selling
                        qty_to_sell -= oldest['qty']
                        inventory.pop(0)

        # If anything survived, the first item is our "Oldest" holding
        if inventory:
            return inventory[0]['date'].strftime('%Y-%m-%d')
        
        return "N/A"