from abc import ABC, abstractmethod
from typing import Dict, Any
from pathlib import Path
import sqlite3

class BaseTransformer(ABC):
    def __init__(self, db_conn: sqlite3.Connection):
        self.conn = db_conn

    @abstractmethod
    def transform(self, dataset_config: Dict[str, Any], raw_path: Path):
        """
        Reads the raw_path file, parses its contents, and inserts
        normalized records into the items, shelf_life, and/or nutrition tables.
        """
        pass
        
    def _insert_item(self, name: str, category: str, source: str, source_url: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO items (name, category, source, source_url) VALUES (?, ?, ?, ?)",
            (name, category, source, source_url)
        )
        self.conn.commit()
        return cursor.lastrowid
        
    def _insert_shelf_life(self, item_id: int, storage_method: str, min_days: int, max_days: int, tips: str):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO shelf_life (item_id, storage_method, min_days, max_days, tips) VALUES (?, ?, ?, ?, ?)",
            (item_id, storage_method, min_days, max_days, tips)
        )
        self.conn.commit()
        
    def _insert_nutrition(self, item_id: int, energy_kcal: float, protein_g: float, fat_g: float, carbs_g: float):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO nutrition (item_id, energy_kcal, protein_g, fat_g, carbohydrate_g) VALUES (?, ?, ?, ?, ?)",
            (item_id, energy_kcal, protein_g, fat_g, carbs_g)
        )
        self.conn.commit()

    def _insert_regional_dish(self, item_id: int, region: str, main_ingredients: str,
                              history: str, occasion: str, how_to_eat: str,
                              preservation: str, recipe_ingredients: str, recipe_steps: str):
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO regional_dishes
               (item_id, region, main_ingredients, history, occasion, how_to_eat,
                preservation, recipe_ingredients, recipe_steps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, region, main_ingredients, history, occasion, how_to_eat,
             preservation, recipe_ingredients, recipe_steps)
        )
        self.conn.commit()

    def _insert_ingredients(self, item_id: int, ingredients_text: str):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO ingredients (item_id, ingredients_text) VALUES (?, ?)",
            (item_id, ingredients_text)
        )
        self.conn.commit()
