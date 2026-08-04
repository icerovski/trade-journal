"""Automated outcome backfill (Entry & Stop System §7) — closes the logging loop.

The decision journal (`trade_log`) is only useful once its *outcome* fields are
populated, and manual backfill never happens in practice. This module fills them
automatically:

  * TAKEN rows with no `realized_r`: detect the position's close from the trades
    ledger (first qty zero-crossing after the log date), then compute
    realized R = (exit − entry) / R₁, MAE/MFE in R from the cached daily bars,
    and result-vs-benchmark over the same window.
  * SKIPPED rows: refresh result-vs-benchmark *to date* on every run — the §0a
    funnel question ("does the source beat the index?") for picks not taken.

Pure core (`find_close_after`, `compute_excursions`, `window_return`) with all
I/O injected; `run_backfill()` is the thin runner wired to db + PriceService,
invoked before the expectancy report renders (menu option 9). Rows that cannot
be resolved (open positions, missing entry/stop/conid, splits mid-trade) are
left untouched and counted — never guessed.

`realized_return_base` (FX-adjusted base-currency return) is deliberately NOT
backfilled here: the FX rate at exit is not recorded, and fabricating it from
today's rate would poison the §7 base-currency review. Left NULL until an
FX-at-exit source exists.
"""

from typing import Optional

from constants import QTY_ZERO_THRESHOLD
from core.trade_log import STATUS_TAKEN, STATUS_SKIPPED
from logger import logger

# Pseudo-conid prefix for the benchmark series cached in prices.db.
BENCHMARK_CONID_PREFIX = "BENCHMARK:"

_BUY_SIDES = {"BUY", "TRANSFER_IN"}
_SELL_SIDES = {"SELL", "TRANSFER_OUT"}


def find_close_after(trades: list[dict], after_date: str) -> Optional[tuple[str, Optional[float]]]:
    """Replay raw trade rows chronologically and find the position close that
    ends the lot a log entry belongs to.

    trades: dicts with date/side/quantity/price/source (db.get_trades_for_conid).
    Mirrors LedgerEngine._apply_trade's sign conventions: quantities are abs()'d,
    side drives direction, OPENING_BALANCE resets the lot, SPLIT is a signed qty
    delta. Returns (close_date, exit_avg_price) for the first zero-crossing
    strictly after `after_date` — exit price is the qty-weighted average of the
    reducing trades between the log date and the close. Returns None while the
    position is still open, and None (deliberately) when a SPLIT lands inside
    the measurement window: post-split prices don't compare to the logged
    entry/stop, so no R is computed rather than a wrong one.
    """
    qty = 0.0
    sells: list[tuple[float, float]] = []  # (qty, price) reductions after the log date
    for t in trades:
        side = str(t.get("side", "")).strip().upper()
        source = str(t.get("source", "") or "").upper()
        q = abs(float(t.get("quantity", 0.0) or 0.0))
        price = float(t.get("price", 0.0) or 0.0)
        date = str(t.get("date", ""))

        if "OPENING_BALANCE" in source or side == "OPENING_BALANCE":
            qty = q
            sells = []
            continue
        if side == "SPLIT":
            if date > after_date:
                return None  # split inside the window — prices no longer comparable
            if qty > 0:
                qty = max(0.0, qty + float(t.get("quantity", 0.0) or 0.0))  # signed delta
            continue
        if side in _BUY_SIDES:
            if qty <= QTY_ZERO_THRESHOLD:
                sells = []  # fresh lot (reset-on-zero re-entry)
            qty += q
        elif side in _SELL_SIDES and qty > 0:
            qty -= q
            if date > after_date:
                sells.append((q, price))
            if qty <= QTY_ZERO_THRESHOLD:
                if date > after_date:
                    total_q = sum(sq for sq, _ in sells)
                    avg = (sum(sq * sp for sq, sp in sells) / total_q) if total_q > 0 else (price or None)
                    return (date, avg)
                qty = 0.0
                sells = []
    return None


def compute_excursions(ohlc_df, entry: float, r1: float) -> tuple[Optional[float], Optional[float]]:
    """MAE/MFE in R units over the holding window, from daily bars.

    MAE = worst adverse excursion = (entry − min Low) / R₁ (floored at 0);
    MFE = best favourable excursion = (max High − entry) / R₁ (floored at 0).
    Returns (None, None) when bars or a positive R₁ are unavailable.
    """
    if ohlc_df is None or getattr(ohlc_df, "empty", True) or not entry or not r1 or r1 <= 0:
        return (None, None)
    cols = ohlc_df.columns
    low_col = "Low" if "Low" in cols else ("low" if "low" in cols else None)
    high_col = "High" if "High" in cols else ("high" if "high" in cols else None)
    if not low_col or not high_col:
        return (None, None)
    mae = max((entry - float(ohlc_df[low_col].min())) / r1, 0.0)
    mfe = max((float(ohlc_df[high_col].max()) - entry) / r1, 0.0)
    return (round(mae, 4), round(mfe, 4))


