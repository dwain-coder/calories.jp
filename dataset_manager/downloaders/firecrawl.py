import os
from pathlib import Path
from typing import Dict, Any, Callable
from urllib.parse import urlparse
from firecrawl import FirecrawlApp

from .base import BaseDownloader

class FirecrawlDownloader(BaseDownloader):
    def __init__(self):
        # Point to the local Docker instance
        self.app = FirecrawlApp(api_url="http://localhost:3002")

    def get_estimated_size(self, dataset_config: Dict[str, Any]) -> int:
        if 'estimated_size_mb' in dataset_config:
            return dataset_config['estimated_size_mb'] * 1024 * 1024
        return 1 * 1024 * 1024  # default to 1MB for scraped markdown

    def download(self, dataset_config: Dict[str, Any], download_dir: Path, progress_callback: Callable[[int, int, float], None] = None) -> bool:
        url = dataset_config.get("url")
        if not url:
            print("Error: 'url' is required for Firecrawl downloader.")
            return False
            
        filename = dataset_config.get("filename")
        if not filename:
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path)
            if not filename:
                filename = "scraped_data"
                
        # Change extension to .md since firecrawl extracts markdown
        filename = f"{os.path.splitext(filename)[0]}.md"
        output_path = download_dir / filename
        
        print(f"Starting Firecrawl scrape of {url} to {output_path}...")
        
        mode = dataset_config.get("firecrawl_mode", "scrape")
        try:
            import httpx
            import time
            
            if mode == "crawl":
                print(f"Starting Firecrawl CRAWL of {url} (limit: {dataset_config.get('crawl_limit', 10)})...")
                response = httpx.post(
                    "http://localhost:3002/v1/crawl",
                    json={"url": url, "limit": dataset_config.get("crawl_limit", 10), "scrapeOptions": {"formats": ["markdown"]}},
                    timeout=60.0
                )
                response.raise_for_status()
                result = response.json()
                if not result.get("success"):
                    raise Exception(f"Crawl API returned unsuccessful: {result}")
                
                job_id = result.get("id")
                
                # Poll for completion
                while True:
                    status_resp = httpx.get(f"http://localhost:3002/v1/crawl/{job_id}", timeout=60.0)
                    status_resp.raise_for_status()
                    status_data = status_resp.json()
                    status = status_data.get("status")
                    if status == "completed":
                        break
                    elif status in ["failed", "cancelled", "error"]:
                        raise Exception(f"Crawl failed with status: {status_data}")
                    print(f"Crawl status: {status}... waiting 5s")
                    time.sleep(5)
                
                # Combine markdown
                items = status_data.get("data", [])
                # some versions of firecrawl return items directly, some return data array
                if not isinstance(items, list) and "data" in status_data:
                    items = status_data["data"]
                    
                markdown_content = "\n\n---\n\n".join([item.get("markdown", "") for item in items if isinstance(item, dict) and item.get("markdown")])
                print(f"Crawl completed with {len(items)} pages.")
            else:
                # Scrape single URL
                response = httpx.post(
                    "http://localhost:3002/v1/scrape", 
                    json={"url": url, "formats": ["markdown"]},
                    timeout=60.0
                )
                response.raise_for_status()
                
                result = response.json()
                if not result.get("success"):
                    raise Exception(f"API returned unsuccessful: {result}")
                    
                markdown_content = result.get("data", {}).get("markdown", "")
            
            with open(output_path, "w", encoding="utf-8") as file:
                file.write(markdown_content)
                
            # Firecrawl doesn't give a stream of bytes during download, so we just trigger the callback at the end
            if progress_callback:
                size = len(markdown_content.encode('utf-8'))
                progress_callback(size, size, 0.0)
                
            print("Scrape complete.")
            return True
        except Exception as e:
            print(f"Error scraping {url} with Firecrawl: {e}")
            return False
