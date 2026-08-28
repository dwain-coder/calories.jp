import sqlite3
import os
from pathlib import Path
from litellm import completion
import json

def run_compliance_check(item_id=None):
    db_path = Path("data/metadata/dataset_manager.db")
    if not db_path.exists():
        print("DB not found.")
        return
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if item_id:
        cursor.execute("SELECT i.id, i.name, ii.ingredients_text, ii.additives_tags, ii.allergens FROM items i JOIN item_ingredients ii ON i.id = ii.item_id WHERE i.id = ?", (item_id,))
    else:
        # Get a Japanese OpenFoodFacts item that has some additives or allergens
        cursor.execute("SELECT i.id, i.name, ii.ingredients_text, ii.additives_tags, ii.allergens FROM items i JOIN item_ingredients ii ON i.id = ii.item_id WHERE i.source = 'OpenFoodFacts' AND ii.additives_tags IS NOT NULL AND ii.additives_tags != '' LIMIT 1")
        
    item = cursor.fetchone()
    if not item:
        print("No item with ingredients found to check.")
        return
        
    rules_path = Path("data/raw/caa_food_labeling_standards/food_labeling_standards.md")
    rules_text = ""
    if rules_path.exists():
        rules_text = rules_path.read_text(encoding='utf-8')
    else:
        rules_path = Path("data/raw/tokyo_nerima_food_labeling/nerima_kigenhyoji.md")
        if rules_path.exists():
            rules_text = rules_path.read_text(encoding='utf-8')
            
    if not rules_text:
        print("Could not find extracted rules text. Using generic knowledge instead.")
        rules_text = "Standard Japanese Food Sanitation Law requirements apply."
        
    prompt = f"""
    You are an automated regulatory compliance engine for Japanese food products.
    You will evaluate the following food product against the provided Japanese labeling standards or general Japanese Food Sanitation Law knowledge.
    
    PRODUCT NAME: {item['name']}
    INGREDIENTS: {item['ingredients_text']}
    ADDITIVES: {item['additives_tags']}
    ALLERGENS: {item['allergens']}
    
    REGULATORY TEXT (Reference):
    {rules_text[:3000]}
    
    Analyze the additives and allergens of this product. Does it comply with Japanese labeling standards? Are any of the additives restricted or require specific warnings?
    Return a structured JSON response:
    {{
        "compliant": true/false,
        "flagged_issues": ["issue 1", "issue 2"],
        "recommendation": "string"
    }}
    """
    
    print(f"Checking compliance for: {item['name']}...")
    try:
        response = completion(
            model=os.environ.get("HELM_LLM_MODEL", "gemini/gemini-1.5-flash"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        print("Compliance Result:")
        print(json.dumps(json.loads(response.choices[0].message.content), indent=2))
    except Exception as e:
        print(f"LLM Error: {e}")

if __name__ == "__main__":
    run_compliance_check()
