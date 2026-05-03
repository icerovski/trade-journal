"""Standalone subprocess entry point for price charts.
Spawned by chart_utils.launch_price_chart — never imported directly.
Usage: python chart_worker.py <display_ticker> <conid_or_empty> <yf_ticker>
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root for core/services imports
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import yfinance as yf


def main() -> None:
    if len(sys.argv) < 4:
        return
    display_ticker = sys.argv[1]
    conid = sys.argv[2] or None
    yf_ticker = sys.argv[3] or display_ticker

    df = None
    if conid:
        from services.price_service import PriceService
        ps = PriceService()
        df = ps.get_prices(str(conid))

    if df is None or df.empty:
        cutoff = (pd.Timestamp.now() - pd.DateOffset(years=5)).strftime('%Y-%m-%d')
        raw = yf.download(yf_ticker, start=cutoff, interval='1d', progress=False, auto_adjust=True)
        if not raw.empty:
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            df = raw

    if df is None or df.empty:
        return

    cutoff_ts = pd.Timestamp.now() - pd.DateOffset(years=5)
    df = df[df.index >= cutoff_ts]
    close = df['Close'].dropna()
    dma200 = close.rolling(200).mean()

    fig, ax = plt.subplots(figsize=(13, 6))
    fig.patch.set_facecolor('#1e1e2e')
    ax.set_facecolor('#1e1e2e')
    ax.plot(close.index, close, label='Price', color='#4C9BE8', linewidth=1.2)
    ax.plot(dma200.index, dma200, label='200 DMA', color='#F4A261', linewidth=1.8)
    ax.set_title(f'{display_ticker}  —  Price & 200 DMA  (5Y)', color='white', fontsize=13, pad=12)
    ax.tick_params(colors='#aaaaaa')
    for spine in ax.spines.values():
        spine.set_edgecolor('#444444')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:,.0f}'))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    fig.autofmt_xdate()
    ax.legend(facecolor='#2e2e3e', edgecolor='#444444', labelcolor='white')
    ax.grid(True, color='#333344', linewidth=0.5)
    plt.tight_layout()
    plt.show(block=True)


if __name__ == '__main__':
    main()
