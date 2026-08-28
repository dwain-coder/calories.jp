import shutil
from pathlib import Path

def get_free_space(path: Path = Path(".")) -> int:
    """
    Returns the free disk space in bytes for the drive containing `path`.
    """
    usage = shutil.disk_usage(path.resolve())
    return usage.free

def format_bytes(size: int) -> str:
    """
    Format bytes to human readable string.
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def check_space_available(required_bytes: int, path: Path = Path(".")) -> bool:
    """
    Checks if there is enough free space for `required_bytes`, keeping a small buffer (e.g., 1GB).
    """
    BUFFER = 1024 * 1024 * 1024 # 1GB buffer
    free = get_free_space(path)
    return free > (required_bytes + BUFFER)