def window_return(close_df, start_date: str, end_date: Optional[str] = None) -> Optional[float]:
    """Simple close-to-close return over [start_date, end_date] from a daily df
    shaped like PriceService.get_prices (datetime index, 'Close' column).
    Uses the first close on/after start and the last close on/before end
    (or the latest close when end_date is None). None when either edge is missing.
    """
    if close_df is None or getattr(close_df, "empty", True) or "Close" not in close_df.columns:
        return None
    closes = close_df["Close"].dropna()
    if closes.empty:
        return None
    start_slice = closes[closes.index >= start_date]
    if start_slice.empty:
        return None
    start_px = float(start_slice.iloc[0])
    end_slice = closes[closes.index <= end_date] if end_date else closes
    if end_slice.empty:
        return None
    end_px = float(end_slice.iloc[-1])
    if start_px <= 0:
        return None
    return end_px / start_px - 1.0


def run_backfill() -> dict:
    """Fill outcome fields on the decision journal. Returns summary counts:
    {'closed': n TAKEN rows backfilled, 'skipped': n SKIPPED rows refreshed,
     'open': still-open TAKEN rows, 'unresolved': rows missing data}.
    Never raises for a single bad row — it logs and moves on."""
    from db import get_trade_log_entries, update_trade_log_entry, get_trades_for_conid, get_setting
    from services.price_service import PriceService

    ps = PriceService()
    bench_ticker = (get_setting("benchmark_ticker", "SPY") or "SPY").strip().upper()
    bench_conid = f"{BENCHMARK_CONID_PREFIX}{bench_ticker}"
    try:
        ps.fetch_and_store(bench_conid, bench_ticker)
    except Exception as e:
        logger.warning(f"[backfill] benchmark fetch failed ({bench_ticker}): {e} — using cache")
    bench_df = ps.get_prices(bench_conid)

    summary = {"closed": 0, "skipped": 0, "open": 0, "unresolved": 0}
    for e in get_trade_log_entries():
        try:
            if e.status == STATUS_SKIPPED:
                # Funnel refresh: pick return to date vs benchmark to date.
                if not (e.conid and e.entry and e.entry > 0 and e.date):
                    summary["unresolved"] += 1
                    continue
                latest = ps.latest_close(e.conid)
                bench_ret = window_return(bench_df, e.date)
                if latest is None or bench_ret is None:
                    summary["unresolved"] += 1
                    continue
                pick_ret = latest / e.entry - 1.0
                update_trade_log_entry(e.id, result_vs_benchmark=round(pick_ret - bench_ret, 6))
                summary["skipped"] += 1
                continue

            # TAKEN: only rows not yet backfilled and resolvable to a lot.
            if e.realized_r is not None:
                continue
            r1 = e.r1 if (e.r1 and e.r1 > 0) else (
                (e.entry - e.stop) if (e.entry and e.stop and e.entry > e.stop) else None
            )
            if not (e.conid and e.date and e.entry and r1):
                summary["unresolved"] += 1
                continue
            close = find_close_after(get_trades_for_conid(e.conid), e.date)
            if close is None:
                summary["open"] += 1
                continue
            close_date, exit_avg = close
            if not exit_avg:
                summary["unresolved"] += 1
                continue
            realized_r = round((exit_avg - e.entry) / r1, 4)
            mae, mfe = compute_excursions(
                ps.get_prices(e.conid, start_date=e.date, end_date=close_date), e.entry, r1
            )
            bench_ret = window_return(bench_df, e.date, close_date)
            vs_bench = (
                round((exit_avg / e.entry - 1.0) - bench_ret, 6) if bench_ret is not None else None
            )
            update_trade_log_entry(
                e.id, realized_r=realized_r, mae_r=mae, mfe_r=mfe, result_vs_benchmark=vs_bench
            )
            summary["closed"] += 1
        except Exception as ex:
            logger.warning(f"[backfill] row id={e.id} ({e.ticker}): {ex}")
            summary["unresolved"] += 1
    return summary
