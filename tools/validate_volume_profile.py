"""Manual sanity-check for the composite volume profile.

Loads daily bars for one ticker from the existing prices.db cache, builds the
6mo and 12mo profiles, and prints POC/VAH/VAL plus an ASCII histogram so the
computed levels can be eyeballed against a known reference (e.g. TradingView's
fixed-range volume profile for the same ticker and window).

Usage:
    uv run python -m tools.validate_volume_profile GOOG
    uv run python -m tools.validate_volume_profile GOOG --months 6
"""

import argparse
import sqlite3

import pandas as pd

from config import PRICES_DB_PATH
from constants import VP_LOOKBACKS_MONTHS
from core.volume_profile import compute_volume_profile, find_naked_pocs


def _load_bars(ticker: str, months: int) -> pd.DataFrame:
    """Pull the trailing `months` of daily bars for `ticker` from prices.db.

    Resolves the most-recently-used conid for the ticker (the cache is keyed by
    conid; a ticker can in principle map to more than one).
    """
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


def _ascii_hist(profile: dict, width: int = 50) -> str:
    hist = profile["hist"]
    vmax = hist["volume"].max()
    if vmax <= 0:
        return "(empty)"
    poc, vah, val = profile["poc"], profile["vah"], profile["val"]
    lines = []
    # Print high price at top, low at bottom. Use ASCII so it renders on any
    # console codepage (Windows cp1251/cp437 chokes on block glyphs).
    for _, r in hist[::-1].iterrows():
        bar = "#" * int(round(r["volume"] / vmax * width))
        tag = ""
        if abs(r["price"] - poc) < 1e-9:
            tag = " <- POC"
        elif abs(r["price"] - vah) < 1e-9:
            tag = " <- VAH"
        elif abs(r["price"] - val) < 1e-9:
            tag = " <- VAL"
        lines.append(f"{r['price']:>10.2f} | {bar}{tag}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate the composite volume profile.")
    ap.add_argument("ticker")
    ap.add_argument("--months", type=int, default=None,
                    help="Single lookback to inspect; default runs all VP_LOOKBACKS_MONTHS.")
    args = ap.parse_args()

    lookbacks = (args.months,) if args.months else VP_LOOKBACKS_MONTHS

    for months in lookbacks:
        bars = _load_bars(args.ticker, months)
        profile = compute_volume_profile(bars)
        print(f"\n{'=' * 60}")
        print(f"{args.ticker.upper()}  --  {months}-month profile  ({len(bars)} bars)")
        print(f"{'=' * 60}")
        if not profile:
            print("  insufficient data")
            continue
        print(f"  POC: {profile['poc']:.2f}   VAH: {profile['vah']:.2f}   "
              f"VAL: {profile['val']:.2f}   bucket: {profile['bucket_width']:.3f}")
        naked = find_naked_pocs(bars, profile)
        if naked:
            shelves = ", ".join(f"{n['price']:.2f}({n['side']})" for n in naked[:5])
            print(f"  naked shelves: {shelves}")
        print()
        print(_ascii_hist(profile))

    print("\nNote: volume profile is a daily-bar approximation, not tick-derived.")


if __name__ == "__main__":
    main()
