import hashlib
from pathlib import Path
from typing import Tuple

def calculate_checksums(file_path: Path, chunk_size: int = 8192) -> Tuple[str, str, int]:
    """
    Calculates SHA256 and MD5 checksums, along with the file size.
    Returns (sha256, md5, size_in_bytes)
    """
    sha256_hash = hashlib.sha256()
    md5_hash = hashlib.md5()
    size = 0
    
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256_hash.update(chunk)
            md5_hash.update(chunk)
            size += len(chunk)
            
    return sha256_hash.hexdigest(), md5_hash.hexdigest(), size
