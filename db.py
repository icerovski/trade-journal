# db.py
import sqlite3
from config import DB_PATH
from logger import logger

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cursor = conn.cursor()
    
    # 1. Trades Table (Activity Only)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            account_id TEXT DEFAULT 'U0000000',
            conid TEXT NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            notes TEXT,
            source TEXT DEFAULT 'MANUAL',
            external_id TEXT UNIQUE
        )
    """)
    # Migration: Add account_id if it doesn't exist
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN account_id TEXT DEFAULT 'U0000000'")
    except Exception:
        pass


    # 2. Risk Profiles Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS risk_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conid TEXT NOT NULL,
            ticker TEXT NOT NULL,
            atr_value REAL NOT NULL,
            stop_type TEXT NOT NULL,
            entry_type TEXT DEFAULT 'SINGLE',
            scale_step REAL DEFAULT 0.5,
            highest_sl REAL DEFAULT 0.0,
            status TEXT DEFAULT 'ACTIVE',
            start_date TEXT,
            end_date TEXT,
            max_r_pct REAL DEFAULT 1.0,
            max_exp_pct REAL DEFAULT 5.0
        )
    """)
    # Migration: Add columns if they don't exist
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN scale_step REAL DEFAULT 0.5")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN max_r_pct REAL DEFAULT 1.0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN max_exp_pct REAL DEFAULT 5.0")
    except Exception:
        pass
    
    # Ensure conid unique for ACTIVE and WATCH profiles separately
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_active_conid ON risk_profiles(conid) WHERE status = 'ACTIVE'")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_watch_conid ON risk_profiles(conid) WHERE status = 'WATCH'")


    # 3. Ticker Info Table (Asset Master - Single Source of Truth for Metadata)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticker_info (
            conid TEXT PRIMARY KEY,
            ticker_ibkr TEXT NOT NULL,
            ticker_yfinance TEXT,
            isin TEXT,
            asset_class TEXT,
            multiplier REAL DEFAULT 1.0,
            description TEXT,
            listing_exchange TEXT,
            currency TEXT,
            underlying_symbol TEXT,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticker_ibkr ON ticker_info(ticker_ibkr)")

    # 4. Kids Fund Configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kids_config (
            name TEXT PRIMARY KEY,
            birthdate TEXT NOT NULL,
            base_units REAL NOT NULL,
            base_date TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

def wipe_trades_only():
    """Drops and recreates the trades table, preserving risk profiles."""
    conn = get_conn()
    conn.execute("DROP TABLE IF EXISTS trades")
    conn.commit()
    conn.close()
    init_db()

