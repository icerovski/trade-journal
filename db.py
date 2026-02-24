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

# 3. Ticker Info Table (Asset Master)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticker_info (
            conid TEXT PRIMARY KEY,
            ticker_ibkr TEXT NOT NULL,
            ticker_yfinance TEXT NOT NULL,
            isin TEXT,
            asset_class TEXT,
            multiplier REAL DEFAULT 1.0,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticker_ibkr ON ticker_info(ticker_ibkr)")
    
    # Migrations...
    cursor.execute("PRAGMA table_info(trades)")
    columns = [info[1] for info in cursor.fetchall()]
    
    migrations = [
        ('description', 'TEXT'),
        ('conid', 'TEXT'),
        ('listing_exchange', 'TEXT'),
        ('currency', 'TEXT'),
        ('underlying_symbol', 'TEXT'),
        ('multiplier', 'REAL'),
        ('isin', 'TEXT')
    ]
    
    for col_name, col_type in migrations:
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")

    # Legacy Migration: If old position_risk exists, move data to risk_profiles
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='position_risk'")
    if cursor.fetchone():
        cursor.execute("SELECT ticker, atr_value, stop_type, highest_sl FROM position_risk")
        old_risks = cursor.fetchall()
        for r in old_risks:
            # We don't have conid for old risks easily here, so we'll use ticker as a placeholder
            # or try to find it from trades. For simplicity in migration, use ticker.
            cursor.execute("""
                INSERT INTO risk_profiles (conid, ticker, atr_value, stop_type, highest_sl, status)
                SELECT conid, ticker, ?, ?, ?, 'ACTIVE' FROM trades WHERE ticker = ? LIMIT 1
            """, (r['atr_value'], r['stop_type'], r['highest_sl'], r['ticker']))
        
        cursor.execute("DROP TABLE position_risk")

    conn.commit()
    conn.close()

def wipe_trades_only():
    """Drops and recreates the trades table, preserving risk profiles."""
    conn = get_conn()
    conn.execute("DROP TABLE IF EXISTS trades")
    conn.commit()
    conn.close()
    init_db()

def set_position_risk(conid, ticker, atr, stop_type, start_date=None, reset_sl=True):
    """Saves or updates the ACTIVE risk profile for a conid."""
    conn = get_conn()
    conid = str(conid)
    
    # Check if an active profile exists
    cursor = conn.execute("SELECT id FROM risk_profiles WHERE conid = ? AND status = 'ACTIVE'", (conid,))
    existing = cursor.fetchone()

    if existing:
        if reset_sl:
            conn.execute("""
                UPDATE risk_profiles SET 
                    atr_value = ?, stop_type = ?, highest_sl = 0.0, ticker = ?
                WHERE id = ?
            """, (float(atr), stop_type.upper(), ticker.upper(), existing['id']))
        else:
            conn.execute("""
                UPDATE risk_profiles SET 
                    atr_value = ?, stop_type = ?, ticker = ?
                WHERE id = ?
            """, (float(atr), stop_type.upper(), ticker.upper(), existing['id']))
    else:
        conn.execute("""
            INSERT INTO risk_profiles (conid, ticker, atr_value, stop_type, start_date, status) 
            VALUES (?, ?, ?, ?, ?, 'ACTIVE')
        """, (conid, ticker.upper(), float(atr), stop_type.upper(), start_date))
    
    conn.commit()
    conn.close()

def close_risk_profile(conid, end_date):
    """Archives an active risk profile when a position is closed."""
    conn = get_conn()
    conn.execute("""
        UPDATE risk_profiles 
        SET status = 'CLOSED', end_date = ? 
        WHERE conid = ? AND status = 'ACTIVE'
    """, (end_date, str(conid)))
    conn.commit()
    conn.close()

def update_high_water_mark(conid, sl_price):
    """Updates the highest stop loss price achieved for an active profile."""
    conn = get_conn()
    conn.execute("""
        UPDATE risk_profiles SET highest_sl = MAX(highest_sl, ?) 
        WHERE conid = ? AND status = 'ACTIVE'
    """, (float(sl_price), str(conid)))
    conn.commit()
    conn.close()

def get_all_risk_settings():
    """Returns all ACTIVE risk settings as a dict {conid: (atr, type, highest_sl)}."""
    conn = get_conn()
    cursor = conn.execute("SELECT conid, atr_value, stop_type, highest_sl FROM risk_profiles WHERE status = 'ACTIVE'")
    rows = cursor.fetchall()
    conn.close()
    return {r['conid']: (r['atr_value'], r['stop_type'], r['highest_sl']) for r in rows}

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

def delete_manual_duplicates(ticker, date, quantity, side):
    """
    Fingerprint De-duplication: Removes manual trades that match a broker execution.
    Matches on Ticker, Date (YYYY-MM-DD), and Quantity.
    """
    conn = get_conn()
    ticker = ticker.upper()
    side = side.upper()
    # Normalize date to YYYY-MM-DD in case it's a full timestamp
    date_str = date[:10] if isinstance(date, str) else date.strftime("%Y-%m-%d")
    
    cursor = conn.execute("""
        DELETE FROM trades 
        WHERE source = 'MANUAL' 
        AND ticker = ? 
        AND date LIKE ? 
        AND ABS(quantity) = abs(?)
        AND side = ?
    """, (ticker, f"{date_str}%", float(quantity), side))
    
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def get_conid_for_ticker(ticker):
    """Attempts to find a known Conid for a ticker from asset master or trade history."""
    conn = get_conn()
    ticker = ticker.upper()
    
    # 1. Try Asset Master first
    cursor = conn.execute("SELECT conid FROM ticker_info WHERE ticker_ibkr = ? LIMIT 1", (ticker,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return row['conid']
        
    # 2. Fallback to trade history
    cursor = conn.execute("SELECT conid FROM trades WHERE ticker = ? AND conid IS NOT NULL LIMIT 1", (ticker,))
    row = cursor.fetchone()
    conn.close()
    return row['conid'] if row else None

def get_ticker_info(conid):
    """Returns all info for a specific conid."""
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM ticker_info WHERE conid = ?", (str(conid),))
    row = cursor.fetchone()
    conn.close()
    return row

def save_ticker_info(conid, ticker_ibkr, ticker_yfinance, isin=None, asset_class=None, multiplier=1.0):
    """Upserts ticker mapping and metadata."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO ticker_info (conid, ticker_ibkr, ticker_yfinance, isin, asset_class, multiplier, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(conid) DO UPDATE SET
            ticker_ibkr = excluded.ticker_ibkr,
            ticker_yfinance = excluded.ticker_yfinance,
            isin = COALESCE(excluded.isin, ticker_info.isin),
            asset_class = COALESCE(excluded.asset_class, ticker_info.asset_class),
            multiplier = excluded.multiplier,
            last_updated = CURRENT_TIMESTAMP
    """, (str(conid), ticker_ibkr.upper(), ticker_yfinance, isin, asset_class, float(multiplier)))
    conn.commit()
    conn.close()

def get_yf_ticker(ticker_ibkr):
    """Helper to find YF ticker directly from IBKR ticker if conid is unknown."""
    conn = get_conn()
    cursor = conn.execute("SELECT ticker_yfinance FROM ticker_info WHERE ticker_ibkr = ? LIMIT 1", (ticker_ibkr.upper(),))
    row = cursor.fetchone()
    conn.close()
    return row['ticker_yfinance'] if row else None

def delete_trade(trade_id):
    """Deletes a trade by its database ID."""
    conn = get_conn()
    conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()