import shutil
from pathlib import Path
import os

# Paths
ONEDRIVE_VAULT = Path(r'C:\Users\User\OneDrive\Documents\Logos\.repos')
REPO_DIR = Path.cwd()
GLOBAL_GEMINI_DIR = Path(os.path.expanduser('~')) / '.gemini'

# Mapping: (Local Source Path, Remote Filename in Vault)
FILES_TO_SYNC = [
    (REPO_DIR / '.env', 'trade-journal.env'),
    (REPO_DIR / 'GEMINI.md', 'trade-journal_GEMINI.md'),
    (GLOBAL_GEMINI_DIR / 'GEMINI.md', 'global_GEMINI.md'),
]

def backup():
    """Copies local files TO OneDrive."""
    if not ONEDRIVE_VAULT.exists():
        print(f"Error: OneDrive vault not found at {ONEDRIVE_VAULT}")
        return

    for local_path, remote_name in FILES_TO_SYNC:
        if local_path.exists():
            dst = ONEDRIVE_VAULT / remote_name
            shutil.copy2(local_path, dst)
            print(f"-> Backed up {local_path.name} to {remote_name}")
        else:
            print(f"Warning: Local file {local_path} not found. Skipping.")

def restore():
    """Copies OneDrive files BACK TO local locations."""
    if not ONEDRIVE_VAULT.exists():
        print(f"Error: OneDrive vault not found at {ONEDRIVE_VAULT}")
        return

    for local_path, remote_name in FILES_TO_SYNC:
        src = ONEDRIVE_VAULT / remote_name
        if src.exists():
            # Ensure parent directory exists (especially for .gemini)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, local_path)
            print(f"-> Restored {local_path.name} from {remote_name}")
        else:
            print(f"Warning: Remote file {remote_name} not found in vault. Skipping.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'restore':
        restore()
    else:
        backup()
