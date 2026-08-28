import sqlite3
import pandas as pd
conn = sqlite3.connect('data/metadata/dataset_manager.db')
c = pd.read_sql_query("SELECT count(*) FROM items WHERE source = 'OpenFoodFacts'", conn)
print(c)
conn.close()
