"""Read endpoints for the drafting tool (Helm), behind a shared key.

The public API answers "what is in this food". A column also states what a
dish adds up to, what a chain publishes for its burger, which foods lead on
iron, and what share of the labelling reference value a serving supplies.
Written from memory, those came out wrong: a natto pack at 83-95 kcal against
the table's 74-92, ひきわり's fibre and vitamin K both backwards. These return
the figures the site's own pages print, with the provenance a writer needs to
phrase them honestly.

Not public, unlike /api/search: the chain menus carry 7,647 figures this site
calculated, and a keyless JSON copy of them is a bulk download. Unset
WRITER_API_KEY and the endpoints do not exist; the webhook in server.py works
the same way.
"""
import hmac
import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ..site import claims, menuterms, nutrient_pages, queries, seo
from ..site.i18n import MACRO_DV, MICRO_DV

LANG = "ja"
WRITER_API_KEY = os.environ.get("WRITER_API_KEY", "")


def _require_key(x_api_key: str = Header("")):
    if not WRITER_API_KEY:
        raise HTTPException(status_code=404, detail="Not found")
    if not hmac.compare_digest(x_api_key, WRITER_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or wrong X-API-Key")


router = APIRouter(prefix="/api", dependencies=[Depends(_require_key)])


def _attribution(source):
    a = seo.ATTRIBUTION.get(source)
    return {"text": a["ja"], "url": a["url"]} if a else None


def _url(kind, slug):
    return seo.base_url(LANG) + f"/{kind}/{quote(slug)}"


# ------------------------------------------------------------------ dishes

@router.get("/dishes/{item_id}/nutrition")
def dish_nutrition(item_id: int):
    """A MAFF regional dish, computed from its recipe the way /dish/{slug} is.

    The total is for the WHOLE recipe, not a serving: MAFF recipes state no
    serving count the tables could divide by. When some ingredient lines did
    not resolve to a table row the total is a lower bound, and `complete`
    says so — 朴葉ずし's rice is one of those, which is most of the dish.
    """
    conn = queries.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM site_pages WHERE item_id = ? AND lang = ? AND page_type = 'dish'",
            (item_id, LANG)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="No public dish with this id")
    d = queries.get_dish_page_data(dict(row))
    c = d["computed"]
    return {
        "item_id": item_id,
        "name": queries.display_name(d["names"], d["item"], LANG),
        "url": _url("dish", row["slug"]),
        "region": d["dish"].get("region"),
        "source": d["item"]["source"],
        "license": d["license"],
        "attribution": _attribution(d["item"]["source"]),
        "nutrition": {
            "basis": "whole_recipe",
            "grams": c.get("grams"),
            "totals": c.get("totals"),
            "per_100g": c.get("per_100g"),
            "complete": c.get("n_resolved") == c.get("n_total"),
            "n_resolved": c.get("n_resolved"),
            "n_total": c.get("n_total"),
            "n_assumed": c.get("n_assumed"),
        } if d["show_nutrition"] else None,
        "ingredients": [{
            "line": l["raw_name"],
            "quantity": l["raw_quantity"],
            "grams": l["grams"],
            "grams_source": l["grams_source"],
            "matched_food": ({"item_id": l["mext_item_id"], "slug": l["mext_slug"]}
                             if l["mext_item_id"] else None),
            "match_method": l["method"],
            "match_confidence": l["confidence"],
        } for l in d["links"]],
    }


# ------------------------------------------------------------------ chains

# What each kcal_source's number is a number OF. A table figure is per 100 g of
# the food the item was linked to; ranked against a whole burger it misleads.
BASIS = {"chain": "per_item_published", "mext_calc": "per_item_estimate", "table": "per_100g"}


@router.get("/menus")
def menus():
    """Every chain with a menu page, and how many of its figures are the chain's own."""
    return [{
        "slug": s["slug"],
        "name": s["name"],
        "url": _url("menu", s["slug"]),
        "item_count": s["item_count"],
        # Rows in the chain's own nutrition table, which can exceed the items
        # the page shows (the page lists only items with a photo).
        "chain_nutrition_rows": s.get("published"),
        "price_min": s["price_min"],
        "price_max": s["price_max"],
        "indexable": bool(s["indexable"]),
    } for s in queries.shops_index(LANG)]


