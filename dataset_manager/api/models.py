from pydantic import BaseModel
from typing import List, Optional

class Nutrition(BaseModel):
    energy_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    carbs_g: Optional[float] = None

class IngredientInfo(BaseModel):
    ingredients_text: Optional[str] = None
    additives_tags: Optional[str] = None
    allergens: Optional[str] = None

class ShelfLifeRule(BaseModel):
    storage_method: str
    min_days: Optional[int] = None
    max_days: Optional[int] = None
    tips: Optional[str] = None

class NutrientDetail(BaseModel):
    code: str
    name: Optional[str] = None
    unit: Optional[str] = None
    amount: Optional[float] = None

class RegionalDish(BaseModel):
    region: Optional[str] = None
    main_ingredients: Optional[str] = None
    history: Optional[str] = None
    occasion: Optional[str] = None
    how_to_eat: Optional[str] = None
    preservation: Optional[str] = None
    recipe_ingredients: Optional[str] = None
    recipe_steps: Optional[str] = None
class AIEstimationResponse(BaseModel):
    energy_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    carbohydrate_g: Optional[float] = None
    ingredients_text: Optional[str] = None

class AIRecipeResponse(BaseModel):
    recipe_text: str

class JDI8Score(BaseModel):
    score: int
    rice: bool
    miso: bool
    seaweed: bool
    pickles: bool
    green_yellow_veg: bool
    fish: bool
    green_tea: bool
    low_meat: bool
    details: Optional[str] = None

class FoodItem(BaseModel):
    id: int
    name: str
    category: str
    source: str
    source_url: Optional[str] = None
    barcodes: List[str] = []
    nutrition: Optional[Nutrition] = None
    ingredients: Optional[IngredientInfo] = None
    shelf_life: List[ShelfLifeRule] = []
    ai_estimation: Optional[AIEstimationResponse] = None
    ai_recipe: Optional[str] = None
    # Card hints (populated by the list endpoint)
    nutrient_count: Optional[int] = None
    main_ingredients: Optional[str] = None
    # Full detail (populated by the item-detail endpoint)
    nutrients: List[NutrientDetail] = []
    regional_dish: Optional[RegionalDish] = None
    jdi8: Optional[JDI8Score] = None
    license: Optional[str] = None
    license_warning: Optional[str] = None

class ItemListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[FoodItem]

class ErrorResponse(BaseModel):
    detail: str
