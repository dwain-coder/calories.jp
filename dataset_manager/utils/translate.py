import os
import json
from typing import List, Dict
from litellm import completion

def batch_translate_to_japanese(items: List[str], batch_size: int = 50) -> Dict[str, str]:
    """
    Translates a list of English food names to Japanese using an LLM in batches.
    Returns a dictionary mapping the original English name to the Japanese translation.
    """
    translations = {}
    
    # Deduplicate
    unique_items = list(set(items))
    total_batches = (len(unique_items) + batch_size - 1) // batch_size
    
    print(f"Translating {len(unique_items)} unique items in {total_batches} batches...")
    
    for i in range(0, len(unique_items), batch_size):
        batch = unique_items[i:i + batch_size]
        
        prompt = f"""
        Translate the following English food item names into natural Japanese.
        Return ONLY a JSON dictionary where the keys are the exact English names provided, and the values are the Japanese translations.
        
        Names to translate:
        {json.dumps(batch)}
        """
        
        try:
            response = completion(
                model=os.environ.get("HELM_LLM_MODEL", "gemini/gemini-1.5-flash"),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            batch_translations = json.loads(response.choices[0].message.content)
            translations.update(batch_translations)
            print(f"Translated batch {i//batch_size + 1}/{total_batches}")
        except Exception as e:
            print(f"Failed to translate batch {i//batch_size + 1}: {e}")
            for item in batch:
                translations[item] = item
                
    return translations
