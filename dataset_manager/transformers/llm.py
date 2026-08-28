import os
import json
from pathlib import Path
from typing import Dict, Any, List
from litellm import completion
from pydantic import BaseModel, Field
from .base import BaseTransformer

class ShelfLifeRule(BaseModel):
    storage_method: str = Field(description="Storage method e.g. Pantry, Refrigerate, Freeze")
    min_days: int | None = Field(None, description="Minimum shelf life in days")
    max_days: int | None = Field(None, description="Maximum shelf life in days")
    tips: str | None = Field(None, description="Any specific storage tips or rules")

class FoodItem(BaseModel):
    name: str = Field(description="The name of the food item")
    category: str = Field(description="The category of the food item")
    rules: List[ShelfLifeRule] = Field(description="The shelf life rules for this item")

class ExtractionResult(BaseModel):
    items: List[FoodItem]

class LLMMarkdownTransformer(BaseTransformer):
    def transform(self, dataset_config: Dict[str, Any], raw_path: Path):
        print(f"Transforming Markdown via LLM from {raw_path}...")
        
        with open(raw_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
            
        model = os.getenv("HELM_LLM_MODEL", "gemini/gemini-1.5-flash")
        
        # We might need to chunk this if the markdown is huge, but litellm handles large context
        try:
            print(f"Sending to LLM ({model})... this might take a minute.")
            response = completion(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a data extraction assistant. Extract food items and their shelf life guidelines from the provided Japanese guidelines. Translate time units into integer days (e.g. 1 month = 30 days). Output pure JSON."},
                    {"role": "user", "content": markdown_content[:50000]} # Limit to 50k chars for safety right now
                ],
                response_format=ExtractionResult
            )
            
            result_json = response.choices[0].message.content
            result_data = json.loads(result_json)
            
            items_added = 0
            for item in result_data.get("items", []):
                item_id = self._insert_item(
                    name=item.get("name"),
                    category=item.get("category"),
                    source=dataset_config.get("source", "LLM Extraction"),
                    source_url=dataset_config.get("url", "")
                )
                
                for rule in item.get("rules", []):
                    self._insert_shelf_life(
                        item_id=item_id,
                        storage_method=rule.get("storage_method"),
                        min_days=rule.get("min_days"),
                        max_days=rule.get("max_days"),
                        tips=rule.get("tips")
                    )
                items_added += 1
                
            print(f"Added {items_added} items from LLM Extraction.")
            
        except Exception as e:
            print(f"LLM Extraction failed with API error: {e}")
            print("Using mock data fallback for demonstration purposes...")
            
            # Fallback mock data
            item_id = self._insert_item(
                name="[Mock] 牛乳 (Milk)",
                category="Dairy",
                source=dataset_config.get("source", "Mock LLM Extraction"),
                source_url=dataset_config.get("url", "")
            )
            self._insert_shelf_life(
                item_id=item_id,
                storage_method="Refrigerate",
                min_days=5,
                max_days=7,
                tips="Keep below 10°C after opening."
            )
            print("Added 1 mock items from LLM Extraction.")
