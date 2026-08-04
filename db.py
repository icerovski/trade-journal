# db.py
import sqlite3
from config import DB_PATH
from logger import logger
from models import RiskProfile
from core.trade_log import TradeLogEntry, COLUMN_TYPES, PERSISTED_FIELDS

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# One-shot data migrations
#
# The CREATE TABLE / ALTER statements in init_db are structurally idempotent and
# re-run harmlessly on every startup. These are different: they MUTATE user rows,
# and their WHERE clauses are historical guards, not permanent invariants. A guard
# that only matched legacy rows in 2026 can match a perfectly legitimate row later
# — the FIXED-stop rewrite below would then overwrite a deliberately deep stop with
# the frozen inception stop AND ratchet highest_sl up to match, fabricating a breach
# on a position the user had just re-stopped. Re-running a destructive migration
# forever is a latent corruption path, so each one is recorded in schema_migrations
# after it runs and can never fire again.
#
# Appending a new entry is the migration mechanism: give it a fresh name and it
# runs once, on the next startup, on every installation.
# ---------------------------------------------------------------------------
_ONE_SHOT_MIGRATIONS = (
    # Manual trade entry was removed; no code path can create a MANUAL row any more
    # (every services/ibkr_parser.py ingest passes an explicit IBKR_* source), so
    # this is a pure one-time purge of pre-removal rows.
    ("001_purge_legacy_manual_trades", """
        DELETE FROM trades WHERE source = 'MANUAL'
    """),
    # Tag positions matching the old preset definitions and move them to the new
    # limits. Guarded on profile IS NULL, i.e. never re-tag an already-tagged row.
    ("002_tag_preset_small", """
        UPDATE risk_profiles SET profile = 'S', max_exp_pct = 1.5, max_r_pct = 0.30
        WHERE profile IS NULL AND max_exp_pct = 3.0 AND max_r_pct = 0.50
    """),
    ("003_tag_preset_base", """
        UPDATE risk_profiles SET profile = 'B', max_exp_pct = 3.0, max_r_pct = 0.60
        WHERE profile IS NULL AND max_exp_pct = 4.0 AND max_r_pct = 0.75
    """),
    ("004_tag_preset_large", """
        UPDATE risk_profiles SET profile = 'L'
        WHERE profile IS NULL AND max_exp_pct = 5.0 AND max_r_pct = 1.00
    """),
    # Scale-In was removed — entry type is always SINGLE.
    ("005_convert_scale_in_to_single", """
        UPDATE risk_profiles SET entry_type = 'SINGLE' WHERE entry_type = 'SCALE_IN'
    """),
    # FIXED-stop redesign: atr_value now stores the absolute stop PRICE, where it
    # previously stored the ATR distance. The "looks like a distance" heuristic is
    # exactly why this must never run twice — a legitimate stop below half the
    # inception stop (a leveraged name that halved and was re-stopped) matches it.
    ("006_fixed_stop_atr_value_is_price", """
        UPDATE risk_profiles
        SET atr_value = inception_stop,
            highest_sl = MAX(highest_sl, inception_stop)
        WHERE stop_type = 'FIXED'
          AND inception_stop IS NOT NULL
          AND inception_stop > 0
          AND atr_value < (inception_stop * 0.5)
    """),
)


