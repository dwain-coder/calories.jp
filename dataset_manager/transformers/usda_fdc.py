import json
from pathlib import Path
from typing import Dict, Any
from .base import BaseTransformer

class USDAFDCTransformer(BaseTransformer):
    def transform(self, config: Dict[str, Any], input_path: Path) -> bool:
        # FDC zips contain one or more JSON files. We'll find the first large JSON.
        if input_path.is_dir():
            json_files = list(input_path.glob('**/*.json'))
        else:
            json_files = [input_path]
        if not json_files:
            print(f"Error: Could not find any JSON files in {input_path}")
            return False
            
        # Filter out manifest.json if present
        json_files = [f for f in json_files if f.name != 'manifest.json']
        if not json_files:
             print("No valid data JSON files found.")
             return False
             
        data_file = json_files[0]
        print(f"Transforming USDA FDC data from {data_file}...")
        
        items_added = 0
        
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # The structure is usually {"FoundationFoods": [...]} or a flat list [...]
            foods = data.get('FoundationFoods', []) if isinstance(data, dict) else data
            
            # Collect names and batch translate
            from ..utils.translate import batch_translate_to_japanese
            names_to_translate = []
            for food in foods:
                if isinstance(food, dict) and food.get('description'):
                    names_to_translate.append(food.get('description'))
                    
            translations = batch_translate_to_japanese(names_to_translate)
            
            for food in foods:
                if not isinstance(food, dict):
                    continue
                    
                fdc_id = food.get('fdcId')
                desc = food.get('description')
                
                if not fdc_id or not desc:
                    continue
                    
                jp_desc = translations.get(desc, desc)
                
                item_id = self._insert_item(
                    name=jp_desc,
                    category="foundation",
                    source="USDA FoodData Central",
                    source_url=f"fdc_{fdc_id}"
                )
                
                if not item_id:
                    continue
                    
                # Parse nutrients
                nutrients = food.get('foodNutrients', [])
                if not nutrients:
                    continue
                    
                energy = None
                protein = None
                fat = None
                carbs = None
                
                for n in nutrients:
                    if not isinstance(n, dict):
                        continue
                        
                    nutrient_info = n.get('nutrient', {})
                    if not isinstance(nutrient_info, dict):
                        continue
                        
                    n_id = nutrient_info.get('id')
                    # FDC Nutrient IDs: 1008=Energy(kcal), 1003=Protein, 1004=Fat, 1005=Carbs
                    if n_id == 1008:
                        energy = n.get('amount')
                    elif n_id == 1003:
                        protein = n.get('amount')
                    elif n_id == 1004:
                        fat = n.get('amount')
                    elif n_id == 1005:
                        carbs = n.get('amount')
                        
                if any(x is not None for x in [energy, protein, fat, carbs]):
                    self._insert_nutrition(item_id, energy, protein, fat, carbs)
                    
                items_added += 1
                
        except Exception as e:
            print(f"Error parsing FDC JSON: {e}")
            return False
            
        self.conn.commit()
        print(f"Added {items_added} items from USDA FDC.")
        return True
