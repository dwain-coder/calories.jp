import os
import time
from pathlib import Path
from typing import Dict, Any, Callable
from huggingface_hub import snapshot_download, HfApi
from huggingface_hub.utils import HfHubHTTPError
from dotenv import load_dotenv

from .base import BaseDownloader

class HuggingFaceDownloader(BaseDownloader):
    def __init__(self):
        load_dotenv()
        self.token = os.getenv("HF_TOKEN")
        self.api = HfApi(token=self.token)

    def get_estimated_size(self, dataset_config: Dict[str, Any]) -> int:
        """
        Returns the estimated download size from config or queries Hugging Face API if possible.
        """
        if 'estimated_size_mb' in dataset_config:
            return dataset_config['estimated_size_mb'] * 1024 * 1024
        
        # Fallback to querying dataset info if possible, but estimated_size is usually better
        # For simplicity, returning a default or 0 if not provided
        return 0

    def download(self, dataset_config: Dict[str, Any], download_dir: Path, progress_callback: Callable[[int, int, float], None] = None) -> bool:
        dataset_id = dataset_config.get("dataset_id")
        if not dataset_id:
            print("Error: dataset_id is required for HuggingFace downloader.")
            return False
        
        try:
            subfolder = dataset_config.get("subfolder")
            allow_patterns = f"{subfolder}/*" if subfolder else None
            
            print(f"Starting download of {dataset_id} (pattern: {allow_patterns}) to {download_dir}...")
            
            snapshot_download(
                repo_id=dataset_id,
                repo_type="dataset",
                local_dir=str(download_dir),
                token=self.token,
                allow_patterns=allow_patterns,
                max_workers=4
            )
            return True
        except Exception as e:
            print(f"Error downloading {dataset_id} from Hugging Face: {e}")
            return False