def _apply_one_shot_migrations(cursor):
    """Run any migration in _ONE_SHOT_MIGRATIONS not yet recorded, then record it.

    Called from init_db once the tables the migrations touch exist. On an
    established database the pending set is every migration on the first startup
    after this mechanism ships — the same statements that have been running on
    every startup until now, so that final pass changes nothing that was not
    already changed — and empty on every startup after that.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    applied = {r[0] for r in cursor.execute("SELECT name FROM schema_migrations").fetchall()}

    for name, sql in _ONE_SHOT_MIGRATIONS:
        if name in applied:
            continue
        cursor.execute(sql)
        if cursor.rowcount > 0:
            logger.info(f"Migration {name}: {cursor.rowcount} row(s) affected.")
        cursor.execute("INSERT INTO schema_migrations (name) VALUES (?)", (name,))


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
    # THESIS / TECHNICAL classification (Entry & Stop System §0a). NULL = unset.
    # Carried only — no exit logic branches on it. See core/stop_loss.py.
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN classification TEXT")
    except Exception: pass
    # Exit shape (§5a): NULL/LADDER = today's default ladder; HARD / THESIS (RUNNER = legacy alias).
    # See core/exit_shapes.py. Default reproduces current exit behaviour exactly.
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN exit_shape TEXT")
    except Exception: pass
    # Pricing currency of a WATCH prospect, resolved from yfinance at add time.
    # NULL = unknown (legacy rows) — consumers fall back to USD, the pre-existing guess.
    # Needed so prospect sizing borrows the RIGHT ccy->NAV fx rate (fix 2026-07-04).
    try:
        cursor.execute("ALTER TABLE risk_profiles ADD COLUMN ccy TEXT")
    except Exception: pass

    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_active_conid ON risk_profiles(conid) WHERE status = 'ACTIVE'")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_watch_conid ON risk_profiles(conid) WHERE status = 'WATCH'")

    # Historical data migrations — run exactly once each (see _apply_one_shot_migrations).
    _apply_one_shot_migrations(cursor)

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
    # Entry-gate mode (Entry & Stop System §4): off | advisory | blocking. Default off
    # reproduces today's behaviour exactly — no gate evaluation in the pre-trade flow.
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('gates_mode', 'off')")
    # Horizon calibration lens (Horizon_Calibration_3to6mo.md): default | position_3to6mo.
    # Default keeps today's short-swing scan; see core/calibration.py.
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('calibration_profile', 'default')")
    # Regime lens (TECHNICAL_DOCS §5): default | horizon. Default = 200-DMA for all.
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('regime_lens', 'default')")
    # Benchmark for the §0a funnel (source picks vs index). Cached in prices.db
    # under the pseudo-conid BENCHMARK:<ticker> by the outcome backfill.
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('benchmark_ticker', 'SPY')")

    # 6. Trade Journal Log (Entry & Stop System §7) — decision journal, separate
    # from the `trades` execution ledger. Schema is driven by core.trade_log so it
    # cannot drift from the dataclass. Every column is nullable/defaulted, and the
    # per-column ALTER loop is the additive migration: old rows gain new columns as
    # NULL and keep loading/saving. See core/trade_log.py.
    _trade_log_cols = ",\n            ".join(f"{name} {typ}" for name, typ in COLUMN_TYPES.items())
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            {_trade_log_cols}
        )
    """)
    for name, typ in COLUMN_TYPES.items():
        try:
            cursor.execute(f"ALTER TABLE trade_log ADD COLUMN {name} {typ}")
        except Exception:
            pass

    # Structural context from the latest zone scan, per ticker (Entry & Stop §4).
    # Written by the zone-scanner workspace after each scan; read by the risk
    # workspace's gate check (freshness-guarded) so G2/G3/G5 get real inputs.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_context (
            ticker TEXT PRIMARY KEY,
            scan_date TEXT,
            regime TEXT,
            flagged INTEGER,
            confluence_count INTEGER,
            stop_source TEXT,
            stop_price REAL,
            trail_anchor REAL,
            tag TEXT
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

# Sentinel for set_position_risk: distinguishes "leave the TP override untouched" (default,
# for callers that don't manage it) from an explicit None ("clear the override → default 3R").
_KEEP = object()

