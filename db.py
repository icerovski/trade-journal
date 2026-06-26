# db.py
import sqlite3
from config import DB_PATH
from logger import logger
from models import RiskProfile

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
            multiplier REAL DEFAULT 1.0,
            notes TEXT,
            source TEXT DEFAULT 'MANUAL',
            external_id TEXT UNIQUE
        )
    """)
    # Migration: Add account_id and multiplier if they don't exist
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN account_id TEXT DEFAULT 'U0000000'")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN multiplier REAL DEFAULT 1.0")
    except Exception: pass

    # Cleanup: Remove legacy MANUAL trades as the feature is now disabled
    cursor.execute("DELETE FROM trades WHERE source = 'MANUAL'")
    if cursor.rowcount > 0:
        logger.info(f"Surgical Cleanup: Removed {cursor.rowcount} legacy manual trades.")

    # 2. Risk Profiles Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS risk_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conid TEXT NOT NULL,
            ticker TEXT NOT NULL,
            atr_value REAL NOT NULL,
            stop_price REAL,
            inception_stop REAL,
            inception_atr REAL,
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
    # Migration: Add risk fields if they don't exist
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN scale_step REAL DEFAULT 0.5")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN max_r_pct REAL DEFAULT 1.0")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN max_exp_pct REAL DEFAULT 5.0")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN stop_price REAL")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN inception_stop REAL")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN inception_atr REAL")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN profile TEXT")
    except Exception: pass
    # Per-position take-profit override: a multiple of the frozen inception ATR.
    # NULL = use the default TP_ATR_MULTIPLE (3R). See core/stop_loss.py.
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN tp_atr_mult REAL")
    except Exception: pass

    # Migration: Tag existing positions that matched old preset definitions, and update
    # their limits to the new values. The WHERE profile IS NULL guard makes this a no-op
    # after the first run (already-tagged rows are skipped).
    cursor.execute("""
        UPDATE risk_profiles SET profile = 'S', max_exp_pct = 1.5, max_r_pct = 0.30
        WHERE profile IS NULL AND max_exp_pct = 3.0 AND max_r_pct = 0.50
    """)
    cursor.execute("""
        UPDATE risk_profiles SET profile = 'B', max_exp_pct = 3.0, max_r_pct = 0.60
        WHERE profile IS NULL AND max_exp_pct = 4.0 AND max_r_pct = 0.75
    """)
    cursor.execute("""
        UPDATE risk_profiles SET profile = 'L'
        WHERE profile IS NULL AND max_exp_pct = 5.0 AND max_r_pct = 1.00
    """)

    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_active_conid ON risk_profiles(conid) WHERE status = 'ACTIVE'")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_watch_conid ON risk_profiles(conid) WHERE status = 'WATCH'")

    # Migration: Remove Scale-In — convert any remaining SCALE_IN profiles to SINGLE.
    cursor.execute("UPDATE risk_profiles SET entry_type = 'SINGLE' WHERE entry_type = 'SCALE_IN'")

    # Migration: FIXED stop redesign — atr_value now stores the absolute stop price.
    # Old behavior stored the ATR distance (small number); inception_stop stored the computed price.
    # Guard: only migrate rows where atr_value looks like a distance (< half of inception_stop).
    cursor.execute("""
        UPDATE risk_profiles
        SET atr_value = inception_stop,
            highest_sl = MAX(highest_sl, inception_stop)
        WHERE stop_type = 'FIXED'
          AND inception_stop IS NOT NULL
          AND inception_stop > 0
          AND atr_value < (inception_stop * 0.5)
    """)

    # 3. Preset Definitions Table (persists matrix edits across sessions)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS preset_definitions (
            key TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            max_r_pct REAL NOT NULL,
            max_exp_pct REAL NOT NULL
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO preset_definitions VALUES ('S', 'Small',       0.30, 1.5)")
    cursor.execute("INSERT OR IGNORE INTO preset_definitions VALUES ('B', 'Base',        0.60, 3.0)")
    cursor.execute("INSERT OR IGNORE INTO preset_definitions VALUES ('L', 'Large/Index', 1.00, 5.0)")

    # 4. Ticker Info Table (Asset Master)
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

    # 5. App Settings (key-value)
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('action_threshold_pct', '10.0')")
    
    conn.commit()
    conn.close()

def wipe_trades_only():
    """Drops and recreates the trades table, preserving risk profiles."""
    conn = get_conn()
    conn.execute("DROP TABLE IF EXISTS trades")
    conn.commit()
    conn.close()
    init_db()

# Sentinel for set_position_risk: distinguishes "leave the TP override untouched" (default,
# for callers that don't manage it) from an explicit None ("clear the override → default 3R").
_KEEP = object()

def set_position_risk(conid, ticker, atr, stop_type, start_date=None, reset_sl=False, entry_type='SINGLE', scale_step=0.5, status='ACTIVE', max_r_pct=1.0, max_exp_pct=5.0, inception_stop=None, inception_atr=None, profile=None, tp_atr_mult=_KEEP):
    """Saves or updates a risk profile (ACTIVE or WATCH) for a conid.

    tp_atr_mult: take-profit override as a multiple of the inception ATR. Pass a number to
    set it, None to clear it (revert to the default 3R), or omit it (_KEEP sentinel) to leave
    the stored value untouched — unlike the write-once inception fields, this is write-many.
    """
    conn = get_conn()
    conid = str(conid)
    cursor = conn.execute("SELECT id, inception_stop, inception_atr FROM risk_profiles WHERE conid = ? AND status = ?", (conid, status))
    existing = cursor.fetchone()

    if existing:
        sql = """UPDATE risk_profiles SET atr_value = ?, stop_type = ?, entry_type = ?,
                 scale_step = ?, max_r_pct = ?, max_exp_pct = ?, ticker = ?"""
        params = [float(atr), stop_type.upper(), entry_type.upper(), float(scale_step), float(max_r_pct), float(max_exp_pct), ticker.upper()]

        # Only update inception_stop if it's currently NULL and a value is provided
        if existing['inception_stop'] is None and inception_stop is not None:
            sql += ", inception_stop = ?"
            params.append(float(inception_stop))

        # Only update inception_atr if it's currently NULL. Fallback to current atr if no explicit inception_atr provided.
        if existing['inception_atr'] is None:
            sql += ", inception_atr = ?"
            params.append(float(inception_atr) if inception_atr is not None else float(atr))

        if profile is not None:
            sql += ", profile = ?"
            params.append(profile or None)

        # Write-many: set/clear the TP override only when the caller explicitly passes it.
        if tp_atr_mult is not _KEEP:
            sql += ", tp_atr_mult = ?"
            params.append(float(tp_atr_mult) if tp_atr_mult is not None else None)

        if reset_sl:
            sql += ", highest_sl = 0.0"
        sql += " WHERE id = ?"
        params.append(existing['id'])
        conn.execute(sql, tuple(params))
    else:
        # For new profiles, use provided values or current atr/stop as inception
        i_stop = float(inception_stop) if inception_stop is not None else None
        i_atr = float(inception_atr) if inception_atr is not None else float(atr)
        i_tp = float(tp_atr_mult) if (tp_atr_mult is not _KEEP and tp_atr_mult is not None) else None

        conn.execute("""
            INSERT INTO risk_profiles (conid, ticker, atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct, start_date, status, inception_stop, inception_atr, profile, tp_atr_mult)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (conid, ticker.upper(), float(atr), stop_type.upper(), entry_type.upper(), float(scale_step), float(max_r_pct), float(max_exp_pct), start_date, status, i_stop, i_atr, profile or None, i_tp))

    conn.commit()
    conn.close()

