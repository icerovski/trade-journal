import sys
import subprocess
from pathlib import Path

_REPO_DIR = Path(__file__).parent
_WORKER = str(_REPO_DIR / 'chart_worker.py')
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0


def launch_price_chart(display_ticker: str, conid: str = None, yf_ticker: str = None) -> None:
    """Spawn chart_worker.py as an isolated subprocess — avoids all Tk threading issues."""
    subprocess.Popen(
        [sys.executable, _WORKER, display_ticker, conid or '', yf_ticker or display_ticker],
        cwd=str(_REPO_DIR),
        creationflags=_NO_WINDOW,
    )
