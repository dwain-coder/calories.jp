import os
import sqlite3
import json
from pathlib import Path
from litellm import completion

def run_merge():
    db_path = Path('data/metadata/dataset_manager.db')
    if not db_path.exists():
        print("Database not found.")
        return
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all USDA items
    cursor.execute("SELECT id, name FROM items WHERE source LIKE 'USDA%'")
    usda_items = [{"id": row['id'], "name": row['name']} for row in cursor.fetchall()]
    
    if not usda_items:
        print("No USDA items found.")
        return
        
    # Get MEXT items
    cursor.execute("""
        SELECT id, name FROM items 
        WHERE source = 'MEXT Standard Tables' 
        AND id NOT IN (SELECT mext_item_id FROM unified_items)
        LIMIT 50 -- Limit to 50 for testing
    """)
    mext_items = [{"id": row['id'], "name": row['name']} for row in cursor.fetchall()]
    
    if not mext_items:
        print("No unmatched MEXT items found.")
        return
        
    print(f"Loaded {len(usda_items)} USDA items and {len(mext_items)} unmatched MEXT items.")
    
    # We will send the USDA items as a list of options.
    # To save tokens, we format it as "id: name"
    usda_options = "\n".join([f"{item['id']}: {item['name']}" for item in usda_items])
    
    for mext in mext_items:
        print(f"Evaluating match for MEXT item: {mext['name']}")
        
        prompt = f"""
        You are a cross-lingual entity resolution system.
        I am giving you a Japanese food item: '{mext['name']}'
        
        Below is a list of English food items with their IDs:
        {usda_options}
        
        If there is an exact or very close conceptual match for the Japanese food in the English list, return the ID of the English food.
        If there is no match, return 0.
        
        Return ONLY a JSON object with this format:
        {{"match_id": 123, "confidence": 0.95}}
        """
        
        try:
            response = completion(
                model=os.environ.get("HELM_LLM_MODEL", "gemini/gemini-1.5-flash"),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            match_id = result.get('match_id', 0)
            confidence = result.get('confidence', 0.0)
            
            if match_id > 0 and confidence > 0.8:
                print(f"-> MATCHED with USDA ID {match_id} (Confidence {confidence})")
                cursor.execute(
                    "INSERT INTO unified_items (mext_item_id, usda_item_id, confidence_score) VALUES (?, ?, ?)",
                    (mext['id'], match_id, confidence)
                )
                conn.commit()
            else:
                print("-> No match found.")
                
        except Exception as e:
            print(f"Error calling LLM: {e}")
            
    conn.close()
    print("Merge complete.")
    
if __name__ == "__main__":
    run_merge()
