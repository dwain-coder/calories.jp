import sqlite3
import pandas as pd

db_path = r'data/metadata/dataset_manager.db'
conn = sqlite3.connect(db_path)

wiki = pd.read_sql_query("SELECT name, category FROM items WHERE source = 'Wikipedia (JA)' ORDER BY RANDOM() LIMIT 5", conn)
counts = pd.read_sql_query("SELECT count(*) FROM items WHERE source = 'Wikipedia (JA)'", conn)
total = counts.iloc[0, 0]
conn.close()

md_append = f"""
## 🌐 Wikipedia (Japanese Food Dictionary)
We recursively crawled `Category:日本の食文化` (Japanese Food Culture) to extract **{total}** native Japanese foods, dishes, and ingredients.
| Article Title | Category |
|---------------|----------|
"""
for _, row in wiki.iterrows():
    md_append += f"| {row['name']} | {row['category']} |\n"

with open(r'C:\Users\dwain\.gemini\antigravity-ide\brain\75fe1372-c652-4b07-80a9-a9eff320b713\walkthrough.md', 'a', encoding='utf-8') as f:
    f.write(md_append)
