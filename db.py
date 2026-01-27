# db.py
import sqlite3
import os
from datetime import datetime
from config import DB_PATH

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    # Trades table: Stores history imported from IBKR
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            ticker TEXT,
            side TEXT,
            quantity REAL,
            price REAL,
            asset_category TEXT,
            expiry TEXT,
            notes TEXT,
            source TEXT,
            external_id TEXT UNIQUE
        )
    ''')
    conn.commit()
    conn.close()

def add_trade(date, ticker, side, quantity, price, asset_category="STK", expiry=None, notes="", source="MANUAL", external_id=None):
    """
    Inserts a trade into the database.
    Used mainly by ibkr.py to save imported XML history.
    """
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR IGNORE INTO trades 
            (date, ticker, side, quantity, price, asset_category, expiry, notes, source, external_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (date, ticker, side, quantity, price, asset_category, expiry, notes, source, external_id))
        conn.commit()
    except sqlite3.IntegrityError:
        print(f"⚠️ Trade {external_id} already exists.")
    finally:
        conn.close()

def trade_exists(external_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM trades WHERE external_id = ?", (external_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def archive_database():
    if os.path.exists(DB_PATH):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{DB_PATH}.{timestamp}.bak"
        os.rename(DB_PATH, new_name)
        print(f"📦 Database archived to: {new_name}")
        init_db()
        print("✨ New database initialized.")
    else:
        print("❌ No database found to archive.")