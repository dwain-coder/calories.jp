import sqlite3
import pandas as pd
from pathlib import Path
import random

db_path = r'data/metadata/dataset_manager.db'
conn = sqlite3.connect(db_path)

# Get overall counts
counts = pd.read_sql_query("SELECT source, count(*) as count FROM items GROUP BY source ORDER BY count DESC", conn)
total_items = counts['count'].sum()

md = f"""# 📚 Dataset Manager Catalog

Welcome to the central repository of all food data processed by the pipeline. We have successfully ingested, translated, and normalized data from global authoritative sources into a unified SQLite database.

## 📊 High-Level Metrics
- **Total Food Items**: {total_items:,}
- **Total Datasets**: {len(counts)}
- **Database Location**: `dataset-manager/data/metadata/dataset_manager.db`

---

## 🍱 MEXT Standard Tables (2023)
**Source**: Japanese Ministry of Education, Culture, Sports, Science and Technology (MEXT)  
**Description**: The official nutritional composition tables for Japan. Contains high-accuracy macronutrient profiles for thousands of native Japanese foods.  
**Total Items**: {counts[counts['source'] == 'MEXT Standard Tables']['count'].values[0]:,}

| Item Name | Energy (kcal) | Protein (g) | Fat (g) | Carbs (g) |
|-----------|---------------|-------------|---------|-----------|
"""

mext = pd.read_sql_query("SELECT i.name, n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g FROM items i JOIN nutrition n ON i.id = n.item_id WHERE i.source = 'MEXT Standard Tables' ORDER BY RANDOM() LIMIT 5", conn)
for _, row in mext.iterrows():
    md += f"| {row['name']} | {row['energy_kcal']} | {row['protein_g']} | {row['fat_g']} | {row['carbohydrate_g']} |\n"

md += f"""
---

## 🌐 Wikipedia (Japanese Food Culture)
**Source**: ja.wikipedia.org (MediaWiki API)  
**Description**: A massive, recursively crawled dictionary of native Japanese foods, dishes, and ingredients. Used to enhance named entity recognition for Legal Compliance checks.  
**Total Items**: {counts[counts['source'] == 'Wikipedia (JA)']['count'].values[0]:,}

| Article Title | Category |
|---------------|----------|
"""

wiki = pd.read_sql_query("SELECT name, category FROM items WHERE source = 'Wikipedia (JA)' ORDER BY RANDOM() LIMIT 5", conn)
for _, row in wiki.iterrows():
    md += f"| {row['name']} | {row['category']} |\n"

md += f"""
---

## 🇺🇸 USDA FoodData Central (Foundation Foods)
**Source**: US Department of Agriculture  
**Description**: Foundational foods rigorously tested by the USDA. We extracted the core JSON dump and used the LLM Batch-Translation engine to localize all English items to native Japanese!  
**Total Items**: {counts[counts['source'] == 'USDA FoodData Central']['count'].values[0]:,}

| Japanese Name (Localized) | Category |
|---------------------------|----------|
"""

fdc = pd.read_sql_query("SELECT name, category FROM items WHERE source = 'USDA FoodData Central' ORDER BY RANDOM() LIMIT 5", conn)
for _, row in fdc.iterrows():
    md += f"| {row['name']} | {row['category']} |\n"

md += f"""
---

## ❄️ USDA FoodKeeper (Shelf-Life Rules)
**Source**: USDA FSIS  
**Description**: Official recommendations for food storage and shelf-life limits across pantry, refrigerator, and freezer. Used as the baseline for our expiration date logic.  
**Total Items**: {counts[counts['source'] == 'USDA FoodKeeper']['count'].values[0]:,}

| Item Name (Localized) | Storage Method | Min Days | Max Days | Storage Tips |
|-----------------------|----------------|----------|----------|--------------|
"""

fk = pd.read_sql_query("SELECT i.name, s.storage_method, s.min_days, s.max_days, s.tips FROM items i JOIN shelf_life s ON i.id = s.item_id WHERE i.source = 'USDA FoodKeeper' ORDER BY RANDOM() LIMIT 5", conn)
for _, row in fk.iterrows():
    tips = str(row['tips']).replace(chr(10), ' ').replace('|', ',').strip()
    md += f"| {row['name']} | {row['storage_method'].title()} | {row['min_days']} | {row['max_days']} | {tips} |\n"

md += f"""
---

## 🍜 OpenFoodFacts (Japan Filtered)
**Source**: OpenFoodFacts Global CSV Dump  
**Description**: Stream-processed 500MB+ CSV dump, aggressively filtered to only include products with the `en:japan` tag. Contains raw ingredients texts and allergen metadata.  
**Total Items**: {counts[counts['source'] == 'OpenFoodFacts']['count'].values[0]:,}

| Item Name | Ingredients Text | Allergens |
|-----------|------------------|-----------|
"""

off = pd.read_sql_query("SELECT i.name, ing.ingredients_text, ing.allergens FROM items i JOIN item_ingredients ing ON i.id = ing.item_id WHERE i.source = 'OpenFoodFacts' ORDER BY RANDOM() LIMIT 5", conn)
for _, row in off.iterrows():
    ing_text = str(row['ingredients_text']).replace(chr(10), ' ').replace('|', ',')[:100] + ('...' if len(str(row['ingredients_text'])) > 100 else '')
    allergens = str(row['allergens']).replace('|', ',')
    md += f"| {row['name']} | {ing_text} | {allergens} |\n"


md += f"""
---

## 🏛️ Wikidata (Semantic Graph)
**Source**: query.wikidata.org (SPARQL)  
**Description**: 100% legal (CC0 Public Domain) semantic graph query for items classified as 'food' with a 'country of origin' tag of Japan. Ensures completely safe ingestion of verifiable, factual food items.  
**Total Items**: {counts[counts['source'] == 'Wikidata (SPARQL)']['count'].values[0]:,}

| Item Label | Category |
|------------|----------|
"""

wd = pd.read_sql_query("SELECT name, category FROM items WHERE source = 'Wikidata (SPARQL)' ORDER BY RANDOM() LIMIT 5", conn)
for _, row in wd.iterrows():
    md += f"| {row['name']} | {row['category']} |\n"


conn.close()

with open(r'C:\Users\dwain\.gemini\antigravity-ide\brain\75fe1372-c652-4b07-80a9-a9eff320b713\data_catalog.md', 'w', encoding='utf-8') as f:
    f.write(md)
print('Data Catalog generated!')
