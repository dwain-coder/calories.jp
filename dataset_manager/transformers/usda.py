import json
from pathlib import Path
from typing import Dict, Any
from .base import BaseTransformer

class USDAFoodKeeperTransformer(BaseTransformer):
    def transform(self, dataset_config: Dict[str, Any], raw_path: Path):
        print(f"Transforming USDA FoodKeeper data from {raw_path}...")
        import pandas as pd
        try:
            df = pd.read_excel(raw_path, sheet_name='Product')
        except Exception as e:
            print(f"Error reading FoodKeeper Excel: {e}")
            return
            
        data = df.to_dict(orient='records')
            
        # Collect names for batch translation
        from ..utils.translate import batch_translate_to_japanese
        names_to_translate = []
        for row in data:
            name = row.get('Name')
            if pd.notna(name) and str(name).strip():
                subtitle = row.get('Name_subtitle')
                full_name = f"{name} ({subtitle})" if pd.notna(subtitle) and str(subtitle).strip() else name
                names_to_translate.append(str(full_name))
                
        translations = batch_translate_to_japanese(names_to_translate)
            
        items_added = 0
        for row in data:
            item_dict = row
            
            name = item_dict.get('Name')
            if pd.isna(name) or not str(name).strip():
                continue
                
            subtitle = item_dict.get('Name_subtitle')
            full_name = f"{name} ({subtitle})" if pd.notna(subtitle) and str(subtitle).strip() else str(name)
            jp_name = translations.get(full_name, full_name)
            
            # Insert into items table
            item_id = self._insert_item(
                name=jp_name,
                category=str(item_dict.get('Category_ID', '')),
                source="USDA FoodKeeper",
                source_url=dataset_config.get("url", "")
            )
            
            # Add storage rules
            self._add_rule(item_id, item_dict, 'Pantry', 'Pantry_tips')
            self._add_rule(item_id, item_dict, 'Refrigerate', 'Refrigerate_tips')
            self._add_rule(item_id, item_dict, 'Freeze', 'Freeze_Tips')
            # They also have DOP (Date of Purchase) and After_Opening rules, but we'll stick to basics for now
            self._add_rule(item_id, item_dict, 'DOP_Pantry', 'DOP_Pantry_tips')
            self._add_rule(item_id, item_dict, 'DOP_Refrigerate', 'DOP_Refrigerate_tips')
            self._add_rule(item_id, item_dict, 'DOP_Freeze', 'DOP_Freeze_Tips')
            
            items_added += 1
            
        print(f"Added {items_added} items from FoodKeeper into the normalized schema.")
            
    def _add_rule(self, item_id, item_dict, prefix, tips_key):
        import pandas as pd
        min_val = item_dict.get(f"{prefix}_Min")
        max_val = item_dict.get(f"{prefix}_Max")
        metric = item_dict.get(f"{prefix}_Metric")
        tips = item_dict.get(tips_key)
        
        if pd.notna(max_val) and pd.notna(metric):
            multiplier = 1
            metric_lower = str(metric).lower()
            if 'year' in metric_lower: multiplier = 365
            elif 'month' in metric_lower: multiplier = 30
            elif 'week' in metric_lower: multiplier = 7
            
            min_days = int(float(min_val) * multiplier) if pd.notna(min_val) else None
            max_days = int(float(max_val) * multiplier) if pd.notna(max_val) else None
            
            tips = item_dict.get(tips_key)
            tips = str(tips) if pd.notna(tips) else None
            
            # Normalize prefix for DB
            storage_method = prefix.replace("DOP_", "").replace("_", " ")
            
            self._insert_shelf_life(item_id, storage_method, min_days, max_days, tips)
