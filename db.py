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
    
    # 1. Trades Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            description TEXT,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            multiplier REAL DEFAULT 1.0,
            asset_category TEXT DEFAULT 'STK',
            expiry TEXT,
            notes TEXT,
            source TEXT DEFAULT 'MANUAL',
            external_id TEXT UNIQUE,
            conid TEXT,
            listing_exchange TEXT,
            currency TEXT,
            underlying_symbol TEXT
        )
    """)

    # 2. Position Risk Table (Settings for ATR/Stops)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS position_risk (
            ticker TEXT PRIMARY KEY,
            atr_value REAL NOT NULL,
            stop_type TEXT NOT NULL,  -- 'FIXED' or 'TRAILING'
            highest_sl REAL DEFAULT 0.0
        )
    """)
    
    # Migrations...
    cursor.execute("PRAGMA table_info(trades)")
    columns = [info[1] for info in cursor.fetchall()]
    
    migrations = [
        ('description', 'TEXT'),
        ('conid', 'TEXT'),
        ('listing_exchange', 'TEXT'),
        ('currency', 'TEXT'),
        ('underlying_symbol', 'TEXT'),
        ('multiplier', 'REAL')
    ]
    
    for col_name, col_type in migrations:
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")

    # Position Risk Migration
    cursor.execute("PRAGMA table_info(position_risk)")
    risk_cols = [info[1] for info in cursor.fetchall()]
    if 'highest_sl' not in risk_cols:
        cursor.execute("ALTER TABLE position_risk ADD COLUMN highest_sl REAL DEFAULT 0.0")

    conn.commit()
    conn.close()

def set_position_risk(ticker, atr, stop_type, reset_sl=True):
    """Saves or updates ATR/Stop settings for a ticker."""
    conn = get_conn()
    if reset_sl:
        conn.execute("""
            INSERT INTO position_risk (ticker, atr_value, stop_type, highest_sl) 
            VALUES (?, ?, ?, 0.0)
            ON CONFLICT(ticker) DO UPDATE SET 
                atr_value = excluded.atr_value,
                stop_type = excluded.stop_type,
                highest_sl = 0.0
        """, (ticker.upper(), float(atr), stop_type.upper()))
    else:
        conn.execute("""
            INSERT INTO position_risk (ticker, atr_value, stop_type) 
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET 
                atr_value = excluded.atr_value,
                stop_type = excluded.stop_type
        """, (ticker.upper(), float(atr), stop_type.upper()))
    conn.commit()
    conn.close()

def update_high_water_mark(ticker, sl_price):
    """Updates the highest stop loss price achieved."""
    conn = get_conn()
    conn.execute("""
        UPDATE position_risk SET highest_sl = MAX(highest_sl, ?) WHERE ticker = ?
    """, (float(sl_price), ticker.upper()))
    conn.commit()
    conn.close()

def get_all_risk_settings():
    """Returns all risk settings as a dict {ticker: (atr, type, highest_sl)}."""
    conn = get_conn()
    cursor = conn.execute("SELECT ticker, atr_value, stop_type, highest_sl FROM position_risk")
    rows = cursor.fetchall()
    conn.close()
    return {r['ticker']: (r['atr_value'], r['stop_type'], r['highest_sl']) for r in rows}

def trade_exists(external_id):
    if not external_id: return False
    conn = get_conn()
    cursor = conn.execute("SELECT 1 FROM trades WHERE external_id = ?", (external_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_trade(date, ticker, side, quantity, price, asset_category="STK", 
              multiplier=1.0, expiry=None, notes="", source="MANUAL", 
              external_id=None, description=None, conid=None, 
              listing_exchange=None, currency=None, underlying_symbol=None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO trades 
               (date, ticker, side, quantity, price, multiplier, asset_category, expiry, notes, 
                source, external_id, description, conid, listing_exchange, currency, underlying_symbol) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, ticker.upper(), side.upper(), float(quantity), float(price), 
             float(multiplier), asset_category, expiry, notes, source, external_id, description,
             conid, listing_exchange, currency, underlying_symbol)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass 
    finally:
        conn.close()

def get_manual_trades():
    """Returns all trades with source='MANUAL'."""
    conn = get_conn()
    cursor = conn.execute("SELECT id, date, ticker, side, quantity, price FROM trades WHERE source = 'MANUAL' ORDER BY date DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_trade(trade_id):
    """Deletes a trade by its database ID."""
    conn = get_conn()
    conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()