def set_position_risk(conid, ticker, atr, stop_type, start_date=None, reset_sl=False, entry_type='SINGLE', scale_step=0.5, status='ACTIVE', max_r_pct=1.0, max_exp_pct=5.0, inception_stop=None, inception_atr=None, profile=None, tp_atr_mult=_KEEP, classification=_KEEP, exit_shape=_KEEP, ccy=None):
    """Saves or updates a risk profile (ACTIVE or WATCH) for a conid.

    tp_atr_mult: take-profit override as a multiple of the inception ATR. Pass a number to
    set it, None to clear it (revert to the default 3R), or omit it (_KEEP sentinel) to leave
    the stored value untouched — unlike the write-once inception fields, this is write-many.

    classification: THESIS / TECHNICAL tag (§0a). Pass a string to set it, "" or None to clear
    it (unset), or omit it (_KEEP) to leave the stored value untouched. Write-many.

    exit_shape: §5a exit shape (HARD / THESIS; RUNNER = legacy alias of the default; "" or None
    → default ladder). Pass a string to set it, "" / None to clear (default), or omit it
    (_KEEP) to leave untouched. Write-many.

    ccy: pricing currency of a WATCH prospect (e.g. from yfinance at add time). Pass a string
    to set it; None leaves the stored value untouched (legacy rows stay NULL → USD assumed).
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

        # Write-many: set/clear the classification only when explicitly passed.
        if classification is not _KEEP:
            sql += ", classification = ?"
            params.append(classification or None)

        # Write-many: set/clear the exit shape only when explicitly passed.
        if exit_shape is not _KEEP:
            sql += ", exit_shape = ?"
            params.append(exit_shape or None)

        # Pricing currency: set only when the caller resolved one (never clears).
        # Case preserved — 'GBp' (pence) must not become 'GBP' (pounds).
        if ccy is not None:
            sql += ", ccy = ?"
            params.append(str(ccy).strip())

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
        i_class = classification or None if classification is not _KEEP else None
        i_shape = exit_shape or None if exit_shape is not _KEEP else None
        i_ccy = str(ccy).strip() if ccy else None  # case preserved: 'GBp' != 'GBP'

        conn.execute("""
            INSERT INTO risk_profiles (conid, ticker, atr_value, stop_type, entry_type, scale_step, max_r_pct, max_exp_pct, start_date, status, inception_stop, inception_atr, profile, tp_atr_mult, classification, exit_shape, ccy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (conid, ticker.upper(), float(atr), stop_type.upper(), entry_type.upper(), float(scale_step), float(max_r_pct), float(max_exp_pct), start_date, status, i_stop, i_atr, profile or None, i_tp, i_class, i_shape, i_ccy))

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

# Columns carried from a WATCH prospect onto the ACTIVE profile it becomes.
# Everything the user decided while the idea was on the watch list must survive
# the promotion — an omission here silently discards a preset tag, a THESIS
# classification, an exit shape or a TP override the moment the trade is filled,
# with no user action to associate the loss with (promotion runs automatically
# during dashboard consolidation). `highest_sl` is deliberately NOT carried: the
# ratchet belongs to the lot, and a new lot starts from zero.
_PROMOTED_COLUMNS = (
    'atr_value', 'stop_type', 'entry_type', 'scale_step', 'max_r_pct', 'max_exp_pct',
    'inception_stop', 'inception_atr', 'profile', 'tp_atr_mult', 'classification',
    'exit_shape', 'ccy',
)

def promote_prospect_to_active(ticker, real_conid):
    """Convert a WATCH prospect into the ACTIVE profile for its real conid.

    Called during dashboard consolidation for every held position, so it must be
    a cheap no-op when there is nothing to promote, and must never raise: an
    ACTIVE profile already existing for this conid (possible — the ACTIVE and
    WATCH unique indexes are independent) would otherwise hit idx_active_conid
    and take the whole dashboard down. In that case the existing ACTIVE profile
    wins untouched and the redundant WATCH row is simply retired.
    """
    conn = get_conn()
    try:
        prospect = conn.execute(
            "SELECT * FROM risk_profiles WHERE ticker = ? AND status = 'WATCH'",
            (ticker.upper(),)
        ).fetchone()
        if not prospect:
            return

        conn.execute("UPDATE risk_profiles SET status = 'CLOSED', end_date = CURRENT_TIMESTAMP WHERE id = ?", (prospect['id'],))

        already_active = conn.execute(
            "SELECT id FROM risk_profiles WHERE conid = ? AND status = 'ACTIVE'",
            (str(real_conid),)
        ).fetchone()
        if already_active:
            conn.commit()
            logger.info(
                f"PROMOTE SKIPPED: {ticker} (conid {real_conid}) already has an ACTIVE profile; "
                f"retired the redundant WATCH row without overwriting it."
            )
            return

        # Column names come from the module constant above, never from input.
        # start_date stays the SQL keyword (as before) — it cannot be bound.
        row = dict(prospect)
        columns = ('conid', 'ticker', 'status') + _PROMOTED_COLUMNS
        values = (str(real_conid), ticker.upper(), 'ACTIVE') + tuple(
            row.get(col) for col in _PROMOTED_COLUMNS
        )
        conn.execute(
            f"INSERT INTO risk_profiles (start_date, {', '.join(columns)}) "
            f"VALUES (CURRENT_TIMESTAMP, {', '.join('?' for _ in columns)})",
            values,
        )
        conn.commit()
        logger.info(f"PROMOTED: Prospect {ticker} is now ACTIVE with conid {real_conid}")
    finally:
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

