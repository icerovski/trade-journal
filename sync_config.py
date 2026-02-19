import shutil
from pathlib import Path
import os

# 1. Define Vault Paths
# Metadata Vault (Secrets and project-specific instructions)
METADATA_VAULT = Path(r'C:\Users\User\OneDrive\Documents\Logos\.repos\trade-journal')

# Global Context Vault
GLOBAL_VAULT = Path(r'C:\Users\User\OneDrive\Documents\Logos\.repos')

# Local paths
REPO_DIR = Path.cwd()
LOCAL_GEMINI_DIR = Path(os.path.expanduser('~')) / '.gemini'

# Mapping: (Local Source Path, Remote Destination Path)
FILES_TO_SYNC = [
    (REPO_DIR / 'GEMINI.md', METADATA_VAULT / 'GEMINI.md'),
    (LOCAL_GEMINI_DIR / 'GEMINI.md', GLOBAL_VAULT / 'global_GEMINI.md'),
]

def backup():
    """Copies local files TO OneDrive."""
    print("🚀 Starting Metadata Backup...")
    
    for local_path, remote_path in FILES_TO_SYNC:
        if local_path.exists():
            # Ensure the destination directory exists
            remote_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(local_path, remote_path)
            print(f"  -> Backed up {local_path.name} to {remote_path}")
        else:
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

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'restore':
        restore()
    else:
        backup()
