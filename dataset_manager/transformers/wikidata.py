import urllib.request
import urllib.parse
import json
import time
from pathlib import Path
from typing import Dict, Any, Set
from .base import BaseTransformer

class WikidataTransformer(BaseTransformer):
    def transform(self, dataset_config: Dict[str, Any], raw_path: Path):
        print(f"Transforming Wikidata for {dataset_config['name']}...")
        
        # SPARQL Query for instances of food (Q2095) with country of origin Japan (Q17)
        # We also look for subclasses of food.
        query = """
        SELECT DISTINCT ?food ?foodLabel ?foodDescription WHERE {
          ?food wdt:P31/wdt:P279* wd:Q2095. 
          ?food wdt:P495 wd:Q17. 
          SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
        }
        """
        
        print("  Executing SPARQL query...")
        url = 'https://query.wikidata.org/sparql?query=' + urllib.parse.quote(query) + '&format=json'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'DatasetManagerBot/1.0 (https://github.com/example/dataset-manager)',
            'Accept': 'application/sparql-results+json'
        })
        
        items_added = 0
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))
                bindings = data.get('results', {}).get('bindings', [])
                
                print(f"  Found {len(bindings)} food items in Wikidata.")
                for result in bindings:
                    label = result.get('foodLabel', {}).get('value')
                    desc = result.get('foodDescription', {}).get('value')
                    uri = result.get('food', {}).get('value', '')
                    
                    if not label or label.startswith('http') or label.startswith('Q'):
                        continue # Skip items that have no Japanese/English label
                    
                    item_id = self._insert_item(
                        name=label,
                        category="Wikidata Food",
                        source=dataset_config['source'],
                        source_url=uri
                    )
                    if item_id and desc and desc != "food":
                        self._insert_ingredients(item_id, desc)
                    items_added += 1
        except Exception as e:
            print(f"  Error fetching Wikidata: {e}")
            
        print(f"Added {items_added} items from Wikidata.")
        return True
