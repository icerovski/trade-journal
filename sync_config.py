import shutil
from pathlib import Path
import os
import atexit
from config import CONFIG_VAULT

# 1. Define Vault Paths
# Metadata Vault (Secrets and project-specific instructions)
METADATA_VAULT = CONFIG_VAULT

# Global Context Vault (parent of Metadata Vault)
GLOBAL_VAULT = CONFIG_VAULT.parent

# Local paths
REPO_DIR = Path.cwd()
LOCAL_GEMINI_DIR = Path(os.path.expanduser('~')) / '.gemini'

# Mapping: (Local Source Path, Remote Destination Path)
FILES_TO_SYNC = [
    (REPO_DIR / 'GEMINI.md', METADATA_VAULT / 'GEMINI.md'),
    (REPO_DIR / '.env', METADATA_VAULT / '.env'),
    (LOCAL_GEMINI_DIR / 'GEMINI.md', GLOBAL_VAULT / 'global_GEMINI.md'),
]

def backup():
    """Copies local files TO OneDrive."""
    print("\n🚀 Starting Metadata Backup to OneDrive...")
    
    for local_path, remote_path in FILES_TO_SYNC:
        if local_path.exists():
            # Ensure the destination directory exists
            remote_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(local_path, remote_path)
            print(f"  -> Backed up {local_path.name} to {remote_path}")
        else:
            # Avoid warning for global GEMINI if not present on this machine
            if "global" not in remote_path.name:
                print(f"  ⚠️ Warning: Local file {local_path} not found. Skipping.")

def restore():
    """Copies OneDrive files BACK TO local locations."""
    print("📥 Restoring Metadata from OneDrive...")
    
    for local_path, remote_path in FILES_TO_SYNC:
        if remote_path.exists():
            # Ensure local parent directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(remote_path, local_path)
            print(f"  -> Restored {local_path.name} from {remote_path}")
        else:
            print(f"  ⚠️ Warning: Remote file {remote_path} not found. Skipping.")

# Automatically register the backup function to run on exit
atexit.register(backup)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'restore':
        restore()
    else:
        backup()