def get_watch_list_profiles():
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM risk_profiles WHERE status = 'WATCH'")
    rows = cursor.fetchall()
    conn.close()
    return [RiskProfile.from_row(r) for r in rows]

def get_all_monitored_profiles():
    """Retrieves all risk profiles with status 'WATCH' or 'ACTIVE'."""
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM risk_profiles WHERE status IN ('WATCH', 'ACTIVE') ORDER BY ticker ASC")
    rows = cursor.fetchall()
    conn.close()
    return [RiskProfile.from_row(r) for r in rows]

def promote_prospect_to_active(ticker, real_conid):
    conn = get_conn()
    cursor = conn.execute("SELECT id, atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct, inception_stop, inception_atr FROM risk_profiles WHERE ticker = ? AND status = 'WATCH'", (ticker.upper(),))
    prospect = cursor.fetchone()
    if prospect:
        conn.execute("UPDATE risk_profiles SET status = 'CLOSED', end_date = CURRENT_TIMESTAMP WHERE id = ?", (prospect['id'],))
        conn.execute("""
            INSERT INTO risk_profiles (conid, ticker, atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct, status, start_date, inception_stop, inception_atr)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', CURRENT_TIMESTAMP, ?, ?)
        """, (str(real_conid), ticker.upper(), prospect['atr_value'], prospect['stop_type'], 
              prospect['entry_type'], prospect['scale_step'], prospect['max_r_pct'], prospect['max_exp_pct'], prospect['inception_stop'], prospect['inception_atr']))
        conn.commit()
        logger.info(f"PROMOTED: Prospect {ticker} is now ACTIVE with conid {real_conid}")
    conn.close()

