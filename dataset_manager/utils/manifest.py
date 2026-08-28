import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

def create_manifest(dataset_config: Dict[str, Any], file_metadata: Dict[str, Any], save_dir: Path):
    """
    Generates a manifest.json file for the dataset to make it self-describing.
    """
    manifest = {
        "dataset_name": dataset_config.get("name"),
        "version": dataset_config.get("version", "1.0"),
        "source_url": dataset_config.get("dataset_id"),
        "original_filename": file_metadata.get("filename"),
        "download_date": datetime.now().isoformat(),
        "sha256": file_metadata.get("sha256"),
        "md5": file_metadata.get("md5"),
        "file_size": file_metadata.get("size"),
        "license": dataset_config.get("license"),
        "extraction_status": file_metadata.get("extraction_status", "pending"),
        "number_of_extracted_files": file_metadata.get("extracted_files_count", 0),
        "sqlite_record_id": file_metadata.get("sqlite_id")
    }
    
    save_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = save_dir / "manifest.json"
    
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, ensure_ascii=False)
    
    return manifest_path
