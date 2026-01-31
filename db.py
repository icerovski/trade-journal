# db.py
import sqlite3
from config import DB_PATH

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cursor = conn.cursor()
    
    # 1. Create Table (with description)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            description TEXT,         -- NEW: Company Name
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            asset_category TEXT DEFAULT 'STK',
            expiry TEXT,
            notes TEXT,
            source TEXT DEFAULT 'MANUAL',
            external_id TEXT UNIQUE
        )
    """)
    
    # 2. Migration: Add 'description' if it's missing from an old DB
    cursor.execute("PRAGMA table_info(trades)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'description' not in columns:
        print("⚠️  Migrating DB: Adding 'description' column...")
        cursor.execute("ALTER TABLE trades ADD COLUMN description TEXT")

    conn.commit()
    conn.close()

def trade_exists(external_id):
    if not external_id: return False
    conn = get_conn()
    cursor = conn.execute("SELECT 1 FROM trades WHERE external_id = ?", (external_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_trade(date, ticker, side, quantity, price, asset_category="STK", 
              expiry=None, notes="", source="MANUAL", external_id=None, description=None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO trades 
               (date, ticker, side, quantity, price, asset_category, expiry, notes, source, external_id, description) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, ticker.upper(), side.upper(), float(quantity), float(price), 
             asset_category, expiry, notes, source, external_id, description)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass 
    finally:
        conn.close()

def archive_database():
    import shutil
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.parent / f"simple_journal_archive_{timestamp}.db"
    shutil.copy(DB_PATH, backup_path)
    print(f"📦 Database archived to: {backup_path.name}")