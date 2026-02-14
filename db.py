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
    
    # 1. Create Table (with all necessary IBKR columns)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            description TEXT,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            asset_category TEXT DEFAULT 'STK',
            expiry TEXT,
            notes TEXT,
            source TEXT DEFAULT 'MANUAL',
            external_id TEXT UNIQUE,
            conid TEXT,               -- NEW: IBKR unique ID
            listing_exchange TEXT,    -- NEW: e.g. IBIS, AEB
            currency TEXT,            -- NEW: e.g. USD, EUR
            underlying_symbol TEXT    -- NEW: For mapping options/funds
        )
    """)
    
    # 2. Migrations: Add missing columns
    cursor.execute("PRAGMA table_info(trades)")
    columns = [info[1] for info in cursor.fetchall()]
    
    migrations = [
        ('description', 'TEXT'),
        ('conid', 'TEXT'),
        ('listing_exchange', 'TEXT'),
        ('currency', 'TEXT'),
        ('underlying_symbol', 'TEXT')
    ]
    
    for col_name, col_type in migrations:
        if col_name not in columns:
            print(f"⚠️  Migrating DB: Adding '{col_name}' column...")
            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")

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
              expiry=None, notes="", source="MANUAL", external_id=None, 
              description=None, conid=None, listing_exchange=None, 
              currency=None, underlying_symbol=None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO trades 
               (date, ticker, side, quantity, price, asset_category, expiry, notes, 
                source, external_id, description, conid, listing_exchange, currency, underlying_symbol) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, ticker.upper(), side.upper(), float(quantity), float(price), 
             asset_category, expiry, notes, source, external_id, description,
             conid, listing_exchange, currency, underlying_symbol)
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