_RATCHET_SQL = ("UPDATE risk_profiles SET highest_sl = MAX(highest_sl, ?) "
                "WHERE conid = ? AND status = 'ACTIVE'")

def update_high_water_mark(conid, sl_price):
    conn = get_conn()
    conn.execute(_RATCHET_SQL, (float(sl_price), str(conid)))
    conn.commit()
    conn.close()

def update_high_water_marks(pairs):
    """Advance several trailing stops in one transaction.

    `pairs` is an iterable of (conid, sl_price). The batched form exists because
    the ratchet is computed for every position on every dashboard refresh — one
    connection per position turned a read into dozens of writes. `MAX(highest_sl, ?)`
    keeps the rule in SQL: a stop only ever moves in the trader's favour, so an
    out-of-order or stale batch can never lower one.

    An empty batch opens no connection — an idle refresh stays genuinely read-only.
    """
    rows = [(float(sl), str(conid)) for conid, sl in pairs]
    if not rows:
        return
    conn = get_conn()
    try:
        conn.executemany(_RATCHET_SQL, rows)
        conn.commit()
    finally:
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

# Upsert that never overwrites a known value with a blank one: every field
# COALESCEs to the stored value when the incoming one is empty, so a sparse feed
# (a CSV missing ISINs, say) enriches the asset master instead of eroding it.
_TICKER_INFO_UPSERT = """
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
"""


def _ticker_info_params(conid, ticker_ibkr, ticker_yfinance=None, isin=None, asset_class=None,
                        multiplier=None, description=None, listing_exchange=None,
                        currency=None, underlying_symbol=None):
    """Bind order for _TICKER_INFO_UPSERT. Single source so the row and bulk forms
    cannot drift apart."""
    m_val = float(multiplier) if multiplier is not None and str(multiplier).strip() != '' else 1.0
    return (str(conid), ticker_ibkr.upper(), ticker_yfinance, isin, asset_class, m_val,
            description, listing_exchange, currency, underlying_symbol)


def save_ticker_info(conid, ticker_ibkr, ticker_yfinance=None, isin=None, asset_class=None, multiplier=None, description=None, listing_exchange=None, currency=None, underlying_symbol=None):
    conn = get_conn()
    try:
        conn.execute(_TICKER_INFO_UPSERT, _ticker_info_params(
            conid, ticker_ibkr, ticker_yfinance, isin, asset_class, multiplier,
            description, listing_exchange, currency, underlying_symbol))
        conn.commit()
    finally:
        conn.close()


def save_ticker_info_bulk(rows):
    """Upsert many asset-master rows in one transaction.

    `rows` is an iterable of dicts keyed like `save_ticker_info`'s parameters. Used
    by the broker-snapshot parse, which previously opened one connection per
    position — 45 writes buried inside what reads as a pure CSV read. An empty
    batch opens no connection.
    """
    params = [_ticker_info_params(**row) for row in rows]
    if not params:
        return
    conn = get_conn()
    try:
        conn.executemany(_TICKER_INFO_UPSERT, params)
        conn.commit()
    finally:
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

# ---------------------------------------------------------------------------
# Trade Journal Log (Entry & Stop System §7)
# ---------------------------------------------------------------------------