@router.get("/menus/{slug}")
def menu(slug: str):
    """One chain's menu as its page shows it, each figure labelled by origin.

    kcal_source: `chain` is the chain's published figure (see `sources`);
    `mext_calc` is this site's estimate for a standard serving, not the
    chain's recipe; `table` is per 100 g of a composition-table food. Cite a
    `chain` figure to the chain; call the others estimates.
    """
    page = queries.get_shop_page(LANG, slug)
    if not page:
        raise HTTPException(status_code=404, detail="No chain with this slug")
    d = queries.get_shop_page_data(page)
    return {
        "slug": page["slug"],
        "name": d["shop"]["name"],
        "url": _url("menu", page["slug"]),
        "sources": d["sources"],
        "items": [{
            "name": it["name"],
            "official_name": it.get("official_name"),
            "price_yen": it["price_yen"],
            "price_max_yen": it["price_max_yen"],
            "tax_incl": it["tax_incl"],
            "kcal": it["kcal"],
            "protein_g": it["protein_g"],
            "fat_g": it["fat_g"],
            "carbs_g": it["carbs_g"],
            "salt_g": it["salt_g"],
            "kcal_source": it["kcal_source"],
            "basis": BASIS.get(it["kcal_source"]),
            "is_extra": menuterms.is_extra(it["name"]),
            "is_drink": menuterms.is_drink(it["name"]),
            "food_url": (_url(it["food_page_type"], it["food_slug"])
                         if it.get("food_slug") else None),
        } for it in d["menu"]],
    }


# --------------------------------------------------------------- nutrients

@router.get("/nutrients")
def nutrients():
    return [{"slug": slug, "code": code, "name": term, "url": _url("nutrient", slug)}
            for code, slug, term, _blurb in nutrient_pages.NUTRIENTS]


@router.get("/nutrients/{slug}")
def nutrient(slug: str, limit: int = Query(20, ge=1, le=60)):
    """Foods holding the most of one component, per 100 g, measured values only.

    The corpus-wide top is gelatin and dried powders; `category_leaders` is
    the answer to "which meat / fish / vegetable", which is usually the
    question an article is asking.
    """
    spec = nutrient_pages.get(slug)
    if not spec:
        raise HTTPException(status_code=404, detail="No nutrient with this slug")
    code, _slug, term, _blurb = spec
    stats = queries.nutrient_corpus_stats(LANG, code)
    if not stats or not stats.get("n"):
        raise HTTPException(status_code=404, detail="No measured values for this nutrient")
    return {
        "code": code,
        "name": term,
        "url": _url("nutrient", slug),
        "basis": "per_100g",
        "quality": "measured_only",
        "stats": stats,
        "ranking": queries.nutrient_ranking(LANG, code, limit=limit),
        "category_leaders": queries.nutrient_category_leaders(LANG, code),
        "attribution": _attribution("MEXT Standard Tables"),
    }


# -------------------------------------------------------- reference values

@router.get("/reference-values")
def reference_values():
    """The tables any "% of" or "high in" sentence must be measured against.

    Served rather than left to the writer because the site itself got this
    wrong for months — the pre-2025 table, labelled 2020 — and a writer
    working from memory will reproduce whichever edition it read most.
    """
    return {
        "labelling_reference": {
            "source": "食品表示基準 別表第十（令和7年内閣府令第26号による改正）",
            "macros": MACRO_DV[LANG],
            "micros": {code: {"name": name, "value": dv, "unit": unit}
                       for code, (name, dv, unit) in MICRO_DV[LANG].items()},
        },
        "salt_target": {
            "source": "日本人の食事摂取基準（2025年版） 目標量",
            "men_below_g": 7.5,
            "women_below_g": 6.5,
            "note": "食塩には推奨量はなく目標量。",
        },
        "claim_thresholds": {
            "source": "食品表示基準 別表第十二",
            "basis": "per_100g (drinks: per_100ml)",
            "nutrients": {code: {"name": name, "high": hi, "source_of": src,
                                 "high_drink": hi_l, "source_of_drink": src_l, "unit": unit}
                          for code, (name, hi, src, hi_l, src_l, unit)
                          in claims.THRESHOLDS.items()},
        },
    }
