import sqlite3
import yaml
import sys
import codecs
from pathlib import Path
from dataset_manager.downloaders.stream import StreamDownloader
from dataset_manager.transformers.openfoodfacts import OpenFoodFactsTransformer

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

with open('config/datasets.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
    
off_config = next(d for d in config['datasets'] if d['name'] == 'openfoodfacts')

# 1. Download
print('Downloading OpenFoodFacts...')
downloader = StreamDownloader()
raw_dir = Path('data/raw/openfoodfacts')
raw_dir.mkdir(parents=True, exist_ok=True)
downloader.download(off_config, raw_dir)

# 2. Transform
print('Transforming OpenFoodFacts...')
conn = sqlite3.connect('data/metadata/dataset_manager.db')

# Clear existing openfoodfacts to avoid duplicates/mess
cursor = conn.cursor()
cursor.execute("DELETE FROM items WHERE source = 'OpenFoodFacts'")
conn.commit()

transformer = OpenFoodFactsTransformer(conn)
transformer.transform(off_config, raw_dir)
conn.close()