def add_trade_log_entry(entry) -> int:
    """Insert a decision-journal row. Accepts a TradeLogEntry or a plain dict;
    every field is optional (a row with only date/ticker is valid). Booleans are
    passed through as-is (SQLite stores them as 0/1). Returns the new row id."""
    # Normalise a plain dict through the dataclass so unspecified fields take the
    # dataclass defaults ("" / None) rather than being stored as bare NULLs.
    if not isinstance(entry, TradeLogEntry):
        entry = TradeLogEntry.from_row(entry)
    data = {k: getattr(entry, k) for k in PERSISTED_FIELDS}
    if data.get("ticker"):
        data["ticker"] = str(data["ticker"]).upper()

    placeholders = ", ".join("?" for _ in PERSISTED_FIELDS)
    columns = ", ".join(PERSISTED_FIELDS)
    values = [data[k] for k in PERSISTED_FIELDS]

    conn = get_conn()
    cursor = conn.execute(
        f"INSERT INTO trade_log ({columns}) VALUES ({placeholders})", values
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def get_trade_log_entries(status=None, ticker=None):
    """Load decision-journal rows as TradeLogEntry objects, oldest first.
    Optionally filter by status (TAKEN/SKIPPED) and/or ticker."""
    query = "SELECT * FROM trade_log"
    conds, params = [], []
    if status:
        conds.append("status = ?")
        params.append(status)
    if ticker:
        conds.append("ticker = ?")
        params.append(str(ticker).upper())
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY date ASC, id ASC"

    conn = get_conn()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [TradeLogEntry.from_row(r) for r in rows]

def get_trades_for_conid(conid):
    """Chronological raw trade rows for one instrument, as plain dicts — the
    minimal feed for core/outcome_backfill's zero-crossing replay. Deliberately
    NOT a Position source (that is LedgerEngine's job); this is read-only."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, side, quantity, price, source FROM trades WHERE conid = ? ORDER BY date ASC, id ASC",
        (str(conid),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_scan_context(rows):
    """Persist per-ticker structural context from a zone scan (§4 gate inputs):
    regime, flagged, independent confluence count, stop_source/price, DMA trail
    anchor. REPLACE per ticker — the latest scan wins; consumers apply their own
    freshness window via get_scan_context(max_age_days)."""
    from datetime import date
    today = date.today().isoformat()
    conn = get_conn()
    for r in rows:
        ticker = (r.get("ticker") or "").upper()
        if not ticker:
            continue
        conn.execute(
            "REPLACE INTO scan_context (ticker, scan_date, regime, flagged, confluence_count, "
            "stop_source, stop_price, trail_anchor, tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, today, r.get("regime") or "",
             (1 if r.get("flagged") else 0) if r.get("flagged") is not None else None,
             r.get("confluence_count"), r.get("stop_source") or "",
             r.get("stop_price"), r.get("trail_anchor"), r.get("tag") or ""),
        )
    conn.commit()
    conn.close()


def get_scan_context(ticker, max_age_days=None):
    """Latest scan context for a ticker as a dict, or None when absent or older
    than `max_age_days` (stale structure must degrade gates to NA, not misfire)."""
    from datetime import date
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM scan_context WHERE ticker = ?", ((ticker or "").upper(),)
    ).fetchone()
    conn.close()
    if not row:
        return None
    ctx = dict(row)
    if max_age_days is not None:
        try:
            age = (date.today() - date.fromisoformat(ctx.get("scan_date") or "")).days
        except ValueError:
            return None
        if age > max_age_days:
            return None
    if ctx.get("flagged") is not None:
        ctx["flagged"] = bool(ctx["flagged"])
    return ctx


def avg_sell_price_since(conid, since_date):
    """Qty-weighted average SELL price for a conid since a date — the realized
    exit basis for §7 backfill suggestions. None when no sells exist yet."""
    conn = get_conn()
    row = conn.execute(
        "SELECT SUM(quantity * price) / SUM(quantity) AS avg_px FROM trades "
        "WHERE conid = ? AND side = 'SELL' AND quantity > 0 AND date >= ?",
        (str(conid), since_date or ""),
    ).fetchone()
    conn.close()
    return float(row["avg_px"]) if row and row["avg_px"] is not None else None


def find_open_trade_log_id(conid):
    """Id of the most recent OPEN decision row for a conid — a TAKEN entry whose
    outcome has not been backfilled (realized_r IS NULL). One decision, one row:
    re-committing the same open lot must UPDATE this row, not append a duplicate
    that would double-count the lot in the expectancy report. Returns None when
    the last decision was closed out (a fresh lot starts a fresh row)."""
    if conid is None:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM trade_log WHERE conid = ? AND status = ? AND realized_r IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (str(conid), "TAKEN"),
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def update_trade_log_entry(entry_id, **fields):
    """Backfill/patch a decision-journal row (e.g. realized R, MAE/MFE at exit).
    Unknown keys are ignored so callers can pass a superset safely."""
    updates = {k: v for k, v in fields.items() if k in PERSISTED_FIELDS}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = get_conn()
    conn.execute(
        f"UPDATE trade_log SET {set_clause} WHERE id = ?",
        (*updates.values(), entry_id),
    )
    conn.commit()
    conn.close()
