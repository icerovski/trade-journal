"""One-off migration: re-stamp `inception_atr` for ACTIVE FIXED risk profiles.

Background
----------
For a FIXED stop the user supplies a stop *price*, not an ATR distance, so the
milestone ladder (M1/M2/TP) had no natural R unit and the UI hardcoded the *daily*
(14d) ATR into `inception_atr`. On deliberately deep stops (e.g. leveraged ETFs)
that made the ladder fire premature signals — M1 tripping at a trivial gain.

The fix (risk_workspace.py FIXED commit path) snaps the risk distance
(entry - stop) to the nearest discovery-ATR timeframe instead. This script applies
the *same* snap retroactively to every existing ACTIVE FIXED profile, using the
identical `get_atr_discovery_data` rows the UI produces, so stored values match what
a fresh re-commit would write.

Usage
-----
    uv run python tools/migrate_fixed_inception_atr.py            # dry-run (prints old -> new)
    uv run python tools/migrate_fixed_inception_atr.py --apply    # write changes to the DB
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse

from db import get_conn
from core.portfolio_manager import PortfolioManager
from core.stop_loss import get_atr_discovery_data
from logger import logger


def _snap_atr(rows, risk_dist):
    """Pick the discovery-ATR value nearest the risk distance, deduped by timeframe label.
    Returns (new_atr, label) or (None, None) if no usable rows."""
    choices = {r.label: r.atr_wilder for r in (rows or [])}
    if not choices or risk_dist <= 0:
        return None, None
    label = min(choices, key=lambda k: abs(choices[k] - risk_dist))
    return choices[label], label


def migrate(apply: bool):
    pm = PortfolioManager()

    conn = get_conn()
    profiles = conn.execute(
        """SELECT conid, ticker, atr_value, inception_stop, inception_atr
           FROM risk_profiles
           WHERE status = 'ACTIVE' AND stop_type = 'FIXED'
           ORDER BY ticker"""
    ).fetchall()
    conn.close()

    if not profiles:
        logger.info("No ACTIVE FIXED profiles found.")
        return

    # Open positions carry the audited reset-on-zero entry price + entry date.
    _, positions = pm.get_dashboard_df(silent=True, include_watch=False)
    pos_map = {str(p.conid): p for p in positions}

    header = f"{'TICKER':10} {'ENTRY':>9} {'STOP':>9} {'RISK_DIST':>9} {'OLD_ATR':>9} {'NEW_ATR':>9} {'TF':>4}"
    print("\n" + header)
    print("-" * len(header))

    updates = []
    for prof in profiles:
        conid = str(prof["conid"])
        ticker = prof["ticker"]
        pos = pos_map.get(conid)
        if not pos or not pos.entry_price or pos.entry_price <= 0:
            print(f"{ticker:10} {'— no open position / entry —':>50}")
            continue

        # The live FIXED stop price is atr_value; risk distance is entry - stop.
        stop = prof["atr_value"]
        if stop is None or stop <= 0:
            print(f"{ticker:10} {'— no stop price —':>50}")
            continue
        risk_dist = abs(pos.entry_price - stop)

        entry_date_str = pos.date_entry.strftime("%Y-%m-%d") if pos.date_entry is not None else ""
        try:
            data = get_atr_discovery_data(
                ticker, entry_date_str, pos.entry_price,
                conid=(conid if not conid.startswith("PROSPECT:") else None),
                qty=pos.qty, inst_multiplier=pos.multiplier, total_nav=0.0,
                mapper=pm.mapper, max_since_entry=getattr(pos, "max_since_entry", 0.0) or 0.0,
            )
        except Exception as e:
            print(f"{ticker:10} discovery failed: {e}")
            continue

        new_atr, tf = _snap_atr((data or {}).get("rows"), risk_dist)
        if new_atr is None:
            print(f"{ticker:10} {'— no discovery ATR rows —':>50}")
            continue

        old_atr = prof["inception_atr"]
        old_str = f"{old_atr:9.3f}" if old_atr is not None else f"{'NULL':>9}"
        print(f"{ticker:10} {pos.entry_price:9.2f} {stop:9.2f} {risk_dist:9.2f} "
              f"{old_str} {new_atr:9.3f} {tf:>4}")
        updates.append((conid, ticker, new_atr))

    if not apply:
        print(f"\nDRY-RUN — {len(updates)} profile(s) would be updated. "
              f"Re-run with --apply to write.\n")
        return

    conn = get_conn()
    for conid, ticker, new_atr in updates:
        conn.execute(
            "UPDATE risk_profiles SET inception_atr = ? WHERE conid = ? AND status = 'ACTIVE' AND stop_type = 'FIXED'",
            (float(new_atr), conid),
        )
    conn.commit()
    conn.close()
    print(f"\nAPPLIED — updated inception_atr on {len(updates)} ACTIVE FIXED profile(s).\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Snap inception_atr for ACTIVE FIXED profiles.")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run).")
    migrate(ap.parse_args().apply)
