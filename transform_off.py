import sqlite3
import yaml
import sys
import codecs
from pathlib import Path
from dataset_manager.transformers.openfoodfacts import OpenFoodFactsTransformer

sys.stdout.reconfigure(encoding='utf-8')

with open('config/datasets.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
    
off_config = next(d for d in config['datasets'] if d['name'] == 'openfoodfacts')

print('Transforming partial OpenFoodFacts CSV...')
conn = sqlite3.connect('data/metadata/dataset_manager.db')

cursor = conn.cursor()
print('Deleting old OpenFoodFacts records...')
cursor.execute("DELETE FROM items WHERE source = 'OpenFoodFacts'")
conn.commit()
print('Deleted old records, starting parsing...')

transformer = OpenFoodFactsTransformer(conn)
raw_dir = Path('data/raw/openfoodfacts')
transformer.transform(off_config, raw_dir)
conn.close()
