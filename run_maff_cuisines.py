import sqlite3
import sys
import codecs
import yaml
from pathlib import Path

from dataset_manager.database.db import init_db
from dataset_manager.transformers.maff_cuisines import MAFFCuisinesTransformer

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

# Usage:
#   python run_maff_cuisines.py                 # full crawl (~1,365 dishes, ~20 min)
#   python run_maff_cuisines.py hokkaido        # single prefecture (validation)
#   python run_maff_cuisines.py hokkaido aomori # a few prefectures

init_db()  # ensure the regional_dishes table exists

with open('config/datasets.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
maff_config = dict(next(d for d in config['datasets'] if d['name'] == 'maff_regional_cuisines'))

areas = sys.argv[1:]
if areas:
    maff_config['maff_areas'] = areas
    print(f'Phased run limited to: {areas}')

SOURCE = maff_config['source']

conn = sqlite3.connect('data/metadata/dataset_manager.db')
cur = conn.cursor()

# Idempotency: clear only what this run will re-crawl. A phased run
# (e.g. `run_maff_cuisines.py hokkaido`) must refresh just that prefecture,
# not wipe the other 46. Dish URLs end with `_{area}.html`, so scope the
# delete to that suffix per requested area; a full run clears everything.
# ponytail: relies on the `_{area}.html` slug convention (verified on the site).
if areas:
    for area in areas:
        pat = f"%\\_{area}.html"
        cur.execute(
            "DELETE FROM regional_dishes WHERE item_id IN "
            "(SELECT id FROM items WHERE source = ? AND source_url LIKE ? ESCAPE '\\')",
            (SOURCE, pat),
        )
        cur.execute("DELETE FROM items WHERE source = ? AND source_url LIKE ? ESCAPE '\\'", (SOURCE, pat))
else:
    cur.execute("DELETE FROM regional_dishes WHERE item_id IN (SELECT id FROM items WHERE source = ?)", (SOURCE,))
    cur.execute("DELETE FROM items WHERE source = ?", (SOURCE,))
conn.commit()

MAFFCuisinesTransformer(conn).transform(maff_config, Path('.'))
conn.close()
