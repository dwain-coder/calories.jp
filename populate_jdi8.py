import sqlite3
import json
import sys
from dataset_manager.utils.jdi8 import calculate_jdi8

# Reconfigure stdout to use UTF-8 to prevent console errors with Japanese chars
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = 'data/metadata/dataset_manager.db'

def main():
    print("Connecting to database...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ensure table exists (in case init_db wasn't run yet)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jdi8_scores (
            item_id INTEGER PRIMARY KEY,
            score INTEGER NOT NULL,
            rice BOOLEAN NOT NULL,
            miso BOOLEAN NOT NULL,
            seaweed BOOLEAN NOT NULL,
            pickles BOOLEAN NOT NULL,
            green_yellow_veg BOOLEAN NOT NULL,
            fish BOOLEAN NOT NULL,
            green_tea BOOLEAN NOT NULL,
            low_meat BOOLEAN NOT NULL,
            details TEXT,
            FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()

    print("Clearing prior JDI8 scores...")
    cursor.execute("DELETE FROM jdi8_scores")
    conn.commit()

    print("Fetching MEXT and MAFF items...")
    # Query MEXT and MAFF items
    cursor.execute("""
        SELECT i.id, i.name, i.category, i.source, 
               rd.main_ingredients, rd.recipe_ingredients, rd.recipe_steps
        FROM items i
        LEFT JOIN regional_dishes rd ON i.id = rd.item_id
        WHERE i.source IN ('MEXT Standard Tables', 'MAFF Our Regional Cuisines')
    """)
    items = cursor.fetchall()
    total = len(items)
    print(f"Found {total} items to process (pre-populating only CC-BY government datasets to maintain quarantine).")

    count = 0
    batch = []
    
    for item in items:
        # Calculate score
        res = calculate_jdi8(
            name=item['name'],
            main_ingredients=item['main_ingredients'] or "",
            recipe_ingredients=item['recipe_ingredients'] or "",
            recipe_steps=item['recipe_steps'] or "",
            category=item['category'] or ""
        )
        
        details_json = json.dumps(res['evidence'], ensure_ascii=False)
        
        batch.append((
            item['id'],
            res['score'],
            1 if res['rice'] else 0,
            1 if res['miso'] else 0,
            1 if res['seaweed'] else 0,
            1 if res['pickles'] else 0,
            1 if res['green_yellow_veg'] else 0,
            1 if res['fish'] else 0,
            1 if res['green_tea'] else 0,
            1 if res['low_meat'] else 0,
            details_json
        ))
        
        count += 1
        if len(batch) >= 100:
            cursor.executemany("""
                INSERT INTO jdi8_scores 
                (item_id, score, rice, miso, seaweed, pickles, green_yellow_veg, fish, green_tea, low_meat, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()
            batch = []
            print(f"Processed {count}/{total}...")

    if batch:
        cursor.executemany("""
            INSERT INTO jdi8_scores 
            (item_id, score, rice, miso, seaweed, pickles, green_yellow_veg, fish, green_tea, low_meat, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        conn.commit()
        print(f"Processed {count}/{total}...")

    # Print some statistics
    cursor.execute("SELECT COUNT(*), AVG(score) FROM jdi8_scores")
    stats = cursor.fetchone()
    print(f"\nJDI8 pre-population complete!")
    print(f"Total scored items: {stats[0]}")
    print(f"Average JDI8 score: {stats[1]:.2f}/8")
    
    # Print top 5 scored MAFF dishes
    print("\nTop 5 scored Traditional Dishes:")
    cursor.execute("""
        SELECT i.name, j.score, rd.region 
        FROM jdi8_scores j
        JOIN items i ON j.item_id = i.id
        JOIN regional_dishes rd ON i.id = rd.item_id
        ORDER BY j.score DESC, i.name ASC
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(f"  {row['name']} ({row['region']}): {row['score']}/8")

    conn.close()

if __name__ == '__main__':
    main()