def delete_risk_profile(conid):
    conn = get_conn()
    conn.execute("DELETE FROM risk_profiles WHERE conid = ?", (str(conid),))
    conn.commit()
    conn.close()

def close_risk_profile(conid, end_date):
    conn = get_conn()
    conn.execute("UPDATE risk_profiles SET status = 'CLOSED', end_date = ? WHERE conid = ? AND status = 'ACTIVE'", (end_date, str(conid)))
    conn.commit()
    conn.close()

def update_high_water_mark(conid, sl_price):
    conn = get_conn()
    conn.execute("UPDATE risk_profiles SET highest_sl = MAX(highest_sl, ?) WHERE conid = ? AND status = 'ACTIVE'", (float(sl_price), str(conid)))
    conn.commit()
    conn.close()

def reset_inception_on_reopen(conid, new_start_date):
    """Clear the stale ratchet and frozen inception for a position that went flat (reset-on-zero)
    and was reopened, re-anchoring start_date to the new lot. highest_sl rebuilds from the new
    lot's high-water mark; inception_stop/atr re-freeze on the next stop save. Prevents a prior
    lot's settings (e.g. a ratcheted stop above the new lot's high) from fabricating a breach."""
    conn = get_conn()
    conn.execute(
        "UPDATE risk_profiles SET highest_sl = 0.0, inception_stop = NULL, inception_atr = NULL, "
        "start_date = ? WHERE conid = ? AND status = 'ACTIVE'",
        (new_start_date, str(conid))
    )
    conn.commit()
    conn.close()

def get_all_risk_settings():
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM risk_profiles WHERE status = 'ACTIVE'")
    rows = cursor.fetchall()
    conn.close()
    return {r['conid']: RiskProfile.from_row(r) for r in rows}

