import os
import sqlite3
from typing import List, Dict, Any, Optional

# Single source of truth for where the corpus lives. Hosted deployments keep it
# on a mounted volume rather than in the image, so the path is an env var:
#   DATABASE_PATH=/data/dataset_manager.db
DB_PATH = os.environ.get("DATABASE_PATH", "data/metadata/dataset_manager.db")

def get_license_info(source: str) -> tuple[str, str]:
    if source == "OpenFoodFacts":
        return "ODbL 1.0 (Open Database License)", "Contains OpenFoodFacts data. Derivative databases must be ODbL licensed if distributed."
    elif source == "MEXT Standard Tables":
        return "Government Standard Terms of Use (Requires Attribution)", "Free commercial use with attribution to MEXT."
    elif source == "MAFF Our Regional Cuisines":
        return "Government Standard Terms of Use (Requires Attribution)", "Free commercial use with attribution to MAFF."
    elif "USDA" in source:
        return "CC0 / Public Domain", "Public domain. No restrictions."
    elif "Wikidata" in source:
        return "CC0 / Public Domain", "Public domain semantic data from Wikidata."
    elif "Wikipedia" in source:
        return "CC BY-SA 4.0", "Licensed under Creative Commons Attribution-ShareAlike 4.0."
    else:
        return "Unknown", None

def get_connection():
    # Use URI to enable read-only mode if needed, but for now just standard connect
    # with a high timeout to handle concurrent writes from the massive stream
    conn = sqlite3.connect(DB_PATH, timeout=5000.0)
    conn.row_factory = sqlite3.Row
    # WAL mode improves concurrency (reads don't block writes)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def search_items(query: Optional[str] = None, source: Optional[str] = None, category: Optional[str] = None, page: int = 1, size: int = 50) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    
    offset = (page - 1) * size
    
    where_clauses = []
    params = []
    
    if query:
        where_clauses.append("name LIKE ?")
        params.append(f"%{query}%")
    if source:
        where_clauses.append("source = ?")
        params.append(source)
    if category:
        where_clauses.append("category = ?")
        params.append(category)
        
    where_stmt = ""
    if where_clauses:
        where_stmt = "WHERE " + " AND ".join(where_clauses)
        
    # Get total count
    count_query = f"SELECT COUNT(*) FROM items {where_stmt}"
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
    
    # Get items with nutrition + card hints (full-nutrient count for MEXT,
    # main ingredients for MAFF regional dishes).
    select_query = f"""
        SELECT items.*,
               nutrition.energy_kcal, nutrition.protein_g, nutrition.fat_g, nutrition.carbohydrate_g,
               rd.main_ingredients,
               (SELECT COUNT(*) FROM nutrients WHERE nutrients.item_id = items.id) AS nutrient_count
        FROM items
        LEFT JOIN nutrition ON items.id = nutrition.item_id
        LEFT JOIN regional_dishes rd ON items.id = rd.item_id
        {where_stmt} LIMIT ? OFFSET ?
    """
    cursor.execute(select_query, params + [size, offset])
    rows = cursor.fetchall()

    items = []
    for row in rows:
        lic, warning = get_license_info(row["source"])
        item_data = {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "source": row["source"],
            "source_url": row["source_url"],
            "license": lic,
            "license_warning": warning
        }

        # Add basic nutrition if available
        if row["energy_kcal"] is not None or row["protein_g"] is not None:
            item_data["nutrition"] = {
                "energy_kcal": row["energy_kcal"],
                "protein_g": row["protein_g"],
                "fat_g": row["fat_g"],
                "carbs_g": row["carbohydrate_g"]
            }

        if row["nutrient_count"]:
            item_data["nutrient_count"] = row["nutrient_count"]
        if row["main_ingredients"]:
            item_data["main_ingredients"] = row["main_ingredients"]

        items.append(item_data)
        
    conn.close()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": items
    }

