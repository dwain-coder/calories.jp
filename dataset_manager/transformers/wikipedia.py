import json
import urllib.request
import urllib.parse
import time
from pathlib import Path
from typing import Dict, Any, Set
from .base import BaseTransformer

class WikipediaTransformer(BaseTransformer):
    def transform(self, dataset_config: Dict[str, Any], raw_path: Path):
        print(f"Transforming Wikipedia data for {dataset_config['name']}...")
        
        visited_categories = set()
        items = set()
        
        def fetch_category(category_name, depth=0):
            if depth > 1: # Only go 1 level deep to avoid unrelated pages
                return
            if category_name in visited_categories:
                return
            visited_categories.add(category_name)
            
            print(f"  Fetching {category_name} (depth {depth})...")
            url = f"https://ja.wikipedia.org/w/api.php?action=query&list=categorymembers&cmtitle={urllib.parse.quote(category_name)}&cmlimit=500&format=json"
            
            req = urllib.request.Request(url, headers={'User-Agent': 'FoodDatasetManager/1.0 (contact@fooddatasetmanager.org)'})
            backoff = 2
            for attempt in range(5):
                try:
                    with urllib.request.urlopen(req, timeout=10) as response:
                        data = json.loads(response.read().decode('utf-8'))
                        for member in data.get('query', {}).get('categorymembers', []):
                            title = member['title']
                            if title.startswith('Category:'):
                                fetch_category(title, depth + 1)
                            elif title.startswith('Template:') or title.startswith('Wikipedia:'):
                                continue
                            else:
                                items.add(title)
                        break
                except Exception as e:
                    if hasattr(e, 'code') and e.code == 429:
                        print(f"  Got 429 fetching {category_name}. Retrying in {backoff}s...")
                        time.sleep(backoff)
                        backoff *= 2
                    else:
                        print(f"  Error fetching {category_name}: {e}")
                        break
            time.sleep(1.5)
            
        # Start scraping from the root categories
        root_categories = [
            "Category:日本の食文化",
            "Category:和菓子",
            "Category:日本の調味料",
            "Category:日本の麺料理",
            "Category:日本の魚介料理"
        ]
        
        for root in root_categories:
            fetch_category(root, 0)
        
        # Skip list pages (一覧) and batch fetch extracts
        filtered_items = [item for item in items if "一覧" not in item]
        print(f"  Fetching summaries for {len(filtered_items)} Wikipedia articles in batches of 20...")
        
        items_added = 0
        batch_size = 20
        for i in range(0, len(filtered_items), batch_size):
            batch = filtered_items[i:i + batch_size]
            titles_str = "|".join(batch)
            url = f"https://ja.wikipedia.org/w/api.php?action=query&prop=extracts&exintro&explaintext&exlimit=20&titles={urllib.parse.quote(titles_str)}&format=json"
            
            req = urllib.request.Request(url, headers={'User-Agent': 'FoodDatasetManager/1.0 (contact@fooddatasetmanager.org)'})
            backoff = 2
            for attempt in range(5):
                try:
                    with urllib.request.urlopen(req, timeout=10) as response:
                        res_data = json.loads(response.read().decode('utf-8'))
                        pages = res_data.get('query', {}).get('pages', {})
                        for page_id, page_data in pages.items():
                            title = page_data.get('title')
                            extract = page_data.get('extract')
                            
                            if title:
                                item_id = self._insert_item(
                                    name=title,
                                    category="Wikipedia Food",
                                    source=dataset_config['source'],
                                    source_url=f"https://ja.wikipedia.org/wiki/{urllib.parse.quote(title)}"
                                )
                                if item_id and extract:
                                    self._insert_ingredients(item_id, extract.strip())
                                items_added += 1
                        break
                except Exception as e:
                    if hasattr(e, 'code') and e.code == 429:
                        print(f"  Got 429 fetching batch. Retrying in {backoff}s...")
                        time.sleep(backoff)
                        backoff *= 2
                    else:
                        print(f"  Error fetching batch of extracts: {e}")
                        break
            
            time.sleep(2) # Be nice to API limits
            
        print(f"Added {items_added} items from Wikipedia (JA).")