def trade_exists(external_id):
    if not external_id: return False
    conn = get_conn()
    cursor = conn.execute("SELECT 1 FROM trades WHERE external_id = ?", (external_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_trade(date, ticker, side, quantity, price, conid, account_id='U0000000', multiplier=1.0, notes="", source="MANUAL", external_id=None):
    conn = get_conn()
    try:
        conid_val = str(conid) if conid is not None else None
        conn.execute(
            """INSERT INTO trades (date, account_id, ticker, side, quantity, price, multiplier, conid, notes, source, external_id) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, account_id, ticker.upper(), side.upper(), float(quantity), float(price), 
             float(multiplier), conid_val, notes, source, external_id)
        )
        conn.commit()
    except sqlite3.IntegrityError: pass 
    finally: conn.close()

def get_conid_for_ticker(ticker):
    conn = get_conn()
    ticker = ticker.upper()
    cursor = conn.execute("SELECT conid FROM ticker_info WHERE ticker_ibkr = ? LIMIT 1", (ticker,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return row['conid']
    cursor = conn.execute("SELECT conid FROM trades WHERE ticker = ? AND conid IS NOT NULL LIMIT 1", (ticker,))
    row = cursor.fetchone()
    conn.close()
    return row['conid'] if row else None

def get_ticker_info(conid):
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM ticker_info WHERE conid = ?", (str(conid),))
    row = cursor.fetchone()
    conn.close()
    return row

def save_ticker_info(conid, ticker_ibkr, ticker_yfinance=None, isin=None, asset_class=None, multiplier=None, description=None, listing_exchange=None, currency=None, underlying_symbol=None):
    conn = get_conn()
    m_val = float(multiplier) if multiplier is not None and str(multiplier).strip() != '' else 1.0
    conn.execute("""
        INSERT INTO ticker_info (conid, ticker_ibkr, ticker_yfinance, isin, asset_class, multiplier, description, listing_exchange, currency, underlying_symbol, last_updated)
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
    """, (str(conid), ticker_ibkr.upper(), ticker_yfinance, isin, asset_class, m_val, description, listing_exchange, currency, underlying_symbol))
    conn.commit()
    conn.close()

def get_yf_ticker(ticker_ibkr):
    conn = get_conn()
    cursor = conn.execute("SELECT ticker_yfinance FROM ticker_info WHERE ticker_ibkr = ? LIMIT 1", (ticker_ibkr.upper(),))
    row = cursor.fetchone()
    conn.close()
    return row['ticker_yfinance'] if row else None

def get_asset_details_from_trades(conid):
    """
    Returns asset metadata (isin, category, etc) from ticker_info for a conid.
    Note: Function name is legacy; metadata now resides primarily in ticker_info Asset Master.
    """
    conn = get_conn()
    cursor = conn.execute("""
        SELECT isin, asset_class as asset_category, listing_exchange, currency, underlying_symbol
        FROM ticker_info WHERE conid = ?
    """, (str(conid),))
    row = cursor.fetchone()
    conn.close()
    return row

def get_kids_config():
    """Returns all rows from kids_config as a list of dicts."""
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM kids_config", conn)
    conn.close()
    return df

def get_kids_trades(account_id, after_date):
    """Returns BUY/SELL trades for the kids account after a given date."""
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql(
        "SELECT side, quantity, price, multiplier FROM trades WHERE account_id = ? AND date > ?",
        conn, params=(account_id, after_date)
    )
    conn.close()
    return df

# ---------------------------------------------------------------------------
# Preset Definitions
# ---------------------------------------------------------------------------

def get_presets() -> dict:
    """Loads preset definitions from the DB (preserves user matrix edits)."""
    conn = get_conn()
    rows = conn.execute("SELECT key, label, max_r_pct, max_exp_pct FROM preset_definitions ORDER BY key").fetchall()
    conn.close()
    return {r['key']: {'label': r['label'], 'max_r_pct': r['max_r_pct'], 'max_exp_pct': r['max_exp_pct']} for r in rows}

def save_preset(key: str, label: str, max_r_pct: float, max_exp_pct: float):
    """Persists a single preset definition change."""
    conn = get_conn()
    conn.execute(
        "UPDATE preset_definitions SET label = ?, max_r_pct = ?, max_exp_pct = ? WHERE key = ?",
        (label, float(max_r_pct), float(max_exp_pct), key)
    )
    conn.commit()
    conn.close()

def get_setting(key: str, default: str = '') -> str:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else default

def save_setting(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def update_preset_profiles(key: str, new_max_r_pct: float, new_max_exp_pct: float):
    """Applies new E%/R% limits to all ACTIVE/WATCH positions tagged with this preset key."""
    conn = get_conn()
    conn.execute(
        "UPDATE risk_profiles SET max_r_pct = ?, max_exp_pct = ? WHERE profile = ? AND status IN ('ACTIVE', 'WATCH')",
        (float(new_max_r_pct), float(new_max_exp_pct), key)
    )
    conn.commit()
    conn.close()
