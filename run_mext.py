import sqlite3
import sys
import codecs
import yaml
from pathlib import Path

from dataset_manager.database.db import init_db
from dataset_manager.downloaders.http import HttpDownloader
from dataset_manager.transformers.mext import MEXTTransformer

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

SOURCE = "MEXT Standard Tables"

init_db()  # ensure the new nutrients table exists

with open('config/datasets.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
mext_config = next(d for d in config['datasets'] if d['name'] == 'mext_food_composition_2023')

# 1. Download
print('Downloading MEXT Standard Tables...')
raw_dir = Path('data/raw/mext_food_composition_2023')
raw_dir.mkdir(parents=True, exist_ok=True)
if not HttpDownloader().download(mext_config, raw_dir):
    print('Download failed.')
    sys.exit(1)

xlsx = next(raw_dir.glob('*.xlsx'))

# 2. Transform (idempotent: clear prior MEXT items + children first)
print('Transforming MEXT...')
conn = sqlite3.connect('data/metadata/dataset_manager.db')
cur = conn.cursor()
cur.execute("DELETE FROM nutrients WHERE item_id IN (SELECT id FROM items WHERE source = ?)", (SOURCE,))
cur.execute("DELETE FROM nutrition WHERE item_id IN (SELECT id FROM items WHERE source = ?)", (SOURCE,))
cur.execute("DELETE FROM items WHERE source = ?", (SOURCE,))
conn.commit()

MEXTTransformer(conn).transform(mext_config, xlsx)
conn.close()
