"""Manual sanity-check for anchored VWAP.

Loads daily bars for one ticker from prices.db, detects the most recent swing
low and swing high, and prints each anchor's date/price and the current AVWAP.
Eyeball against TradingView's Anchored VWAP tool dropped on the same pivot bar.

Usage:
    uv run python -m tools.validate_anchored_vwap VOO
    uv run python -m tools.validate_anchored_vwap VOO --months 12 --window 10
"""

import argparse
import sqlite3

import pandas as pd

from config import PRICES_DB_PATH
from constants import PIVOT_WINDOW
from core.anchored_vwap import compute_anchored_vwaps


def _load_bars(ticker: str, months: int) -> pd.DataFrame:
    conn = sqlite3.connect(PRICES_DB_PATH)
    row = conn.execute(
        "SELECT conid, MAX(date) FROM prices_daily WHERE ticker = ? GROUP BY conid "
        "ORDER BY MAX(date) DESC LIMIT 1",
        (ticker.upper(),),
    ).fetchone()
    if not row:
        conn.close()
        raise SystemExit(f"No price history cached for {ticker.upper()} in prices.db")
    conid, last_date = row
    start = (pd.to_datetime(last_date) - pd.DateOffset(months=months)).strftime("%Y-%m-%d")
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices_daily "
        "WHERE conid = ? AND date >= ? ORDER BY date ASC",
        conn,
        params=(conid, start),
    )
    conn.close()
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate anchored VWAP.")
    ap.add_argument("ticker")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--window", type=int, default=PIVOT_WINDOW)
    args = ap.parse_args()

    bars = _load_bars(args.ticker, args.months)
    last_close = float(bars["close"].iloc[-1])
    out = compute_anchored_vwaps(bars, window=args.window)

    print(f"\n{args.ticker.upper()}  --  {len(bars)} bars (~{args.months}mo), "
          f"pivot window {args.window}")
    print(f"  last close: {last_close:.2f}")
    for label, key in (("swing-low anchor (support)", "low_anchor"),
                       ("swing-high anchor (resist) ", "high_anchor")):
        a = out[key]
        if a is None:
            print(f"  {label}: none detected")
            continue
        rel = "below" if a["vwap"] < last_close else "above"
        print(f"  {label}: anchored {a['date']} @ {a['price']:.2f}  "
              f"->  AVWAP {a['vwap']:.2f} ({rel} price)")


if __name__ == "__main__":
    main()
