import re
import shutil
from pathlib import Path
import atexit
from config import CONFIG_VAULT

METADATA_VAULT = CONFIG_VAULT
REPO_DIR = Path.cwd()

# Mapping: (Local Source Path, Remote Destination Path)
FILES_TO_SYNC = [
    (REPO_DIR / '.env', METADATA_VAULT / '.env'),
]

# ---------------------------------------------------------------------------
# Data-hub duplicate detection
#
# The ledger is a live SQLite file inside a synced OneDrive folder. OneDrive
# cannot merge a binary file, so if the app runs on two machines with overlapping
# writes it does not fail — it silently writes a SECOND database beside the first
# ("trade_journal-LAPTOP-XYZ.db"). Nothing in the app would tell you which copy it
# opened, so a forked ledger looks exactly like a working one. That is the whole
# danger: not the lost file, the undetectable fork.
#
# Detection is keyed off the canonical filenames rather than OneDrive's naming
# conventions (which differ per client and version): anything in the hub that
# looks like another copy of a canonical file is reported. A `.db` duplicate is
# loud; a stray `.log` is a one-liner.
# ---------------------------------------------------------------------------
CANONICAL_HUB_FILES = ("trade_journal.db", "prices.db", "trade_journal.log")

# OneDrive/Dropbox conflict markers, vs. a deliberate hand-made backup.
_CONFLICT_MARKERS = re.compile(
    r"(-(?:LAPTOP|DESKTOP|PC|MACBOOK)-|conflicted copy|conflict|\(\d+\)$)",
    re.IGNORECASE,
)


def find_duplicate_hub_files(names) -> dict:
    """Classify data-hub filenames into extra copies of the canonical files.

    Pure — takes an iterable of bare filenames so it can be tested without a
    filesystem. Returns {'conflict': [...], 'other': [...]}: `conflict` carries a
    sync-conflict marker (a genuine fork), `other` is any remaining extra copy
    (typically a deliberate `.backup_` file). Canonical names are never reported.
    """
    conflict, other = [], []
    for name in names:
        if name in CANONICAL_HUB_FILES:
            continue
        for canonical in CANONICAL_HUB_FILES:
            stem = Path(canonical).stem
            # A duplicate shares the canonical stem and extension but not the name.
            if name.startswith(stem) and name.endswith(Path(canonical).suffix):
                (conflict if _CONFLICT_MARKERS.search(Path(name).stem) else other).append(name)
                break
    return {"conflict": sorted(conflict), "other": sorted(other)}


# ---------------------------------------------------------------------------
# Stale-DATA_PATH detection
#
# `config.DATA_DIR` calls mkdir(parents=True, exist_ok=True), so a DATA_PATH
# naming a folder that no longer exists does not fail — it RECREATES it, init_db
# fills it with empty tables, and the app runs normally against a book with no
# history and no risk layer. Renaming the OneDrive parent folder did exactly that
# in 2026-08: .env still named the old path and a full ghost hub was rebuilt under
# it, indistinguishable from a real one except by being impossibly sparse.
#
# Both checks below are warnings only. Which hub is right is a judgement call, the
# same as which forked ledger is authoritative, and this module does not guess.
# ---------------------------------------------------------------------------

def env_value(text: str, key: str = "DATA_PATH"):
    """Read one key out of .env text. Pure — no dotenv, no environment, no I/O.

    Deliberately not `dotenv_values`: this has to read the OTHER machine's copy
    without loading it into this process, and it must never raise on a malformed
    line. Last assignment wins, matching dotenv's own override behaviour.
    """
    value = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        if name.strip() == key:
            value = raw.strip().strip('"').strip("'").rstrip("\\/")
    return value or None


