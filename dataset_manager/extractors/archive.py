import os
import tarfile
import zipfile
import py7zr
import gzip
import shutil
from pathlib import Path

def extract_archive(archive_path: Path, extract_dir: Path) -> bool:
    """
    Detects the archive type and extracts it to the destination directory.
    Will not overwrite existing files if possible.
    """
    extract_dir.mkdir(parents=True, exist_ok=True)
    archive_name = archive_path.name.lower()
    
    try:
        if archive_name.endswith('.tar.gz') or archive_name.endswith('.tgz'):
            with tarfile.open(archive_path, 'r:gz') as tar:
                tar.extractall(path=extract_dir)
        elif archive_name.endswith('.tar'):
            with tarfile.open(archive_path, 'r:') as tar:
                tar.extractall(path=extract_dir)
        elif archive_name.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        elif archive_name.endswith('.7z'):
            with py7zr.SevenZipFile(archive_path, mode='r') as z:
                z.extractall(path=extract_dir)
        elif archive_name.endswith('.gz') and not archive_name.endswith('.tar.gz'):
            # It's just a gzipped file, e.g. jsonl.gz
            out_file = extract_dir / archive_path.with_suffix('').name
            if not out_file.exists():
                with gzip.open(archive_path, 'rb') as f_in:
                    with open(out_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
        else:
            print(f"Unsupported archive format: {archive_name}")
            return False
            
        return True
    except Exception as e:
        print(f"Extraction failed for {archive_path}: {e}")
        return False
