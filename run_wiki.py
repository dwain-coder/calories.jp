import sqlite3
import sys
import codecs
from pathlib import Path
from dataset_manager.transformers.wikipedia import WikipediaTransformer

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

conn = sqlite3.connect('data/metadata/dataset_manager.db')
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON")
cursor.execute("DELETE FROM items WHERE source = 'Wikipedia (JA)'")
conn.commit()

transformer = WikipediaTransformer(conn)
dataset_config = {
    'name': 'wikipedia_ja_food',
    'source': 'Wikipedia (JA)'
}
transformer.transform(dataset_config, Path('.'))
conn.close()
