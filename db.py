# db.py
import sqlite3
from config import DB_PATH

def get_conn():
    """Connects to the database and returns the connection object."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Creates the single table we need."""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,       -- YYYY-MM-DD
            ticker TEXT NOT NULL,     -- AAPL
            side TEXT NOT NULL,       -- BUY or SELL
            quantity REAL NOT NULL,   -- Always positive input
            price REAL NOT NULL,      -- Execution price
            notes TEXT                -- Strategy tags or comments
        )
    """)
    conn.commit()
    conn.close()

def trade_exists(date, ticker, side, quantity, price):
    """Checks if a trade typically already exists to prevent duplication on import."""
    conn = get_conn()
    cursor = conn.execute(
        """
        SELECT id FROM trades 
        WHERE date = ? AND ticker = ? AND side = ? AND quantity = ? AND price = ?
        """,
        (date, ticker.upper(), side.upper(), float(quantity), float(price))
    )
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_trade(date, ticker, side, quantity, price, notes=""):
    """Simple insert function."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO trades (date, ticker, side, quantity, price, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (date, ticker.upper(), side.upper(), float(quantity), float(price), notes)
    )
    conn.commit()
    conn.close()
    # Print logic moved to main/service to avoid clutter during bulk imports