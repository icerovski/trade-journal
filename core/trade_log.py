"""Trade journal log (Entry & Stop System §7) — the professional-grade logging loop.

One record per *decision*: trades taken AND source picks skipped (so the funnel
itself can be benchmarked, §0a). This is deliberately separate from the `trades`
execution ledger — `trades` holds broker fills; `trade_log` is the analyst's
decision journal carrying source, THESIS/TECHNICAL tag, structural context, and
realized-outcome fields that feed the Phase-5 expectancy report.

Additive by design: every field is optional and defaults to empty, so a row
written with only a ticker + date loads and saves cleanly, and later phases can
backfill the outcome fields (realized R, MAE/MFE, vs-benchmark) without a
migration. `COLUMN_TYPES` is the single source of truth for the schema — db.py
builds its CREATE TABLE and additive ALTERs from it, so the table and the
dataclass cannot drift.
"""

from dataclasses import dataclass, fields
from typing import Optional

# status values — a log entry is either a taken trade or a skipped source pick.
STATUS_TAKEN = "TAKEN"
STATUS_SKIPPED = "SKIPPED"

# classification values (§0a). Empty string = unset (default; carried, not acted on).
CLASS_THESIS = "THESIS"
CLASS_TECHNICAL = "TECHNICAL"

# Ordered column -> SQLite type. `id` and `created_at` are DB-managed and handled
# separately in db.py. Booleans are stored as INTEGER (0/1/NULL) and coerced back
# to bool on load. This dict is the single source of truth for the schema.
COLUMN_TYPES = {
    # identity
    "date": "TEXT",
    "ticker": "TEXT",
    "conid": "TEXT",
    "status": "TEXT",
    # sourcing / classification (§0a, §7)
    "source": "TEXT",
    "took_independently": "INTEGER",  # "would I have taken it independently?"
    "theme": "TEXT",
    "classification": "TEXT",          # THESIS | TECHNICAL | "" (unset)
    "regime": "TEXT",
    "archetype": "TEXT",
    # structural context (§4, scanner)
    "stop_source": "TEXT",
    "flagged": "INTEGER",
    "confluence_count": "INTEGER",
    "event_adjacent": "INTEGER",
    # geometry (§0, §3)
    "entry": "REAL",
    "stop": "REAL",
    "r1": "REAL",                      # initial risk per share = entry - stop
    "r_pct": "REAL",                   # R% of NAV
    "atr_period": "TEXT",              # e.g. "ATR14-daily"
    "atr_value": "REAL",
    # realized outcome (§7) — backfilled at/after exit
    "realized_r": "REAL",
    "realized_return_base": "REAL",    # FX-adjusted base-currency return
    "result_vs_benchmark": "REAL",     # vs a benchmark over the same window
    "mae_r": "REAL",                   # worst excursion in R before exit
    "mfe_r": "REAL",                   # best excursion in R before exit
    # freeform
    "notes": "TEXT",
}

# Columns persisted by db.py, in insert order. `id`/`created_at` are DB-managed.
PERSISTED_FIELDS = list(COLUMN_TYPES)

# Fields stored as INTEGER but exposed as bool on the dataclass.
BOOL_FIELDS = ("took_independently", "flagged", "event_adjacent")


@dataclass
class TradeLogEntry:
    """One decision-journal row. Every field optional so partial rows are valid."""

    # identity
    date: str = ""                     # decision date (YYYY-MM-DD)
    ticker: str = ""
    conid: Optional[str] = None
    status: str = STATUS_TAKEN         # TAKEN | SKIPPED

    # sourcing / classification
    source: str = ""
    took_independently: Optional[bool] = None
    theme: str = ""
    classification: str = ""           # THESIS | TECHNICAL | "" (unset)
    regime: str = ""
    archetype: str = ""

    # structural context
    stop_source: str = ""
    flagged: Optional[bool] = None
    confluence_count: Optional[int] = None
    event_adjacent: Optional[bool] = None

    # geometry
    entry: Optional[float] = None
    stop: Optional[float] = None
    r1: Optional[float] = None
    r_pct: Optional[float] = None
    atr_period: str = ""
    atr_value: Optional[float] = None

    # realized outcome (backfilled later)
    realized_r: Optional[float] = None
    realized_return_base: Optional[float] = None
    result_vs_benchmark: Optional[float] = None
    mae_r: Optional[float] = None
    mfe_r: Optional[float] = None

    # freeform
    notes: str = ""

    # db bookkeeping
    id: Optional[int] = None
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "TradeLogEntry":
        """Build from a DB row, ignoring unknown/legacy columns (mirrors
        RiskProfile.from_row) and coercing INTEGER bool columns back to bool."""
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in dict(row).items() if k in known}
        for b in BOOL_FIELDS:
            if data.get(b) is not None:
                data[b] = bool(data[b])
        return cls(**data)
