from pathlib import Path
import csv
import sys
from .base import BaseTransformer

csv.field_size_limit(2147483647)

from typing import Dict, Any

class OpenFoodFactsTransformer(BaseTransformer):
    def transform(self, config: Dict[str, Any], input_dir: Path) -> bool:
        csv_file = input_dir / 'en.openfoodfacts.org.products.csv'
        if not csv_file.exists():
            print(f"Error: Could not find {csv_file}")
            return False
            
        print(f"Transforming OpenFoodFacts data from {csv_file}...")
        
        items_added = 0
        batch_size = 5000
        items_batch = []
        barcodes_batch = []
        nutrition_batch = []
        ingredients_batch = []
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            
            for row in reader:
                try:
                    barcode = row.get('code')
                    name = row.get('product_name')
                    
                    if not barcode or not name:
                        continue
                        
                    items_batch.append((
                        name,
                        "branded",
                        "OpenFoodFacts",
                        f"off_{barcode}"
                    ))
                    
                    barcodes_batch.append((
                        f"off_{barcode}", # temporary item_id reference
                        barcode
                    ))
                    nutrition_batch.append({
                        'ref': f"off_{barcode}",
                        'energy_kcal': row.get('energy-kcal_100g') or None,
                        'protein_g': row.get('proteins_100g') or None,
                        'fat_g': row.get('fat_100g') or None,
                        'carbs_g': row.get('carbohydrates_100g') or None
                    })
                    
                    ing_text = row.get('ingredients_text')
                    if ing_text:
                        ingredients_batch.append({
                            'ref': f"off_{barcode}",
                            'text': ing_text
                        })
                    
                    items_added += 1
                    
                    if len(items_batch) >= batch_size:
                        cursor = self.conn.cursor()
                        # Insert items
                        cursor.executemany(
                            "INSERT OR IGNORE INTO items (name, category, source, source_url) VALUES (?, ?, ?, ?)",
                            items_batch
                        )
                        
                        # Get generated IDs
                        refs = [b[0] for b in barcodes_batch]
                        placeholders = ','.join(['?'] * len(refs))
                        cursor.execute(f"SELECT id, source_url FROM items WHERE source_url IN ({placeholders})", refs)
                        ref_to_id = {row[1]: row[0] for row in cursor.fetchall()}
                        
                        # Prepare mapped batches
                        nut_to_insert = []
                        for n in nutrition_batch:
                            if n['ref'] in ref_to_id:
                                nut_to_insert.append((
                                    ref_to_id[n['ref']], n['energy_kcal'], n['protein_g'], n['fat_g'], n['carbs_g']
                                ))
                                
                        ing_to_insert = []
                        for i in ingredients_batch:
                            if i['ref'] in ref_to_id:
                                ing_to_insert.append((
                                    ref_to_id[i['ref']], i['text']
                                ))
                                
                        bc_to_insert = []
                        for b in barcodes_batch:
                            if b[0] in ref_to_id:
                                bc_to_insert.append((ref_to_id[b[0]], b[1]))
                                
                        cursor.executemany("INSERT OR IGNORE INTO nutrition (item_id, energy_kcal, protein_g, fat_g, carbohydrate_g) VALUES (?, ?, ?, ?, ?)", nut_to_insert)
                        cursor.executemany("INSERT OR IGNORE INTO ingredients (item_id, ingredients_text) VALUES (?, ?)", ing_to_insert)
                        cursor.executemany("INSERT OR IGNORE INTO barcodes (item_id, upc) VALUES (?, ?)", bc_to_insert)
                        
                        self.conn.commit()
                        print(f"Processed {items_added} OpenFoodFacts items (with full macro data)...")
                        items_batch = []
                        barcodes_batch = []
                        nutrition_batch = []
                        ingredients_batch = []
                        
                except Exception as e:
                    print(f"Error on row: {e}")
                    continue
                    
            if items_batch:
                cursor = self.conn.cursor()
                cursor.executemany(
                    "INSERT OR IGNORE INTO items (name, category, source, source_url) VALUES (?, ?, ?, ?)",
                    items_batch
                )
                
                refs = [b[0] for b in barcodes_batch]
                placeholders = ','.join(['?'] * len(refs))
                cursor.execute(f"SELECT id, source_url FROM items WHERE source_url IN ({placeholders})", refs)
                ref_to_id = {row[1]: row[0] for row in cursor.fetchall()}
                
                nut_to_insert = []
                for n in nutrition_batch:
                    if n['ref'] in ref_to_id:
                        nut_to_insert.append((
                            ref_to_id[n['ref']], n['energy_kcal'], n['protein_g'], n['fat_g'], n['carbs_g']
                        ))
                        
                ing_to_insert = []
                for i in ingredients_batch:
                    if i['ref'] in ref_to_id:
                        ing_to_insert.append((
                            ref_to_id[i['ref']], i['text']
                        ))
                        
                bc_to_insert = []
                for b in barcodes_batch:
                    if b[0] in ref_to_id:
                        bc_to_insert.append((ref_to_id[b[0]], b[1]))
                        
                cursor.executemany("INSERT OR IGNORE INTO nutrition (item_id, energy_kcal, protein_g, fat_g, carbohydrate_g) VALUES (?, ?, ?, ?, ?)", nut_to_insert)
                cursor.executemany("INSERT OR IGNORE INTO ingredients (item_id, ingredients_text) VALUES (?, ?)", ing_to_insert)
                cursor.executemany("INSERT OR IGNORE INTO barcodes (item_id, upc) VALUES (?, ?)", bc_to_insert)
                
                self.conn.commit()
                
        print(f"Added {items_added} items from OpenFoodFacts.")
        return True
        
    def _parse_float(self, val):
        if not val:
            return None
        try:
            return float(val)
        except ValueError:
            return None
