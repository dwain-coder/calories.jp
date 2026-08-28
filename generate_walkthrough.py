import sqlite3
import pandas as pd
from pathlib import Path

db_path = 'data/metadata/dataset_manager.db'
conn = sqlite3.connect(db_path)

counts = pd.read_sql_query("SELECT source, count(*) as count FROM items GROUP BY source ORDER BY count DESC", conn)
fdc = pd.read_sql_query("SELECT name, category FROM items WHERE source = 'USDA FoodData Central' LIMIT 5", conn)
fk = pd.read_sql_query("SELECT i.name, s.storage_method, s.min_days, s.max_days, s.tips FROM items i JOIN shelf_life s ON i.id = s.item_id WHERE i.source = 'USDA FoodKeeper' LIMIT 3", conn)
mext = pd.read_sql_query("SELECT i.name, n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g FROM items i JOIN nutrition n ON i.id = n.item_id WHERE i.source = 'MEXT Standard Tables' LIMIT 3", conn)
off = pd.read_sql_query("SELECT i.name, ing.ingredients_text, ing.allergens FROM items i JOIN item_ingredients ing ON i.id = ing.item_id WHERE i.source = 'OpenFoodFacts' LIMIT 3", conn)

conn.close()

md = f"""# Final Database Overview

Here is a summary of all the data we successfully scraped, filtered, translated, and ingested into the SQLite database. Everything is fully normalized and cleanly stored!

## 📊 Total Items by Dataset
| Source | Total Food Items |
|--------|------------------|
"""
for _, row in counts.iterrows():
    md += f"| {row['source']} | {row['count']} |\n"

md += """
## 🇯🇵 Localized USDA Data (FoodData Central)
These items were originally in English, but our batch-translation engine converted them to Japanese before inserting them into the database:
| Japanese Name | Category |
|---------------|----------|
"""
for _, row in fdc.iterrows():
    md += f"| {row['name']} | {row['category']} |\n"

md += """
## ❄️ USDA FoodKeeper (Shelf-Life Rules)
We extracted the `Product` sheet from the downloaded Excel file and applied translations!
| Item Name | Storage Method | Min Days | Max Days | Tips |
|-----------|----------------|----------|----------|------|
"""
for _, row in fk.iterrows():
    md += f"| {row['name']} | {row['storage_method']} | {row['min_days']} | {row['max_days']} | {str(row['tips']).replace(chr(10), ' ').strip()} |\n"

md += """
## 🍱 MEXT 2023 Standard Tables (Nutrition)
Native Japanese food items with full macronutrient extraction.
| Item Name | Energy (kcal) | Protein (g) | Fat (g) | Carbs (g) |
|-----------|---------------|-------------|---------|-----------|
"""
for _, row in mext.iterrows():
    md += f"| {row['name']} | {row['energy_kcal']} | {row['protein_g']} | {row['fat_g']} | {row['carbohydrate_g']} |\n"

md += """
## 🍜 OpenFoodFacts (Ingredients & Compliance)
Stream-filtered to only ingest products with the `en:japan` tag. Contains full ingredients text for the Legal Compliance engine to check!
| Item Name | Ingredients Text | Allergens |
|-----------|------------------|-----------|
"""
for _, row in off.iterrows():
    md += f"| {row['name']} | {str(row['ingredients_text']).replace(chr(10), ' ')} | {str(row['allergens'])} |\n"

with open(r'C:\Users\dwain\.gemini\antigravity-ide\brain\75fe1372-c652-4b07-80a9-a9eff320b713\walkthrough.md', 'w', encoding='utf-8') as f:
    f.write(md)
print('Done!')