def _warn_on_data_path_divergence(local_path, remote_path):
    """Report two .env copies that disagree about where the data hub is.

    This is the two-machine failure mode: the laptop that missed a path change
    still names the old hub, and whichever copy happens to be newer wins the sync
    silently. Say it out loud before that decision is made by an mtime.
    """
    try:
        local = env_value(local_path.read_text(encoding="utf-8", errors="replace"))
        remote = env_value(remote_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if not local or not remote or local == remote:
        return None

    print(f"\n[!!] THE TWO .env COPIES NAME DIFFERENT DATA HUBS:")
    print(f"       local (this machine): {local}")
    print(f"       vault (OneDrive):     {remote}")
    print("     Only one of these is the real book. The newer file is about to win on")
    print("     mtime alone, and a path that no longer exists is silently RECREATED as")
    print("     an empty hub — it will not error. Fix .env before continuing.")
    return (local, remote)


def check_data_hub(data_dir=None) -> dict:
    """Scan the data hub for duplicate ledgers and report to the console.

    Called on startup, before init_db, so a hub about to be filled with empty
    tables can still be questioned. Read-only: it never deletes or moves anything
    — which copy is authoritative is a judgement call, and guessing at it is how
    you lose a ledger. Returns the same dict as find_duplicate_hub_files.
    """
    if data_dir is None:
        from config import DATA_DIR
        data_dir = DATA_DIR
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return {"conflict": [], "other": []}

    if not (data_dir / "trade_journal.db").exists():
        print("\n[!!] NO LEDGER IN THE CONFIGURED DATA HUB:")
        print(f"       {data_dir}")
        print("     An empty book is about to be created here. If this is not a genuine")
        print("     first run, DATA_PATH in .env names a hub that has moved or been")
        print("     renamed — the folder you are looking at was recreated, not found.")
        print("     Check DATA_PATH before ingesting anything.")

    found = find_duplicate_hub_files(p.name for p in data_dir.iterdir() if p.is_file())

    forked_db = [n for n in found["conflict"] if n.endswith(".db")]
    if forked_db:
        print("\n[!!] SYNC CONFLICT — the data hub holds more than one copy of the ledger:")
        for name in forked_db:
            print(f"       {name}")
        print("     Two machines wrote to it at once. Neither copy is authoritative and the")
        print("     app cannot tell you which one it is using. Compare them before trading on")
        print(f"     these numbers.  Hub: {data_dir}")

    stray_logs = [n for n in found["conflict"] if not n.endswith(".db")]
    if stray_logs:
        print(f"[i] {len(stray_logs)} conflict-copy log file(s) in the data hub — safe to delete.")

    return found

def backup():
    """Copies local files TO OneDrive."""
    print("\n[BACKUP] Backing up Metadata to OneDrive...")

    for local_path, remote_path in FILES_TO_SYNC:
        if local_path.exists():
            remote_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, remote_path)
            print(f"  -> Backed up {local_path.name}")

def smart_sync():
    """
    On startup: Ensures local files are the latest version compared to OneDrive.
    If OneDrive version is newer (or local is missing), it copies it locally.
    """
    print("\n[SYNC] Syncing Configuration with OneDrive...")

    for local_path, remote_path in FILES_TO_SYNC:
        if remote_path.exists():
            if not local_path.exists():
                print(f"  -> {local_path.name} missing. Restoring from OneDrive...")
                local_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(remote_path, local_path)
            else:
                if local_path.name == '.env':
                    _warn_on_data_path_divergence(local_path, remote_path)

                local_mtime = local_path.stat().st_mtime
                remote_mtime = remote_path.stat().st_mtime

                # If remote is significantly newer (> 2 seconds to avoid filesystem noise)
                if remote_mtime > local_mtime + 2:
                    print(f"  -> OneDrive has a newer {local_path.name}. Updating local copy...")
                    shutil.copy2(remote_path, local_path)
                elif local_mtime > remote_mtime + 2:
                    print(f"  -> Local {local_path.name} is newer. Will backup on exit.")
                else:
                    print(f"  -> {local_path.name} is in sync.")
        else:
            if local_path.exists():
                print(f"  -> Remote {remote_path.name} not found. Will backup on exit.")
            else:
                print(f"  [WARNING] Both local and remote {local_path.name} are missing.")

# Automatically register the backup function to run on exit
atexit.register(backup)

if __name__ == "__main__":
    smart_sync()
