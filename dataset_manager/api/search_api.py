"""JSON endpoints for the public site (clean corpus only, via site_pages join)."""
from fastapi import APIRouter, HTTPException, Query

from ..site import queries
from ..site.i18n import LANGS

router = APIRouter(prefix="/api")


@router.get("/search")
def api_search(
    q: str = Query(..., min_length=1, max_length=100),
    lang: str = Query("ja"),
    limit: int = Query(10, ge=1, le=50),
):
    if lang not in LANGS:
        raise HTTPException(status_code=400, detail=f"lang must be one of {', '.join(LANGS)}")
    results = queries.search(q, lang, limit=limit)
    return [
        {
            "item_id": r["item_id"],
            "title": r["name"] or r["title"],
            "slug": r["slug"],
            "page_type": r["page_type"],
            "url": f"/{'food' if r['page_type'] == 'food' else 'dish'}/{r['slug']}",
            "energy_kcal": r["energy_kcal"],
            "source": r["source"],
        }
        for r in results
    ]


@router.get("/atlas")
def api_atlas(lang: str = Query("ja")):
    """Point cloud for the PFC atlas on the home page."""
    if lang not in LANGS:
        raise HTTPException(status_code=400, detail=f"lang must be one of {', '.join(LANGS)}")
    from ..site import groups as g
    from ..site.i18n import MEXT_GROUPS_EN
    data = queries.atlas_points(lang)
    data["colors"] = [g.color(cat) for cat in data["groups"]]
    # FoodData Central stores a flat placeholder category; give it a real label.
    fdc = "USDA Foundation Foods" if lang == "en" else "USDA基準食品"
    data["groups"] = [
        fdc if c == "foundation" else (MEXT_GROUPS_EN.get(c, c) if lang == "en" else c)
        for c in data["groups"]
    ]
    return data


@router.get("/foods/{item_id}/nutrition")
def api_food_nutrition(item_id: int):
    data = queries.food_nutrition_json(item_id)
    if not data:
        raise HTTPException(status_code=404, detail="No public food with this id")
    return data


@router.get("/foods/{item_id}/cooking-yield")
def api_food_cooking_yield(item_id: int):
    """What this food weighs after cooking, as a percentage of its raw weight."""
    conn = queries.get_connection()
    try:
        if not conn.execute(
                "SELECT 1 FROM site_pages WHERE item_id = ? LIMIT 1", (item_id,)).fetchone():
            raise HTTPException(status_code=404, detail="No public food with this id")
        return queries.food_cooking_yield(conn, item_id)
    finally:
        conn.close()


@router.get("/cooking-yield")
def api_cooking_yield(
    q: str = Query(..., min_length=1, max_length=100),
    lang: str = Query("ja"),
    limit: int = Query(20, ge=1, le=100),
):
    """Weight-change rates by food name.

    A recipe is written in raw weights and a composition table in cooked ones,
    so the two cannot be compared without this number. MEXT publishes it and
    almost nothing else exposes it.
    """
    if lang not in LANGS:
        raise HTTPException(status_code=400, detail=f"lang must be one of {', '.join(LANGS)}")
    return queries.cooking_yield_search(q, lang, limit=limit)
