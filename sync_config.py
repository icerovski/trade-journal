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
