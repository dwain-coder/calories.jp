from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from typing import Optional
import sqlite3
import csv
import io

from .models import ItemListResponse, FoodItem, ErrorResponse, JDI8Score
from .database import search_items, get_item_details, DB_PATH

# main.py does this too, but the app is also started straight through uvicorn,
# and without it SITE_DOMAIN_JA is unset and every canonical URL says localhost.
load_dotenv()

app = FastAPI(
    title="Food Dataset Manager API",
    description="A unified API for massive food data aggregation across global datasets.",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root(request: Request):
    # Browsers get the public site; programmatic clients (React viewer, curl)
    # keep the original JSON stats contract.
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse("/ja/", status_code=302)
    # Fetch some fast stats
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5000.0)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM items")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT source, COUNT(*) FROM items GROUP BY source")
        sources = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        
        return {
            "status": "online",
            "total_items": total,
            "sources": sources
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/items", response_model=ItemListResponse)
def get_items(
    query: Optional[str] = Query(None, description="Search by item name"),
    source: Optional[str] = Query(None, description="Filter by source (e.g., 'OpenFoodFacts', 'MEXT')"),
    category: Optional[str] = Query(None, description="Filter by category"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=1000, description="Items per page")
):
    try:
        results = search_items(query, source, category, page, size)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/items/{item_id}", response_model=FoodItem, responses={404: {"model": ErrorResponse}})
def get_item(item_id: int):
    try:
        item = get_item_details(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return item
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

import os
from google import genai
from google.genai import types
from .database import save_ai_estimation, save_ai_recipe
from .models import AIEstimationResponse, AIRecipeResponse
import json
import re

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    return genai.Client(api_key=api_key)

@app.post("/items/{item_id}/estimate", response_model=AIEstimationResponse)
def estimate_item(item_id: int):
    item = get_item_details(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    client = get_gemini_client()
    prompt = f"""
    You are an expert nutritionist and food scientist.
    Estimate the macro breakdown (per 100g) and the ingredients for the following product:
    Name: {item['name']}
    Category: {item.get('category', 'Unknown')}
    
    Respond ONLY with a valid JSON object matching this exact schema, with no markdown formatting or extra text:
    {{
      "energy_kcal": float (or null),
      "protein_g": float (or null),
      "fat_g": float (or null),
      "carbohydrate_g": float (or null),
      "ingredients_text": "string of ingredients" (or null)
    }}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        text = response.text
        # Remove any markdown code blocks if the model didn't listen
        text = re.sub(r'```json\n?', '', text)
        text = re.sub(r'```\n?', '', text)
        data = json.loads(text.strip())
        
        # Cache it
        save_ai_estimation(
            item_id=item_id,
            energy=data.get('energy_kcal'),
            protein=data.get('protein_g'),
            fat=data.get('fat_g'),
            carbs=data.get('carbohydrate_g'),
            ingredients=data.get('ingredients_text')
        )
        
        return AIEstimationResponse(**data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Estimation failed: {str(e)}")

@app.post("/items/{item_id}/recipe", response_model=AIRecipeResponse)
def get_recipe(item_id: int):
    item = get_item_details(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    client = get_gemini_client()
    prompt = f"""
    You are a creative chef.
    Suggest a quick, 3-step recipe or serving pairing for: {item['name']}.
    Keep it concise, appetizing, and under 70 words.
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        recipe_text = response.text.strip()
        save_ai_recipe(item_id, recipe_text)
        
        return AIRecipeResponse(recipe_text=recipe_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Recipe failed: {str(e)}")

@app.get("/items/{item_id}/jdi8", response_model=JDI8Score, responses={404: {"model": ErrorResponse}})
def get_item_jdi8_endpoint(item_id: int):
    item = get_item_details(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not item.get("jdi8"):
        raise HTTPException(status_code=404, detail="JDI8 score not available for this item (non-Japanese datasets are skipped under the ODbL quarantine plan)")
    return item["jdi8"]

@app.get("/export/clean")
def export_clean_data(format: str = Query("csv", description="Export format (csv or json)")):
    """
    Export clean CC-BY government datasets (MEXT + MAFF) while quarantining ODbL datasets (OpenFoodFacts).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT i.id, i.name, i.category, i.source, i.source_url,
                   n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g,
                   rd.region, rd.main_ingredients, rd.recipe_ingredients, rd.recipe_steps,
                   j.score AS jdi8_score
            FROM items i
            LEFT JOIN nutrition n ON i.id = n.item_id
            LEFT JOIN regional_dishes rd ON i.id = rd.item_id
            LEFT JOIN jdi8_scores j ON i.id = j.item_id
            WHERE i.source IN ('MEXT Standard Tables', 'MAFF Our Regional Cuisines')
        """)
        rows = cursor.fetchall()
        conn.close()
        
        if format.lower() == "json":
            return [dict(row) for row in rows]
        else:
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow([
                "id", "name", "category", "source", "source_url",
                "energy_kcal", "protein_g", "fat_g", "carbohydrate_g",
                "region", "main_ingredients", "recipe_ingredients", "recipe_steps",
                "jdi8_score"
            ])
            
            for row in rows:
                writer.writerow([
                    row["id"], row["name"], row["category"], row["source"], row["source_url"],
                    row["energy_kcal"], row["protein_g"], row["fat_g"], row["carbohydrate_g"],
                    row["region"], row["main_ingredients"], row["recipe_ingredients"], row["recipe_steps"],
                    row["jdi8_score"]
                ])
            
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=clean_japanese_food_data.csv"}
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


# ---- Public bilingual site (additive; existing endpoints above are unchanged) ----
from pathlib import Path as _Path
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from ..site.middleware import add_host_lang_middleware
from ..site.router import router as site_router
from .search_api import router as search_router
from .analyzer import router as analyzer_router

app.add_middleware(GZipMiddleware, minimum_size=1024)
add_host_lang_middleware(app)
app.include_router(search_router)
app.include_router(analyzer_router)
app.include_router(site_router)
if _Path("static").is_dir():
    app.mount("/static", StaticFiles(directory="static"), name="static")
