# db.py
import sqlite3
import shutil
from datetime import datetime
from config import DB_PATH, BASE_DIR

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,       -- YYYY-MM-DD
            ticker TEXT NOT NULL,     -- AAPL
            side TEXT NOT NULL,       -- BUY, SELL, EXP
            quantity REAL NOT NULL,   -- Always positive
            price REAL NOT NULL,      -- Execution price
            asset_category TEXT DEFAULT 'STK',
            expiry TEXT,              -- YYYY-MM-DD (for options)
            notes TEXT,
            source TEXT DEFAULT 'MANUAL', -- 'MANUAL', 'IBKR_SNAPSHOT', 'IBKR_YTD'
            external_id TEXT UNIQUE   -- IBKR Trade ID to prevent duplicates
        )
    """)
    conn.commit()
    conn.close()

def trade_exists(external_id):
    if not external_id:
        return False
    conn = get_conn()
    cursor = conn.execute("SELECT 1 FROM trades WHERE external_id = ?", (external_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_trade(date, ticker, side, quantity, price, asset_category="STK", 
              expiry=None, notes="", source="MANUAL", external_id=None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO trades 
               (date, ticker, side, quantity, price, asset_category, expiry, notes, source, external_id) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, ticker.upper(), side.upper(), float(quantity), float(price), 
             asset_category, expiry, notes, source, external_id)
        )
        conn.commit()
        print(f"✅ Recorded: {side} {quantity} {ticker} @ {price}")
    except sqlite3.IntegrityError:
        print(f"⚠️  Skipping duplicate trade (ID: {external_id})")
    finally:
        conn.close()

def archive_database():
    """
    Renames the current database file to a timestamped backup
    and initializes a fresh one.
    """
    if not DB_PATH.exists():
        print("❌ No database found to archive.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"journal_archive_{timestamp}.db"
    archive_path = BASE_DIR / archive_name
    
    try:
        shutil.move(str(DB_PATH), str(archive_path))
        print(f"✅ Database archived to: {archive_name}")
        print("🔄 Initializing fresh database...")
        init_db()
        print("✅ New 'simple_journal.db' created. Ready for Opening Balance.")
    except Exception as e:
        print(f"❌ Error archiving database: {e}")