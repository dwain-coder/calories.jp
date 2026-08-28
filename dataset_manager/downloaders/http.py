import os
import httpx
from pathlib import Path
from typing import Dict, Any, Callable
from urllib.parse import urlparse

from .base import BaseDownloader

class HttpDownloader(BaseDownloader):
    def get_estimated_size(self, dataset_config: Dict[str, Any]) -> int:
        if 'estimated_size_mb' in dataset_config:
            return dataset_config['estimated_size_mb'] * 1024 * 1024
        
        url = dataset_config.get("url")
        if not url:
            return 0
            
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            with httpx.Client() as client:
                response = client.head(url, follow_redirects=True, headers=headers)
                size = response.headers.get("Content-Length")
                if size and size.isdigit():
                    return int(size)
        except Exception:
            pass
        return 0

    def download(self, dataset_config: Dict[str, Any], download_dir: Path, progress_callback: Callable[[int, int, float], None] = None) -> bool:
        url = dataset_config.get("url")
        if not url:
            print("Error: 'url' is required for HTTP downloader.")
            return False
            
        ignore_robots = dataset_config.get("ignore_robots_txt", False)
        if not ignore_robots and not self.check_robots_txt(url):
            print(f"Error: robots.txt strictly forbids scraping {url}.")
            return False
            
        # Try to get filename from config, else derive from url
        filename = dataset_config.get("filename")
        if not filename:
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path)
            if not filename:
                filename = "downloaded_file"
                
        output_path = download_dir / filename
        
        print(f"Starting download from {url} to {output_path}...")
        
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            with httpx.stream("GET", url, follow_redirects=True, headers=headers) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", 0))
                
                with open(output_path, "wb") as file:
                    downloaded = 0
                    for chunk in response.iter_bytes(chunk_size=8192):
                        file.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total, 0.0)
                            
            print("Download complete.")
            return True
        except Exception as e:
            print(f"Error downloading {url}: {e}")
            return False
