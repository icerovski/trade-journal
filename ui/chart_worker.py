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

    _attach_hover(fig, ax, close, dma200)

    plt.show(block=True)


def _attach_hover(fig, ax, close, dma200) -> None:
    """Snapping crosshair + tooltip that reads off date/Price/200 DMA on mouse move."""
    import numpy as np

    x_nums = mdates.date2num(close.index.to_pydatetime())

    vline = ax.axvline(close.index[0], color='#888888', linewidth=0.7, linestyle='--', visible=False)
    marker = ax.plot([], [], 'o', color='#4C9BE8', markersize=5, visible=False)[0]
    annot = ax.annotate(
        '', xy=(0, 0), xytext=(12, 12), textcoords='offset points',
        bbox=dict(boxstyle='round,pad=0.5', fc='#2e2e3e', ec='#444444', alpha=0.95),
        color='white', fontsize=9, visible=False, zorder=10,
    )

    def on_move(event):
        if event.inaxes is not ax or event.xdata is None:
            if annot.get_visible():
                vline.set_visible(False)
                marker.set_visible(False)
                annot.set_visible(False)
                fig.canvas.draw_idle()
            return

        i = int(np.searchsorted(x_nums, event.xdata))
        if i >= len(x_nums):
            i = len(x_nums) - 1
        if i > 0 and (event.xdata - x_nums[i - 1]) < (x_nums[i] - event.xdata):
            i -= 1

        date = close.index[i]
        price = close.iloc[i]
        dma = dma200.iloc[i]
        dma_txt = f'{dma:,.2f}' if pd.notna(dma) else 'n/a'

        vline.set_xdata([date, date])
        vline.set_visible(True)
        marker.set_data([date], [price])
        marker.set_visible(True)
        annot.xy = (date, price)
        annot.set_text(f"{date:%d %b %Y}\nPrice: {price:,.2f}\n200 DMA: {dma_txt}")
        # Flip the tooltip to the left half so it never spills off the right edge.
        if i > len(x_nums) * 0.6:
            annot.set_position((-12, 12))
            annot.set_ha('right')
        else:
            annot.set_position((12, 12))
            annot.set_ha('left')
        annot.set_visible(True)
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect('motion_notify_event', on_move)


if __name__ == '__main__':
    main()
