import requests
import time
from pathlib import Path
from typing import Dict, Any
from .base import BaseDownloader

class StreamDownloader(BaseDownloader):
    def download(self, dataset_config: Dict[str, Any], output_dir: Path) -> bool:
        url = dataset_config.get('url')
        if not url:
            return False
            
        if not self.check_robots_txt(url):
            print(f"Error: robots.txt strictly forbids scraping {url}.")
            return False
            
        filename = dataset_config.get('filename', 'downloaded_file')
        output_path = output_dir / filename
        
        max_items = dataset_config.get('max_items', None)
        
        print(f"Streaming {url} to {output_path} (max items: {max_items})")
        
        filter_column = dataset_config.get('filter_column')
        filter_keyword = dataset_config.get('filter_keyword')
        
        try:
            with requests.get(url, stream=True, headers={'User-Agent': 'Mozilla/5.0'}) as r:
                r.raise_for_status()
                lines_written = 0
                header = None
                filter_index = -1
                
                with open(output_path, 'wb') as f:
                    for line_bytes in r.iter_lines():
                        if not line_bytes:
                            continue
                            
                        if filter_column and filter_keyword:
                            try:
                                line_str = line_bytes.decode('utf-8', errors='ignore')
                            except Exception:
                                continue
                                
                            if header is None:
                                header = line_str
                                f.write(line_bytes + b'\n')
                                columns = header.split('\t')
                                if filter_column in columns:
                                    filter_index = columns.index(filter_column)
                                continue
                                
                            if filter_index != -1:
                                columns = line_str.split('\t')
                                if len(columns) > filter_index:
                                    if filter_keyword not in columns[filter_index]:
                                        continue
                                        
                        f.write(line_bytes + b'\n')
                        lines_written += 1
                        
                        if max_items and lines_written >= max_items:
                            print(f"Reached max items limit ({max_items}). Stopping stream.")
                            break
                            
            print(f"Successfully streamed {lines_written} lines to {output_path}")
            return True
            
        except Exception as e:
            print(f"Error streaming {url}: {e}")
            return False

    def get_estimated_size(self, dataset_config: Dict[str, Any]) -> int:
        return dataset_config.get('estimated_size_mb', 0) * 1024 * 1024