def get_item_details(item_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    if not item:
        conn.close()
        return None
        
    result = dict(item)
    
    # Get barcodes
    cursor.execute("SELECT upc FROM barcodes WHERE item_id = ?", (item_id,))
    result["barcodes"] = [row["upc"] for row in cursor.fetchall()]
    
    # Get nutrition
    cursor.execute("SELECT * FROM nutrition WHERE item_id = ?", (item_id,))
    nut = cursor.fetchone()
    if nut and any(x is not None for x in [nut["energy_kcal"], nut["protein_g"], nut["fat_g"], nut["carbohydrate_g"]]):
        result["nutrition"] = {
            "energy_kcal": nut["energy_kcal"],
            "protein_g": nut["protein_g"],
            "fat_g": nut["fat_g"],
            "carbs_g": nut["carbohydrate_g"]
        }
    else:
        result["nutrition"] = None
        
    # Get ingredients (handle both tables in case data is in one or the other)
    cursor.execute("SELECT * FROM ingredients WHERE item_id = ?", (item_id,))
    ing = cursor.fetchone()
    if not ing:
        # Try old table
        cursor.execute("SELECT * FROM item_ingredients WHERE item_id = ?", (item_id,))
        ing = cursor.fetchone()
        
    if ing:
        result["ingredients"] = {
            "ingredients_text": ing["ingredients_text"],
            "additives_tags": ing["additives_tags"] if "additives_tags" in ing.keys() else None,
            "allergens": ing["allergens"] if "allergens" in ing.keys() else None
        }
    else:
        result["ingredients"] = None
        
    # Get full nutrient breakdown (MEXT: all ~54 components)
    cursor.execute("SELECT code, name, unit, amount FROM nutrients WHERE item_id = ? ORDER BY id", (item_id,))
    result["nutrients"] = [dict(r) for r in cursor.fetchall()]

    # Get regional dish detail (MAFF)
    cursor.execute(
        """SELECT region, main_ingredients, history, occasion, how_to_eat,
                  preservation, recipe_ingredients, recipe_steps
           FROM regional_dishes WHERE item_id = ?""",
        (item_id,),
    )
    rd = cursor.fetchone()
    result["regional_dish"] = dict(rd) if rd else None

    # Get shelf life
    cursor.execute("SELECT storage_method, min_days, max_days, tips FROM shelf_life WHERE item_id = ?", (item_id,))
    shelf_life_rules = []
    for rule in cursor.fetchall():
        shelf_life_rules.append({
            "storage_method": rule["storage_method"],
            "min_days": rule["min_days"],
            "max_days": rule["max_days"],
            "tips": rule["tips"]
        })
    result["shelf_life"] = shelf_life_rules
        
    # Get AI Estimation if exists
    cursor.execute("SELECT * FROM ai_estimations WHERE item_id = ?", (item_id,))
    ai_est = cursor.fetchone()
    if ai_est:
        result["ai_estimation"] = {
            "energy_kcal": ai_est["energy_kcal"],
            "protein_g": ai_est["protein_g"],
            "fat_g": ai_est["fat_g"],
            "carbohydrate_g": ai_est["carbohydrate_g"],
            "ingredients_text": ai_est["ingredients_text"]
        }
        
    # Get AI Recipe if exists
    cursor.execute("SELECT recipe_text FROM ai_recipes WHERE item_id = ?", (item_id,))
    ai_rec = cursor.fetchone()
    if ai_rec:
        result["ai_recipe"] = ai_rec["recipe_text"]
        
    # Get JDI8 Score
    cursor.execute("SELECT * FROM jdi8_scores WHERE item_id = ?", (item_id,))
    jdi_row = cursor.fetchone()
    if jdi_row:
        result["jdi8"] = {
            "score": jdi_row["score"],
            "rice": bool(jdi_row["rice"]),
            "miso": bool(jdi_row["miso"]),
            "seaweed": bool(jdi_row["seaweed"]),
            "pickles": bool(jdi_row["pickles"]),
            "green_yellow_veg": bool(jdi_row["green_yellow_veg"]),
            "fish": bool(jdi_row["fish"]),
            "green_tea": bool(jdi_row["green_tea"]),
            "low_meat": bool(jdi_row["low_meat"]),
            "details": jdi_row["details"]
        }
    else:
        result["jdi8"] = None

    # Get license info
    lic, warning = get_license_info(result["source"])
    result["license"] = lic
    result["license_warning"] = warning

    conn.close()
    return result

def save_ai_estimation(item_id: int, energy: float, protein: float, fat: float, carbs: float, ingredients: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO ai_estimations 
        (item_id, energy_kcal, protein_g, fat_g, carbohydrate_g, ingredients_text)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (item_id, energy, protein, fat, carbs, ingredients))
    conn.commit()
    conn.close()

def save_ai_recipe(item_id: int, recipe_text: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO ai_recipes (item_id, recipe_text) VALUES (?, ?)", (item_id, recipe_text))
    conn.commit()
    conn.close()
