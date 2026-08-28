import sqlite3
import yaml
import sys
import codecs
from pathlib import Path
from dataset_manager.transformers.wikidata import WikidataTransformer

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

with open('config/datasets.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
    
wd_config = next(d for d in config['datasets'] if d['name'] == 'wikidata_japan_foods')

conn = sqlite3.connect('data/metadata/dataset_manager.db')
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON")
cursor.execute("DELETE FROM items WHERE source = 'Wikidata (SPARQL)'")
conn.commit()

transformer = WikidataTransformer(conn)
transformer.transform(wd_config, Path('.'))
conn.close()