def set_position_risk(conid, ticker, atr, stop_type, start_date=None, reset_sl=False, entry_type='SINGLE', scale_step=0.5, status='ACTIVE', max_r_pct=1.0, max_exp_pct=5.0):
    """Saves or updates a risk profile (ACTIVE or WATCH) for a conid."""
    conn = get_conn()
    conid = str(conid)
    
    # Check if a profile with this status exists
    cursor = conn.execute("SELECT id FROM risk_profiles WHERE conid = ? AND status = ?", (conid, status))
    existing = cursor.fetchone()

    if existing:
        if reset_sl:
            conn.execute("""
                UPDATE risk_profiles SET 
                    atr_value = ?, stop_type = ?, entry_type = ?, scale_step = ?, max_r_pct = ?, max_exp_pct = ?, highest_sl = 0.0, ticker = ?
                WHERE id = ?
            """, (float(atr), stop_type.upper(), entry_type.upper(), float(scale_step), float(max_r_pct), float(max_exp_pct), ticker.upper(), existing['id']))
        else:
            conn.execute("""
                UPDATE risk_profiles SET 
                    atr_value = ?, stop_type = ?, entry_type = ?, scale_step = ?, max_r_pct = ?, max_exp_pct = ?, ticker = ?
                WHERE id = ?
            """, (float(atr), stop_type.upper(), entry_type.upper(), float(scale_step), float(max_r_pct), float(max_exp_pct), ticker.upper(), existing['id']))
    else:
        conn.execute("""
            INSERT INTO risk_profiles (conid, ticker, atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct, start_date, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (conid, ticker.upper(), float(atr), stop_type.upper(), entry_type.upper(), float(scale_step), float(max_r_pct), float(max_exp_pct), start_date, status))
    
    conn.commit()
    conn.close()

def get_watch_list_profiles():
    """Returns all risk profiles marked as 'WATCH'."""
    conn = get_conn()
    cursor = conn.execute("SELECT conid, ticker, atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct FROM risk_profiles WHERE status = 'WATCH'")
    rows = cursor.fetchall()
    conn.close()
    return rows

def promote_prospect_to_active(ticker, real_conid):
    """
    Bridge Logic: Transfers a 'WATCH' profile to 'ACTIVE' when a real conid is discovered.
    Called when a new asset is synced from the broker.
    """
    conn = get_conn()
    # Find watch entry by ticker (since conid was virtual)
    cursor = conn.execute("SELECT id, atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct FROM risk_profiles WHERE ticker = ? AND status = 'WATCH'", (ticker.upper(),))
    prospect = cursor.fetchone()
    
    if prospect:
        # 1. Close the watch entry
        conn.execute("UPDATE risk_profiles SET status = 'CLOSED', end_date = CURRENT_TIMESTAMP WHERE id = ?", (prospect['id'],))
        
        # 2. Create new ACTIVE entry with real conid, inheriting settings
        conn.execute("""
            INSERT INTO risk_profiles (conid, ticker, atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct, status, start_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', CURRENT_TIMESTAMP)
        """, (str(real_conid), ticker.upper(), prospect['atr_value'], prospect['stop_type'], 
              prospect['entry_type'], prospect['scale_step'], prospect['max_r_pct'], prospect['max_exp_pct']))
        
        conn.commit()
        logger.info(f"PROMOTED: Prospect {ticker} is now an ACTIVE position with conid {real_conid}")
    
    conn.close()

def delete_risk_profile(conid):
    """Permanently deletes a risk profile by its conid."""
    conn = get_conn()
    conn.execute("DELETE FROM risk_profiles WHERE conid = ?", (str(conid),))
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
    """Returns all ACTIVE risk settings as a dict {conid: (atr, type, highest_sl, entry_type, scale_step, max_r_pct, max_exp_pct, start_date)}."""
    conn = get_conn()
    cursor = conn.execute("SELECT conid, atr_value, stop_type, highest_sl, entry_type, scale_step, max_r_pct, max_exp_pct, start_date FROM risk_profiles WHERE status = 'ACTIVE'")
    rows = cursor.fetchall()
    conn.close()
    return {r['conid']: (r['atr_value'], r['stop_type'], r['highest_sl'], r['entry_type'], r['scale_step'], r['max_r_pct'], r['max_exp_pct'], r['start_date']) for r in rows}

def trade_exists(external_id):
    if not external_id:
        return False
    conn = get_conn()
    cursor = conn.execute("SELECT 1 FROM trades WHERE external_id = ?", (external_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_trade(date, ticker, side, quantity, price, conid, account_id='U0000000', notes="", source="MANUAL", external_id=None):
    """Inserts a trade execution or manual entry (Activity Only)."""
    conn = get_conn()
    try:
        # Normalize conid to string or None
        conid_val = str(conid) if conid is not None else None
        
        conn.execute(
            """INSERT INTO trades 
               (date, account_id, ticker, side, quantity, price, conid, notes, source, external_id) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, account_id, ticker.upper(), side.upper(), float(quantity), float(price), 
             conid_val, notes, source, external_id)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass 
    finally:
        conn.close()

def get_manual_trades():
    """Returns all trades with source='MANUAL'."""
    conn = get_conn()
    cursor = conn.execute("SELECT id, date, account_id, ticker, side, quantity, price FROM trades WHERE source = 'MANUAL' ORDER BY date DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def seed_kids_fund():
    """Initial seed of the kids fund configuration from the legacy JSON state."""
    data = [
        ("Angelina", "2016-01-18", 5430.3034, "2026-03-05"),
        ("Ivan",     "2018-11-26", 3788.2800, "2026-03-05"),
        ("Boris",    "2020-02-20", 3283.1760, "2026-03-05")
    ]
    conn = get_conn()
    for name, dob, units, bdate in data:
        conn.execute("INSERT OR IGNORE INTO kids_config (name, birthdate, base_units, base_date) VALUES (?, ?, ?, ?)",
                     (name, dob, units, bdate))
    conn.commit()
    conn.close()

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

def save_ticker_info(conid, ticker_ibkr, ticker_yfinance=None, isin=None, asset_class=None, 
                     multiplier=None, description=None, listing_exchange=None, 
                     currency=None, underlying_symbol=None):
    """Upserts asset metadata into the Asset Master (ticker_info)."""
    conn = get_conn()
    # Ensure multiplier is float
    m_val = float(multiplier) if multiplier is not None and str(multiplier).strip() != '' else 1.0
    
    # Use NULLIF to treat empty strings as NULL for COALESCE logic
    conn.execute("""
        INSERT INTO ticker_info (conid, ticker_ibkr, ticker_yfinance, isin, asset_class, 
                                multiplier, description, listing_exchange, currency, 
                                underlying_symbol, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(conid) DO UPDATE SET
            ticker_ibkr = excluded.ticker_ibkr,
            ticker_yfinance = COALESCE(NULLIF(excluded.ticker_yfinance, ''), ticker_info.ticker_yfinance),
            isin = COALESCE(NULLIF(excluded.isin, ''), ticker_info.isin),
            asset_class = COALESCE(NULLIF(excluded.asset_class, ''), ticker_info.asset_class),
            multiplier = COALESCE(excluded.multiplier, ticker_info.multiplier),
            description = COALESCE(NULLIF(excluded.description, ''), ticker_info.description),
            listing_exchange = COALESCE(NULLIF(excluded.listing_exchange, ''), ticker_info.listing_exchange),
            currency = COALESCE(NULLIF(excluded.currency, ''), ticker_info.currency),
            underlying_symbol = COALESCE(NULLIF(excluded.underlying_symbol, ''), ticker_info.underlying_symbol),
            last_updated = CURRENT_TIMESTAMP
    """, (str(conid), ticker_ibkr.upper(), ticker_yfinance, isin, asset_class, 
          m_val, description, listing_exchange, currency, underlying_symbol))
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
