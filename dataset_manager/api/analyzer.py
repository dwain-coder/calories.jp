"""AI meal photo analyzer.

Pipeline: validated image -> Gemini vision (structured JSON) -> match each
detected food to the clean corpus via search -> deterministic totals from
DB per-100g values x AI-estimated grams. DB values and AI estimates are kept
separate in the response; nothing AI-derived is presented as verified.
"""
import hashlib
import json
import os
import sqlite3
import time
import re

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from ..calc.nutrition import meal_insights, scale, sum_components
from ..site import foodterms, queries, servings
from ..site.i18n import LANGS, MACRO_DV, MICRO_DV, t
from .database import DB_PATH, get_license_info

router = APIRouter(prefix="/api")

MAX_BYTES = 8 * 1024 * 1024
# Each miss costs a vision-model call, so cap what one address can spend.
# Cached repeats are free and are not counted.
RATE_LIMIT = int(os.environ.get("ANALYZER_RATE_LIMIT", "12"))
RATE_WINDOW = int(os.environ.get("ANALYZER_RATE_WINDOW", "3600"))
_hits = {}


def _rate_limit(client_ip):
    """Fixed-window counter, in process. Single-worker deployment only —
    put the limit in the proxy if this ever runs multi-worker."""
    now = time.time()
    cutoff = now - RATE_WINDOW
    seen = [t for t in _hits.get(client_ip, ()) if t > cutoff]
    if len(_hits) > 4096:                      # bound the table
        for k in [k for k, v in _hits.items() if not any(t > cutoff for t in v)]:
            _hits.pop(k, None)
    if len(seen) >= RATE_LIMIT:
        retry = int(seen[0] + RATE_WINDOW - now)
        raise HTTPException(
            status_code=429,
            detail=f"Analysis limit reached ({RATE_LIMIT} per hour). Try again in {max(retry // 60, 1)} minutes.",
            headers={"Retry-After": str(max(retry, 1))},
        )
    seen.append(now)
    _hits[client_ip] = seen
MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # + 'WEBP' at offset 8, checked below
}

VISION_PROMPT = """You are reading a photograph of a meal for a nutrition database.

List every dish you can see, and break each one into the ingredients it is made of.
A composite dish — lasagna, curry, a sandwich, a bento — must be given as its
components (the pasta, the minced beef, the tomato sauce, the cheese, the white
sauce), never as a single line: the database holds ingredients and basic foods,
so a dish name on its own can be matched to nothing and the meal ends up with no
figures at all. A simple food (an apple, a grilled fillet) is one dish with one
component.

Name each component the way a national food composition table would: a generic
ingredient name with its state when that changes the food (raw, boiled, fried,
dried). Give the Japanese name and the English one. No brand names, no dish
names inside components.

Two things decide whether the figures come out right:

* Name the food in the state it is IN THE PHOTOGRAPH, not the state it was
  bought in. Rice in a bowl is ご飯, never 米 or 白米 — the dry grain holds
  twice the calories of the same weight cooked. Boiled noodles are ゆで.
* Always name the animal or species. 「もも肉」 could be any animal, and the
  table will answer about the wrong one; write 「豚もも肉」 or 「鶏もも肉」.
  Say whether meat has its fat on it (脂身つき) or is trimmed lean (赤肉).

Estimate the edible grams of each component as served in the photograph — what
is on the plate, not the recipe for a whole tray — and be conservative.
servings_visible is how many portions the photograph shows, usually 1.

Respond ONLY with a JSON object:
{"dishes": [{"dish_ja": "...", "dish_en": "...", "servings_visible": 1,
  "components": [{"name_ja": "...", "name_en": "...",
                  "estimated_grams": <number>, "confidence": "high"|"medium"|"low"}]}]}
If you cannot identify a component confidently, still list it with confidence
"low". Do not invent nutrition values; quantities only."""


def _sniff(data: bytes):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _cache_get(sha, lang):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    row = conn.execute(
        "SELECT result_json FROM ai_meal_analyses WHERE image_sha256 = ? AND lang = ?",
        (sha, lang)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def _cache_put(sha, lang, result):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute(
        "INSERT OR REPLACE INTO ai_meal_analyses (image_sha256, lang, result_json) VALUES (?, ?, ?)",
        (sha, lang, json.dumps(result, ensure_ascii=False)))
    conn.commit()
    conn.close()


def _as_dishes(payload):
    """Normalise the model's reply to [{dish, servings, components:[...]}].

    The prompt asks for dishes, but a model occasionally answers with the old
    flat food list, and cached analyses from before the change have that shape
    too. Both are accepted rather than throwing away a paid call.
    """
    dishes = payload.get("dishes")
    if isinstance(dishes, list) and dishes:
        out = []
        for d in dishes:
            comps = d.get("components") or []
            if not isinstance(comps, list) or not comps:
                continue
            out.append({
                "dish_ja": d.get("dish_ja"), "dish_en": d.get("dish_en"),
                "servings": _positive(d.get("servings_visible")) or 1,
                "components": comps,
            })
        if out:
            return out
    foods = payload.get("foods")
    if isinstance(foods, list) and foods:
        return [{"dish_ja": None, "dish_en": None, "servings": 1, "components": foods}]
    return []


def _positive(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _per_serving(totals, servings):
    """Totals divided by the portions on the plate. Deterministic, like every
    other number here — the model supplies the count, never the arithmetic."""
    if not totals or not servings or servings <= 1:
        return None
    return {k: (round(v / servings, 2) if isinstance(v, (int, float)) else v)
            for k, v in totals.items()}


def _upgrade_cached(result):
    """Give an analysis stored before the dish breakdown existed the newer
    shape, so a photo analysed yesterday still renders today. One unnamed
    dish holding everything that was found: no numbers change."""
    if result.get("dishes") is not None:
        return result
    components = result.get("components") or []
    unmatched = result.get("unmatched") or []
    result["dishes"] = [{
        "name_ja": None, "name_en": None, "servings": 1,
        "component_indexes": list(range(len(components))),
        "totals": result.get("totals"),
        "per_serving": None,
        "grams": round(sum(g for g in (
            c.get("ai_estimate", {}).get("estimated_grams") for c in components) if g), 1),
        "n_matched": len(components),
        "n_total": len(components) + len(unmatched),
    }] if components else []
    result.setdefault("per_serving", None)
    result.setdefault("servings", 1)
    return result


# What one plate can hold. The model estimates grams from a photograph and is
# occasionally wildly out — a bowl of rice read as 2 kg — and a single bad
# estimate silently multiplies the meal's calories. These are deliberately
# loose: the job is to catch the absurd, not to second-guess a large portion.
MAX_COMPONENT_G = 1500.0        # one ingredient on one plate
MAX_MEAL_G = 4000.0             # everything visible in one photograph
SERVING_MULTIPLE = 8.0          # vs a known serving for that food


def _implausible(name_ja, grams, match):
    """Why this quantity cannot be right, or None if it can.

    Returns a reason key rather than dropping the component: the food was
    still recognised, and saying "this quantity looks wrong" is more use than
    quietly leaving it out of the total.
    """
    if grams is None:
        return None
    if grams > MAX_COMPONENT_G:
        return "too_much"
    serving = servings.for_food(match["name"]) if match else servings.for_food(name_ja or "")
    if serving and grams > serving["grams"] * SERVING_MULTIPLE:
        return "many_servings"
    return None


def _match_food(name_ja, name_en, lang, cooked=False):
    """Best clean-corpus match (MEXT > FDC priority is applied inside search).

    A model names food the way a cook does — 「牛肉（加熱）」 — and the tables do
    not, so the everyday name is translated into the tables' vocabulary before
    searching. Without it the beef in a photo matched nothing and silently left
    the totals.

    `cooked` passes the dish's own state down: rice on a plate is ご飯, even
    when the model calls it 白米.
    """
    if name_ja and foodterms.is_ignorable(name_ja):
        return None                     # water: a real ingredient, no nutrition
    tried = []
    for q in (name_ja, name_en):
        if not q:
            continue
        tried.extend(foodterms.search_terms(q, cooked=cooked) if q == name_ja else [q])
    asked = name_ja or name_en or ""
    for q in tried:
        # Twelve, not five: the reranking below can only choose among the rows
        # the search returned, and 「うし 乳用肥育牛肉 かた 脂身つき 焼き」 sits well
        # below 「かた 赤肉 焼き」 for the query 「牛肉 焼き」.
        foods = [h for h in queries.search(q, lang, limit=12) if h["page_type"] == "food"]
        # Serving beef for pork is worse than serving nothing: the figures look
        # authoritative and are about a different animal.
        foods = [h for h in foods if not foodterms.conflicts(asked, h["name"])]
        if not foods:
            continue
        # The composition tables are laboratory analyses of Japanese foods; the
        # USDA rows are a fallback for what they do not cover, so a MEXT hit
        # wins even when it ranks lower.
        mext = [h for h in foods if h["source"] == "MEXT Standard Tables"]
        # A recipe's 「ひじき 20g」 is 20 g of rehydrated hijiki, but the table's
        # canonical row is the dried one it is sold as — 186 kcal/100 g against
        # 13 for ゆで. Unless the name itself says dried, the prepared row wins.
        name_of = lambda h: h.get("name") or h.get("title") or ""   # noqa: E731
        ranked = foodterms.prefer_rehydrated(asked, mext or foods, name_of=name_of)
        # Last word goes to the state and the cut the asker actually named. The
        # model says 脂身つき and 炒め; the tables publish exactly those rows, and
        # the index was handing back the plainest one — 175 kcal of 赤肉 for a
        # 322 kcal 脂身つき cut, 23 kcal of raw cabbage for 78 kcal of 油いため.
        ranked = foodterms.prefer_state(asked, ranked, name_of=name_of)
        return ranked[0]
    return None


@router.post("/meal-analyzer")
async def analyze_meal(request: Request, image: UploadFile = File(...), lang: str = Query("ja")):
    if lang not in LANGS:
        raise HTTPException(status_code=400, detail=f"lang must be one of {', '.join(LANGS)}")
    data = await image.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 8 MB)")
    mime = _sniff(data)
    if not mime:
        raise HTTPException(status_code=415, detail="Unsupported image type (jpeg/png/webp only)")

    sha = hashlib.sha256(data).hexdigest()
    cached = _cache_get(sha, lang)
    if cached is not None:
        cached["cached"] = True
        return _upgrade_cached(cached)     # served from cache, costs nothing

    _rate_limit(request.client.host if request.client else "unknown")

    from .server import get_gemini_client, gemini_model  # reuse client + key handling
    from google.genai import types
    client = get_gemini_client()
    try:
        resp = client.models.generate_content(
            model=gemini_model(),
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime),
                VISION_PROMPT,
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        payload = json.loads(resp.text)
        dishes_in = _as_dishes(payload)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI analysis unavailable: {e}")

    result = calculate_nutrition_for_dishes(dishes_in, lang=lang)
    _cache_put(sha, lang, result)
    return result


def calculate_nutrition_for_dishes(dishes_in, lang="ja"):
    """Deterministic calculation: match components to clean DB rows x estimated grams."""
    components, unmatched, parts, dishes = [], [], [], []
    for di, dish in enumerate(dishes_in):
        dish_parts, dish_component_ix, dish_unmatched = [], [], 0
        cooked = foodterms.is_cooked_dish(dish["dish_ja"] or dish["dish_en"] or "")
        for f in dish["components"]:
            name_ja, name_en = f.get("name_ja"), f.get("name_en")
            grams = _positive(f.get("estimated_grams"))
            conf = f.get("confidence", "low")
            match = _match_food(name_ja, name_en, lang, cooked=cooked)
            if not match:
                dish_unmatched += 1
                unmatched.append({"name_ja": name_ja, "name_en": name_en,
                                  "confidence": conf, "dish_index": di,
                                  "estimated_grams": grams})
                continue
            nut = queries.food_nutrition_json(match["item_id"])
            per100 = nut["per_100g"] if nut else None
            doubt = _implausible(name_ja, grams, match)
            scaled = scale(per100, grams) if (per100 and grams and not doubt) else None
            if scaled:
                parts.append(scaled)
                dish_parts.append(scaled)
            lic, _ = get_license_info(match["source"])
            dish_component_ix.append(len(components))
            components.append({
                "dish_index": di,
                "identified": {"name_ja": name_ja, "name_en": name_en, "confidence": conf},
                "ai_estimate": {"estimated_grams": grams, "estimated": True,
                                "implausible": doubt},
                "db_match": {
                    "item_id": match["item_id"],
                    "title": match.get("name") or match["title"],
                    "url": f"/food/{match['slug']}",
                    "source": match["source"],
                    "license": lic,
                    "per_100g": per100,
                },
                "calculated": scaled,  # deterministic: DB per-100g x AI grams
            })
        dish_totals, _ = sum_components(dish_parts)
        dishes.append({
            "name_ja": dish["dish_ja"], "name_en": dish["dish_en"],
            "servings": dish["servings"],
            "component_indexes": dish_component_ix,
            "totals": dish_totals if dish_parts else None,
            "per_serving": _per_serving(dish_totals, dish["servings"]) if dish_parts else None,
            "grams": round(sum(c for c in (
                components[i]["ai_estimate"]["estimated_grams"] for i in dish_component_ix)
                if c), 1),
            "n_matched": len(dish_component_ix),
            "n_total": len(dish_component_ix) + dish_unmatched,
        })

    totals, missing = sum_components(parts)

    item_grams = [
        (c["db_match"]["item_id"], c["ai_estimate"]["estimated_grams"])
        for c in components if c["calculated"]
    ]
    micro_codes = list(MICRO_DV[lang].keys()) + ["FIB-", "NACL_EQ"]
    micro_totals, n_micro = queries.sum_micros(item_grams, micro_codes)
    fiber_g = micro_totals.pop("FIB-", None)
    salt_g = micro_totals.pop("NACL_EQ", None)
    micronutrients = []
    for code, (label, dv, unit) in MICRO_DV[lang].items():
        amount = micro_totals.get(code)
        if amount is not None:
            micronutrients.append({
                "code": code, "label": label, "amount": round(amount, 1),
                "unit": unit, "dv": dv, "dv_pct": round(amount / dv * 100),
            })
    micronutrients.sort(key=lambda m: -m["dv_pct"])

    dv = MACRO_DV[lang]
    insights = [
        {"level": level, "text": t(lang, key, **params)}
        for level, key, params in meal_insights(totals, salt_g=salt_g, fiber_g=fiber_g, dv=dv)
    ]

    meal_servings = dishes[0]["servings"] if len(dishes) == 1 else 1
    return {
        "dishes": dishes,
        "components": components,
        "unmatched": unmatched,
        "totals": totals,
        "per_serving": _per_serving(totals, meal_servings),
        "servings": meal_servings,
        "salt_g": round(salt_g, 2) if salt_g is not None else None,
        "fiber_g": round(fiber_g, 1) if fiber_g is not None else None,
        "macro_dv": dv,
        "micronutrients": micronutrients,
        "micros_from": n_micro,
        "insights": insights,
        "totals_note": t(lang, "analyzer_totals_note"),
        # An ingredient the tables do not carry contributes NOTHING to the sum
        # above, so the sum is a lower bound rather than the meal — a 150 g
        # steak that matched nothing took a plate from 290 kcal to 34. Say so
        # in the response, so every caller shows it the same way instead of
        # each one deciding for itself.
        "totals_partial": bool(unmatched),
        "unmatched_grams": round(
            sum(u.get("estimated_grams") or 0 for u in unmatched), 1) or None,
        "missing_fields": missing,
        "cached": False,
    }


def _decompose_with_model(name, shop_name=None):
    """Gemini's reading of the whole dish name, or None."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            from .server import get_gemini_client, gemini_model
            from google.genai import types
            client = get_gemini_client()
            prompt = f"""You are an expert Japanese restaurant chef and nutritionist.
The customer is ordering this meal from '{shop_name or 'Japanese restaurant'}':
Dish name: {name}

Break down this restaurant dish/meal into its typical components and standard weights in grams as served.
Rules:
- If it's a set/combo (e.g. ラーメン＆半ライスセット), include all items in the combo (e.g. ramen ingredients PLUS ご飯 120g).
- If it has toppings specified (e.g. ねぎ, 背脂, チャーシュー), include those extra toppings.
- Use generic Japanese ingredient names recognizable in standard food composition tables.

Respond ONLY with a valid JSON object:
{{"dishes": [{{"dish_ja": "{name}", "dish_en": "Meal", "servings_visible": 1,
  "components": [{{"name_ja": "...", "name_en": "...", "estimated_grams": 100, "confidence": "high"}}]}}]}}
"""
            resp = client.models.generate_content(
                model=gemini_model(),
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            payload = json.loads(resp.text)
            dishes = _as_dishes(payload)
            if dishes:
                return dishes
        except Exception:
            pass

    return None


def _heuristic_components(name, shop_name=None):
    """Ingredients and grams for one dish name, from its words alone.

    A ladder of keyword tests, and the reason the estimates were not
    dish-specific: the first branch that matches wins and nothing else in
    the name is read. Kept as it is — it encodes a lot of real menu
    vocabulary — and wrapped by decompose_dish_text, which now hands it one
    dish at a time and then applies any weight the name stated.
    """
    # Culinary composition heuristic for Japanese restaurant dishes
    comps = []

    # Check for explicit accompaniment rice or soup
    # e.g., （ライス付）, (ご飯付), ライスつき, 麦ごはん付, 半ライス, 小ライス
    has_explicit_rice = bool(re.search(r'[(（]?(?:(?<!ス)ライス|ご飯|ごはん|白米|麦ごはん|麦飯)(?:付|つき|セット)?[)）]?', name)) or any(
        k in name for k in ('半ライス', '小ライス', '大盛ライス', 'ライスセット', 'ごはんセット', 'ご飯セット')
    )
    has_explicit_soup = any(k in name for k in ('みそ汁', '味噌汁', 'スープ付', 'スープつき', 'スープセット'))

    def get_rice_grams(base_g=240.0):
        if any(k in name for k in ('大盛', '大盛り', '特盛')):
            return min(base_g * 1.25, 320.0)
        if any(k in name for k in ('小', 'ミニ', 'ハーフ', '半')):
            return max(base_g * 0.65, 120.0)
        return base_g

    is_tanpin = "単品" in name and not any(k in name for k in ("定食", "セット"))

    # 1. Donburi & Ju (丼・重 - Rice Bowl Meals: Check BEFORE individual meats, steaks or noodles)
    if ("丼" in name or "重" in name) and not any(k in name for k in ("ドレッシング", "タレ", "ふりかけ", "スパイス")):
        rice_g = get_rice_grams(240.0)
        comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

        if any(k in name for k in ("鉄火", "まぐろ", "マグロ", "本まぐろ", "中とろ", "大とろ", "トロ", "とろ", "赤身")):
            comps.append({"name_ja": "まぐろ", "name_en": "Tuna", "estimated_grams": 75.0, "confidence": "high"})
            comps.append({"name_ja": "のり", "name_en": "Nori Seaweed", "estimated_grams": 1.5, "confidence": "high"})
            comps.append({"name_ja": "しょうゆ", "name_en": "Soy Sauce", "estimated_grams": 10.0, "confidence": "high"})
            if "アボカ" in name or "アボカド" in name:
                comps.append({"name_ja": "アボカド", "name_en": "Avocado", "estimated_grams": 25.0, "confidence": "high"})
            if "ユッケ" in name:
                comps.append({"name_ja": "卵", "name_en": "Egg Yolk", "estimated_grams": 20.0, "confidence": "high"})
        elif "ねぎとろ" in name or "ネギトロ" in name:
            comps.append({"name_ja": "まぐろ", "name_en": "Minced Tuna", "estimated_grams": 75.0, "confidence": "high"})
            comps.append({"name_ja": "ねぎ", "name_en": "Green Onion", "estimated_grams": 10.0, "confidence": "high"})
            comps.append({"name_ja": "しょうゆ", "name_en": "Soy Sauce", "estimated_grams": 10.0, "confidence": "high"})
        elif "サーモン" in name or "鮭" in name:
            comps.append({"name_ja": "サーモン", "name_en": "Salmon", "estimated_grams": 75.0, "confidence": "high"})
            comps.append({"name_ja": "しょうゆ", "name_en": "Soy Sauce", "estimated_grams": 10.0, "confidence": "high"})
            if "いくら" in name:
                comps.append({"name_ja": "いくら", "name_en": "Salmon Roe", "estimated_grams": 30.0, "confidence": "high"})
        elif "いくら" in name or "イクラ" in name:
            comps.append({"name_ja": "いくら", "name_en": "Salmon Roe", "estimated_grams": 60.0, "confidence": "high"})
            comps.append({"name_ja": "のり", "name_en": "Nori Seaweed", "estimated_grams": 1.5, "confidence": "high"})
        elif "しらす" in name or "シラス" in name:
            comps.append({"name_ja": "しらす干し", "name_en": "Whitebait", "estimated_grams": 45.0, "confidence": "high"})
            comps.append({"name_ja": "のり", "name_en": "Nori Seaweed", "estimated_grams": 1.5, "confidence": "high"})
            comps.append({"name_ja": "しょうゆ", "name_en": "Soy Sauce", "estimated_grams": 8.0, "confidence": "high"})
        elif any(k in name for k in ("海鮮", "ちらし", "おさかな", "魚", "てっぺん", "5色", "3色", "贅沢")):
            comps.append({"name_ja": "まぐろ", "name_en": "Tuna Sashimi", "estimated_grams": 40.0, "confidence": "high"})
            comps.append({"name_ja": "サーモン", "name_en": "Salmon Sashimi", "estimated_grams": 30.0, "confidence": "high"})
            comps.append({"name_ja": "えび", "name_en": "Shrimp", "estimated_grams": 25.0, "confidence": "high"})
            comps.append({"name_ja": "しょうゆ", "name_en": "Soy Sauce", "estimated_grams": 10.0, "confidence": "high"})
        elif "かつ" in name or "カツ" in name:
            comps.append({"name_ja": "とんかつ", "name_en": "Pork Cutlet", "estimated_grams": 120.0, "confidence": "high"})
            comps.append({"name_ja": "卵", "name_en": "Egg", "estimated_grams": 55.0, "confidence": "high"})
            comps.append({"name_ja": "たまねぎ", "name_en": "Onion", "estimated_grams": 35.0, "confidence": "high"})
        elif "親子" in name:
            comps.append({"name_ja": "鶏肉", "name_en": "Chicken", "estimated_grams": 80.0, "confidence": "high"})
            comps.append({"name_ja": "卵", "name_en": "Egg", "estimated_grams": 60.0, "confidence": "high"})
            comps.append({"name_ja": "たまねぎ", "name_en": "Onion", "estimated_grams": 35.0, "confidence": "high"})
        elif "天" in name or "えび" in name or "海老" in name:
            comps.append({"name_ja": "えび", "name_en": "Shrimp Tempura", "estimated_grams": 60.0, "confidence": "high"})
            comps.append({"name_ja": "めんつゆ", "name_en": "Tare Sauce", "estimated_grams": 30.0, "confidence": "high"})
        elif "うな" in name or "鰻" in name:
            comps.append({"name_ja": "うなぎ", "name_en": "Grilled Eel", "estimated_grams": 90.0, "confidence": "high"})
            comps.append({"name_ja": "しょうゆ", "name_en": "Tare Sauce", "estimated_grams": 15.0, "confidence": "high"})
        elif any(k in name for k in ("牛", "カルビ", "ステーキ")):
            comps.append({"name_ja": "牛肉", "name_en": "Beef", "estimated_grams": 85.0, "confidence": "high"})
            comps.append({"name_ja": "たまねぎ", "name_en": "Onion", "estimated_grams": 40.0, "confidence": "high"})
        elif any(k in name for k in ("豚", "豚カルビ", "生姜焼", "とん")):
            comps.append({"name_ja": "豚肉", "name_en": "Pork", "estimated_grams": 85.0, "confidence": "high"})
            comps.append({"name_ja": "たまねぎ", "name_en": "Onion", "estimated_grams": 40.0, "confidence": "high"})
        elif "中華" in name:
            comps.append({"name_ja": "豚肉", "name_en": "Pork", "estimated_grams": 40.0, "confidence": "high"})
            comps.append({"name_ja": "キャベツ", "name_en": "Vegetables", "estimated_grams": 50.0, "confidence": "high"})
            comps.append({"name_ja": "植物油", "name_en": "Cooking Oil", "estimated_grams": 10.0, "confidence": "high"})
        elif "麻婆" in name:
            comps.append({"name_ja": "絹ごし豆腐", "name_en": "Tofu", "estimated_grams": 80.0, "confidence": "high"})
            comps.append({"name_ja": "豚肉", "name_en": "Minced Pork", "estimated_grams": 35.0, "confidence": "high"})
            comps.append({"name_ja": "植物油", "name_en": "Chili Oil", "estimated_grams": 10.0, "confidence": "high"})
        elif "から揚げ" in name or "唐揚げ" in name or "チキン" in name or "竜田" in name:
            comps.append({"name_ja": "から揚げ", "name_en": "Fried Chicken", "estimated_grams": 90.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "牛肉", "name_en": "Savory Meat", "estimated_grams": 75.0, "confidence": "medium"})
            comps.append({"name_ja": "たまねぎ", "name_en": "Onion", "estimated_grams": 35.0, "confidence": "medium"})

        # Accompanying items (mini noodles or miso soup)
        if any(k in name for k in ("そば付", "そばつき", "うどん付", "うどんつき")):
            comps.append({"name_ja": "そば ゆで" if "そば" in name else "うどん ゆで", "name_en": "Side Noodles", "estimated_grams": 100.0, "confidence": "high"})
            comps.append({"name_ja": "めんつゆ", "name_en": "Noodle Broth", "estimated_grams": 100.0, "confidence": "high"})
        elif any(k in name for k in ("モーニング", "セット", "定食", "御膳", "汁", "朝")) or has_explicit_soup:
            comps.append({"name_ja": "みそ", "name_en": "Miso Paste", "estimated_grams": 15.0, "confidence": "high"})
            comps.append({"name_ja": "だし汁", "name_en": "Dashi Broth", "estimated_grams": 150.0, "confidence": "high"})
            comps.append({"name_ja": "絹ごし豆腐", "name_en": "Tofu", "estimated_grams": 20.0, "confidence": "high"})

    # 2. Teishoku, Bento, Gozen & Zen (定食・御膳・弁当・膳 - Complete meal: Check BEFORE individual sides!)
    elif any(k in name for k in ("定食", "御膳", "弁当", "膳")):
        if not is_tanpin:
            rice_g = get_rice_grams(200.0)
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})
            comps.append({"name_ja": "みそ", "name_en": "Miso Paste", "estimated_grams": 15.0, "confidence": "high"})
            comps.append({"name_ja": "だし汁", "name_en": "Dashi Broth", "estimated_grams": 150.0, "confidence": "high"})
            comps.append({"name_ja": "絹ごし豆腐", "name_en": "Tofu", "estimated_grams": 20.0, "confidence": "high"})
        comps.append({"name_ja": "キャベツ", "name_en": "Shredded Cabbage", "estimated_grams": 50.0, "confidence": "high"})

        if any(k in name for k in ("から揚げ", "唐揚げ", "竜田")):
            comps.append({"name_ja": "から揚げ", "name_en": "Fried Chicken", "estimated_grams": 130.0, "confidence": "high"})
        elif "チキン南蛮" in name:
            comps.append({"name_ja": "から揚げ", "name_en": "Chicken Nanban", "estimated_grams": 120.0, "confidence": "high"})
            comps.append({"name_ja": "マヨネーズ", "name_en": "Tartar Sauce", "estimated_grams": 20.0, "confidence": "high"})
        elif any(k in name for k in ("生姜焼き", "生姜焼", "豚生姜")):
            comps.append({"name_ja": "豚肉", "name_en": "Ginger Pork", "estimated_grams": 110.0, "confidence": "high"})
            comps.append({"name_ja": "たまねぎ", "name_en": "Onion", "estimated_grams": 30.0, "confidence": "high"})
        elif any(k in name for k in ("とんかつ", "豚カツ", "カツ", "かつ")):
            comps.append({"name_ja": "とんかつ", "name_en": "Tonkatsu", "estimated_grams": 130.0, "confidence": "high"})
        elif any(k in name for k in ("さば", "鯖", "あじ", "鯵", "ほっけ", "鮭", "サーモン", "金目鯛", "魚", "刺身")):
            if any(k in name for k in ("フライ", "揚")):
                comps.append({"name_ja": "さば", "name_en": "Fried Fish", "estimated_grams": 90.0, "confidence": "high"})
                comps.append({"name_ja": "植物油", "name_en": "Frying Oil", "estimated_grams": 12.0, "confidence": "high"})
            elif "刺身" in name or "生" in name:
                comps.append({"name_ja": "まぐろ", "name_en": "Sashimi", "estimated_grams": 80.0, "confidence": "high"})
            else:
                comps.append({"name_ja": "さば", "name_en": "Grilled Fish", "estimated_grams": 90.0, "confidence": "high"})
        elif "ハンバーグ" in name:
            comps.append({"name_ja": "ハンバーグ", "name_en": "Hamburg Patty", "estimated_grams": 130.0, "confidence": "high"})
        elif any(k in name for k in ("牛", "ステーキ", "焼肉")):
            comps.append({"name_ja": "牛肉", "name_en": "Beef", "estimated_grams": 100.0, "confidence": "high"})
        elif "餃子" in name or "ギョーザ" in name:
            comps.append({"name_ja": "餃子", "name_en": "Gyoza", "estimated_grams": 120.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "豚肉", "name_en": "Main Dish Meat", "estimated_grams": 100.0, "confidence": "medium"})

    # 3. Omurice, Pilaf, Risotto, Doria, Curry & Fried Rice
    elif "オムライス" in name:
        comps.append({"name_ja": "ご飯", "name_en": "Chicken Rice", "estimated_grams": 200.0, "confidence": "high"})
        comps.append({"name_ja": "卵", "name_en": "Omelette Egg", "estimated_grams": 100.0, "confidence": "high"})
        comps.append({"name_ja": "鶏肉", "name_en": "Chicken", "estimated_grams": 35.0, "confidence": "high"})
        comps.append({"name_ja": "ケチャップ", "name_en": "Ketchup", "estimated_grams": 25.0, "confidence": "high"})
        comps.append({"name_ja": "バター", "name_en": "Butter", "estimated_grams": 8.0, "confidence": "high"})
        if "ビーフシチュー" in name or "シチュー" in name:
            comps.append({"name_ja": "牛肉", "name_en": "Stewed Beef", "estimated_grams": 40.0, "confidence": "high"})
            comps.append({"name_ja": "デミグラスソース", "name_en": "Demiglace", "estimated_grams": 40.0, "confidence": "high"})

    elif "ピラフ" in name:
        comps.append({"name_ja": "ご飯", "name_en": "Pilaf Rice", "estimated_grams": 220.0, "confidence": "high"})
        comps.append({"name_ja": "バター", "name_en": "Butter", "estimated_grams": 10.0, "confidence": "high"})
        comps.append({"name_ja": "たまねぎ", "name_en": "Onion", "estimated_grams": 25.0, "confidence": "high"})
        if any(k in name for k in ("チキン", "タンドリー", "鶏")):
            comps.append({"name_ja": "から揚げ", "name_en": "Tandoori Chicken", "estimated_grams": 85.0, "confidence": "high"})
        elif any(k in name for k in ("エビ", "えび", "海老", "シーフード")):
            comps.append({"name_ja": "えび", "name_en": "Shrimp", "estimated_grams": 40.0, "confidence": "high"})

    elif "リゾット" in name:
        comps.append({"name_ja": "ご飯", "name_en": "Risotto Rice", "estimated_grams": 180.0, "confidence": "high"})
        comps.append({"name_ja": "チーズ", "name_en": "Cheese", "estimated_grams": 30.0, "confidence": "high"})
        comps.append({"name_ja": "植物油", "name_en": "Olive Oil", "estimated_grams": 10.0, "confidence": "high"})

    elif "ドリア" in name:
        comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": 160.0, "confidence": "high"})
        comps.append({"name_ja": "チーズ", "name_en": "Cheese", "estimated_grams": 30.0, "confidence": "high"})
        comps.append({"name_ja": "生クリーム", "name_en": "White Sauce", "estimated_grams": 50.0, "confidence": "high"})
        if "ミラノ" in name or "ミート" in name or "ボロネーゼ" in name:
            comps.append({"name_ja": "ミートソース", "name_en": "Meat Sauce", "estimated_grams": 50.0, "confidence": "high"})
        if "エビ" in name or "えび" in name or "海老" in name:
            comps.append({"name_ja": "えび", "name_en": "Shrimp", "estimated_grams": 35.0, "confidence": "high"})
        if "チキン" in name or "鶏" in name:
            comps.append({"name_ja": "蒸し鶏", "name_en": "Chicken", "estimated_grams": 45.0, "confidence": "high"})
        if "卵" in name or "たまご" in name or "温玉" in name:
            comps.append({"name_ja": "卵", "name_en": "Egg", "estimated_grams": 50.0, "confidence": "high"})

    elif "カレー" in name and not any(k in name for k in ("うどん", "そば", "らーめん", "ラーメン", "パン", "ピザ")):
        rice_g = get_rice_grams(250.0)
        comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})
        comps.append({"name_ja": "カレー ルウ", "name_en": "Curry Sauce", "estimated_grams": 180.0, "confidence": "high"})
        if "カツ" in name or "かつ" in name:
            comps.append({"name_ja": "とんかつ", "name_en": "Pork Cutlet", "estimated_grams": 120.0, "confidence": "high"})
        elif "チキン" in name or "鶏" in name:
            comps.append({"name_ja": "鶏肉", "name_en": "Chicken", "estimated_grams": 50.0, "confidence": "high"})
        elif "ビーフ" in name or "牛" in name:
            comps.append({"name_ja": "牛肉", "name_en": "Beef", "estimated_grams": 45.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "豚肉", "name_en": "Pork", "estimated_grams": 40.0, "confidence": "medium"})

    elif "チャーハン" in name or "炒飯" in name:
        rice_g = get_rice_grams(240.0)
        comps.append({"name_ja": "ご飯", "name_en": "Rice", "estimated_grams": rice_g, "confidence": "high"})
        comps.append({"name_ja": "卵", "name_en": "Egg", "estimated_grams": 50.0, "confidence": "high"})
        comps.append({"name_ja": "豚肉 焼き豚", "name_en": "Roast Pork", "estimated_grams": 35.0, "confidence": "high"})
        comps.append({"name_ja": "植物油", "name_en": "Cooking Oil", "estimated_grams": 12.0, "confidence": "high"})

    # 4. Stews, Hotpots & Specialized Cookery (スンドゥブ・チゲ・回鍋肉・ビーフシチュー)
    elif any(k in name for k in ("スンドゥブ", "チゲ")):
        comps.append({"name_ja": "絹ごし豆腐", "name_en": "Tofu", "estimated_grams": 150.0, "confidence": "high"})
        comps.append({"name_ja": "豚肉", "name_en": "Pork", "estimated_grams": 40.0, "confidence": "high"})
        comps.append({"name_ja": "卵", "name_en": "Egg", "estimated_grams": 50.0, "confidence": "high"})
        comps.append({"name_ja": "植物油", "name_en": "Chili Oil", "estimated_grams": 8.0, "confidence": "high"})
        if has_explicit_rice:
            rice_g = 120.0 if any(k in name for k in ('半', '小', 'ミニ')) else 200.0
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

    elif "ビーフシチュー" in name or "シチュー" in name:
        comps.append({"name_ja": "牛肉", "name_en": "Beef", "estimated_grams": 100.0, "confidence": "high"})
        comps.append({"name_ja": "デミグラスソース", "name_en": "Demiglace Sauce", "estimated_grams": 120.0, "confidence": "high"})
        comps.append({"name_ja": "じゃがいも", "name_en": "Potato", "estimated_grams": 50.0, "confidence": "high"})
        comps.append({"name_ja": "にんじん", "name_en": "Carrot", "estimated_grams": 30.0, "confidence": "high"})
        if has_explicit_rice:
            rice_g = 120.0 if any(k in name for k in ('半', '小', 'ミニ')) else 200.0
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

    elif "回鍋肉" in name:
        comps.append({"name_ja": "豚肉", "name_en": "Pork", "estimated_grams": 80.0, "confidence": "high"})
        comps.append({"name_ja": "キャベツ", "name_en": "Cabbage", "estimated_grams": 90.0, "confidence": "high"})
        comps.append({"name_ja": "みそ", "name_en": "Sweet Bean Sauce", "estimated_grams": 20.0, "confidence": "high"})
        comps.append({"name_ja": "植物油", "name_en": "Cooking Oil", "estimated_grams": 12.0, "confidence": "high"})
        if has_explicit_rice or "定食" in name or "セット" in name:
            rice_g = 120.0 if any(k in name for k in ('半', '小', 'ミニ')) else 200.0
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

    # 5. Hamburg Steak, Steaks & Western Meats (洋食・肉料理)
    elif "ハンバーグ" in name:
        comps.append({"name_ja": "ハンバーグ", "name_en": "Hamburg Patty", "estimated_grams": 140.0, "confidence": "high"})
        comps.append({"name_ja": "コーン", "name_en": "Corn Garnish", "estimated_grams": 20.0, "confidence": "high"})
        comps.append({"name_ja": "フライドポテト", "name_en": "Potato Garnish", "estimated_grams": 30.0, "confidence": "high"})
        if "和風" in name or "おろし" in name:
            comps.append({"name_ja": "大根", "name_en": "Grated Daikon", "estimated_grams": 30.0, "confidence": "high"})
            comps.append({"name_ja": "しょうゆ", "name_en": "Soy Sauce Glaze", "estimated_grams": 15.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "デミグラスソース", "name_en": "Demiglace Sauce", "estimated_grams": 30.0, "confidence": "high"})
        if "チーズ" in name:
            comps.append({"name_ja": "チーズ", "name_en": "Cheese", "estimated_grams": 25.0, "confidence": "high"})
        if "エッグ" in name or "目玉焼き" in name or "たまご" in name:
            comps.append({"name_ja": "卵", "name_en": "Egg", "estimated_grams": 50.0, "confidence": "high"})
        if has_explicit_rice:
            rice_g = 120.0 if any(k in name for k in ('半', '小', 'ミニ')) else 200.0
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

    elif "ステーキ" in name:
        comps.append({"name_ja": "牛肉", "name_en": "Beef Steak", "estimated_grams": 160.0, "confidence": "high"})
        comps.append({"name_ja": "しょうゆ", "name_en": "Steak Sauce", "estimated_grams": 25.0, "confidence": "high"})
        comps.append({"name_ja": "コーン", "name_en": "Corn Garnish", "estimated_grams": 20.0, "confidence": "high"})
        comps.append({"name_ja": "フライドポテト", "name_en": "Potato Garnish", "estimated_grams": 30.0, "confidence": "high"})
        if has_explicit_rice:
            rice_g = 120.0 if any(k in name for k in ('半', '小', 'ミニ')) else 200.0
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

    # 6. Ramen, Soba & Udon (麺類)
    elif any(k in name for k in ("ラーメン", "らーめん", "中華そば", "つけ麺")):
        soup_type = "みそ ラーメン スープ" if ("味噌" in name or "みそ" in name) else "しょうゆ ラーメン スープ"
        comps.append({"name_ja": "中華麺 ゆで", "name_en": "Boiled Chinese Noodles", "estimated_grams": 220.0, "confidence": "high"})
        comps.append({"name_ja": soup_type, "name_en": "Ramen Broth", "estimated_grams": 300.0, "confidence": "high"})
        comps.append({"name_ja": "豚肉 焼き豚", "name_en": "Roast Pork Chashu", "estimated_grams": 30.0, "confidence": "high"})
        comps.append({"name_ja": "メンマ", "name_en": "Menma bamboo shoots", "estimated_grams": 20.0, "confidence": "high"})
        comps.append({"name_ja": "ねぎ", "name_en": "Green Onion", "estimated_grams": 15.0, "confidence": "high"})
        comps.append({"name_ja": "のり", "name_en": "Nori Seaweed", "estimated_grams": 2.0, "confidence": "high"})

        if "ねぎ" in name:
            comps.append({"name_ja": "ねぎ", "name_en": "Extra Green Onion", "estimated_grams": 45.0, "confidence": "high"})
        if "背脂" in name:
            comps.append({"name_ja": "豚肉 脂身", "name_en": "Pork Back Fat", "estimated_grams": 25.0, "confidence": "high"})
        if "チャーシュー" in name:
            comps.append({"name_ja": "豚肉 焼き豚", "name_en": "Extra Chashu", "estimated_grams": 50.0, "confidence": "high"})
        if "玉子" in name or "たまご" in name or "味玉" in name:
            comps.append({"name_ja": "鶏卵 ゆで", "name_en": "Boiled Egg", "estimated_grams": 55.0, "confidence": "high"})
        if "半カレー" in name:
            comps.append({"name_ja": "ご飯", "name_en": "Half Curry Rice", "estimated_grams": 100.0, "confidence": "high"})
            comps.append({"name_ja": "カレー ルウ", "name_en": "Curry Sauce", "estimated_grams": 70.0, "confidence": "high"})
        elif "半ライス" in name or "半ごはん" in name:
            comps.append({"name_ja": "ご飯", "name_en": "Half Steamed Rice", "estimated_grams": 100.0, "confidence": "high"})
        elif "ライス" in name or "ご飯" in name or has_explicit_rice:
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": 180.0, "confidence": "high"})
        elif "チャーハン" in name or "炒飯" in name:
            comps.append({"name_ja": "ご飯", "name_en": "Fried Rice", "estimated_grams": 150.0, "confidence": "high"})
            comps.append({"name_ja": "卵", "name_en": "Egg", "estimated_grams": 25.0, "confidence": "high"})
        elif "餃子" in name or "ギョーザ" in name:
            comps.append({"name_ja": "餃子", "name_en": "Gyoza Side", "estimated_grams": 70.0, "confidence": "high"})

    elif "うどん" in name:
        comps.append({"name_ja": "うどん ゆで", "name_en": "Boiled Udon", "estimated_grams": 250.0, "confidence": "high"})
        comps.append({"name_ja": "めんつゆ", "name_en": "Noodle Broth", "estimated_grams": 250.0, "confidence": "high"})
        comps.append({"name_ja": "ねぎ", "name_en": "Green Onion", "estimated_grams": 10.0, "confidence": "high"})
        if "きつね" in name:
            comps.append({"name_ja": "油揚げ", "name_en": "Fried Tofu", "estimated_grams": 35.0, "confidence": "high"})
        if "天ぷら" in name or "天" in name:
            comps.append({"name_ja": "えび", "name_en": "Tempura", "estimated_grams": 65.0, "confidence": "high"})
        if "肉" in name:
            comps.append({"name_ja": "牛肉", "name_en": "Simmered Beef", "estimated_grams": 60.0, "confidence": "high"})
        if has_explicit_rice:
            rice_g = 100.0 if any(k in name for k in ('半', '小', 'ミニ')) else 150.0
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

    elif "そば" in name:
        comps.append({"name_ja": "そば ゆで", "name_en": "Boiled Soba", "estimated_grams": 220.0, "confidence": "high"})
        comps.append({"name_ja": "めんつゆ", "name_en": "Soba Broth", "estimated_grams": 250.0, "confidence": "high"})
        comps.append({"name_ja": "ねぎ", "name_en": "Green Onion", "estimated_grams": 10.0, "confidence": "high"})
        if "天ぷら" in name or "天" in name:
            comps.append({"name_ja": "えび", "name_en": "Tempura", "estimated_grams": 65.0, "confidence": "high"})
        if has_explicit_rice:
            rice_g = 100.0 if any(k in name for k in ('半', '小', 'ミニ')) else 150.0
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

    # 7. Sushi & Sashimi (にぎり、軍艦、巻き寿司、海鮮)
    elif any(k in name for k in ("寿司", "すし", "スシ", "にぎり", "握り", "軍艦", "手巻", "刺身", "造り")) or (
        shop_name and any(s in shop_name for s in ("寿司", "すし", "スシ", "回転")) and any(
            f in name for f in ("まぐろ", "マグロ", "中とろ", "大とろ", "サーモン", "いくら", "えび", "海老", "いか", "たこ", "うなぎ", "穴子", "たい", "ほたて", "ぶり", "はまち", "さば", "たまご", "玉子")
        )
    ):
        is_sashimi = "刺身" in name or "造り" in name
        is_gunkan = "軍艦" in name
        is_maki = "巻" in name or "手巻" in name
        
        # Rice base
        if not is_sashimi:
            rice_g = 35.0 if is_gunkan else (60.0 if is_maki else 40.0)
            comps.append({"name_ja": "ご飯", "name_en": "Sushi Rice", "estimated_grams": rice_g, "confidence": "high"})
            if is_gunkan or is_maki:
                comps.append({"name_ja": "のり", "name_en": "Nori Seaweed", "estimated_grams": 1.5, "confidence": "high"})
        
        # Toppings & Protein
        seafood_g = 70.0 if is_sashimi else 25.0
        if "牛" in name or "カルビ" in name:
            comps.append({"name_ja": "牛肉", "name_en": "Beef Topping", "estimated_grams": 25.0, "confidence": "high"})
        elif "豚" in name:
            comps.append({"name_ja": "豚肉", "name_en": "Pork Topping", "estimated_grams": 25.0, "confidence": "high"})
        elif "ハンバーグ" in name or "ミートボール" in name:
            comps.append({"name_ja": "ハンバーグ", "name_en": "Hamburg", "estimated_grams": 30.0, "confidence": "high"})
        elif "ツナ" in name:
            comps.append({"name_ja": "まぐろ 缶詰", "name_en": "Tuna", "estimated_grams": 20.0, "confidence": "high"})
            comps.append({"name_ja": "マヨネーズ", "name_en": "Mayonnaise", "estimated_grams": 5.0, "confidence": "high"})
        elif "納豆" in name:
            comps.append({"name_ja": "納豆", "name_en": "Natto", "estimated_grams": 25.0, "confidence": "high"})
        elif "コーン" in name:
            comps.append({"name_ja": "コーン", "name_en": "Corn", "estimated_grams": 25.0, "confidence": "high"})
            comps.append({"name_ja": "マヨネーズ", "name_en": "Mayonnaise", "estimated_grams": 5.0, "confidence": "high"})
        elif "生ハム" in name:
            comps.append({"name_ja": "生ハム", "name_en": "Prosciutto", "estimated_grams": 20.0, "confidence": "high"})
        elif "中とろ" in name or "大とろ" in name or "トロ" in name or "とろ" in name:
            comps.append({"name_ja": "中とろ", "name_en": "Fatty Tuna", "estimated_grams": seafood_g, "confidence": "high"})
        elif "まぐろ" in name or "マグロ" in name or "赤身" in name:
            comps.append({"name_ja": "まぐろ", "name_en": "Tuna", "estimated_grams": seafood_g, "confidence": "high"})
        elif "サーモン" in name or "鮭" in name:
            comps.append({"name_ja": "サーモン", "name_en": "Salmon", "estimated_grams": seafood_g, "confidence": "high"})
        elif "いくら" in name:
            comps.append({"name_ja": "いくら", "name_en": "Salmon Roe", "estimated_grams": 20.0, "confidence": "high"})
        elif "えび" in name or "エビ" in name or "海老" in name:
            comps.append({"name_ja": "えび", "name_en": "Shrimp", "estimated_grams": seafood_g, "confidence": "high"})
        elif "いか" in name or "イカ" in name:
            comps.append({"name_ja": "いか", "name_en": "Squid", "estimated_grams": seafood_g, "confidence": "high"})
        elif "たこ" in name or "タコ" in name:
            comps.append({"name_ja": "たこ", "name_en": "Octopus", "estimated_grams": seafood_g, "confidence": "high"})
        elif "うなぎ" in name or "鰻" in name:
            comps.append({"name_ja": "うなぎ", "name_en": "Eel", "estimated_grams": seafood_g, "confidence": "high"})
        elif "穴子" in name or "あなご" in name:
            comps.append({"name_ja": "穴子", "name_en": "Sea Eel", "estimated_grams": seafood_g, "confidence": "high"})
        elif "ほたて" in name or "ホタテ" in name:
            comps.append({"name_ja": "ほたて", "name_en": "Scallop", "estimated_grams": seafood_g, "confidence": "high"})
        elif "ぶり" in name or "はまち" in name or "ハマチ" in name:
            comps.append({"name_ja": "ぶり", "name_en": "Yellowtail", "estimated_grams": seafood_g, "confidence": "high"})
        elif "さば" in name or "サバ" in name:
            comps.append({"name_ja": "さば", "name_en": "Mackerel", "estimated_grams": seafood_g, "confidence": "high"})
        elif "玉子" in name or "たまご" in name or "エッグ" in name:
            comps.append({"name_ja": "卵", "name_en": "Egg", "estimated_grams": 35.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "まぐろ", "name_en": "Fish Topping", "estimated_grams": seafood_g, "confidence": "medium"})
        
        # Accompaniments
        if "アボカド" in name:
            comps.append({"name_ja": "アボカド", "name_en": "Avocado", "estimated_grams": 15.0, "confidence": "high"})
        if "マヨ" in name and not any(c["name_ja"] == "マヨネーズ" for c in comps):
            comps.append({"name_ja": "マヨネーズ", "name_en": "Mayonnaise", "estimated_grams": 5.0, "confidence": "high"})
        if "チーズ" in name:
            comps.append({"name_ja": "チーズ", "name_en": "Cheese", "estimated_grams": 10.0, "confidence": "high"})

    # 8. Pizza, Pasta, Doria & Gratin (ピザ・パスタ・ドリア・グラタン)
    elif "ピザ" in name or "ピッツァ" in name:
        comps.append({"name_ja": "ピザ生地", "name_en": "Pizza Crust", "estimated_grams": 130.0, "confidence": "high"})
        comps.append({"name_ja": "チーズ", "name_en": "Cheese", "estimated_grams": 45.0, "confidence": "high"})
        comps.append({"name_ja": "トマトソース", "name_en": "Tomato Sauce", "estimated_grams": 30.0, "confidence": "high"})
        if "ソーセージ" in name or "サラミ" in name or "チョリソー" in name:
            comps.append({"name_ja": "ソーセージ", "name_en": "Sausage", "estimated_grams": 30.0, "confidence": "high"})
        elif "ベーコン" in name:
            comps.append({"name_ja": "ベーコン", "name_en": "Bacon", "estimated_grams": 25.0, "confidence": "high"})
        elif "シーフード" in name or "エビ" in name or "えび" in name:
            comps.append({"name_ja": "えび", "name_en": "Shrimp", "estimated_grams": 30.0, "confidence": "high"})
        elif "コーン" in name:
            comps.append({"name_ja": "コーン", "name_en": "Sweet Corn", "estimated_grams": 30.0, "confidence": "high"})
            comps.append({"name_ja": "マヨネーズ", "name_en": "Mayonnaise", "estimated_grams": 12.0, "confidence": "high"})

    elif any(k in name for k in ("パスタ", "スパゲッティ", "ボロネーゼ", "カルボナーラ", "ペペロンチーノ")):
        comps.append({"name_ja": "パスタ", "name_en": "Boiled Pasta", "estimated_grams": 200.0, "confidence": "high"})
        if "ミートソース" in name or "ボロネーゼ" in name:
            comps.append({"name_ja": "ミートソース", "name_en": "Meat Sauce", "estimated_grams": 120.0, "confidence": "high"})
        elif "カルボナーラ" in name:
            comps.append({"name_ja": "生クリーム", "name_en": "Cream", "estimated_grams": 40.0, "confidence": "high"})
            comps.append({"name_ja": "ベーコン", "name_en": "Bacon", "estimated_grams": 25.0, "confidence": "high"})
            comps.append({"name_ja": "チーズ", "name_en": "Cheese", "estimated_grams": 15.0, "confidence": "high"})
        elif "たらこ" in name or "明太子" in name:
            comps.append({"name_ja": "たらこ", "name_en": "Tarako Caviar", "estimated_grams": 25.0, "confidence": "high"})
            comps.append({"name_ja": "バター", "name_en": "Butter", "estimated_grams": 10.0, "confidence": "high"})
        elif "ナポリタン" in name:
            comps.append({"name_ja": "ケチャップ", "name_en": "Ketchup", "estimated_grams": 35.0, "confidence": "high"})
            comps.append({"name_ja": "ソーセージ", "name_en": "Sausage", "estimated_grams": 25.0, "confidence": "high"})
        elif "ペペロンチーノ" in name:
            comps.append({"name_ja": "植物油", "name_en": "Olive Oil", "estimated_grams": 15.0, "confidence": "high"})
            comps.append({"name_ja": "にんにく", "name_en": "Garlic", "estimated_grams": 5.0, "confidence": "high"})
            if "温玉" in name or "卵" in name or "たまご" in name:
                comps.append({"name_ja": "卵", "name_en": "Soft Boiled Egg", "estimated_grams": 50.0, "confidence": "high"})
        elif "イカスミ" in name:
            comps.append({"name_ja": "いか", "name_en": "Squid", "estimated_grams": 35.0, "confidence": "high"})
            comps.append({"name_ja": "トマトソース", "name_en": "Tomato Sauce", "estimated_grams": 50.0, "confidence": "high"})
            comps.append({"name_ja": "植物油", "name_en": "Olive Oil", "estimated_grams": 10.0, "confidence": "high"})
        elif "ボンゴレ" in name or "あさり" in name:
            comps.append({"name_ja": "あさり", "name_en": "Clams", "estimated_grams": 50.0, "confidence": "high"})
            comps.append({"name_ja": "植物油", "name_en": "Olive Oil", "estimated_grams": 10.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "トマトソース", "name_en": "Tomato Sauce", "estimated_grams": 100.0, "confidence": "medium"})

    elif "グラタン" in name:
        comps.append({"name_ja": "パスタ", "name_en": "Macaroni", "estimated_grams": 100.0, "confidence": "high"})
        comps.append({"name_ja": "生クリーム", "name_en": "White Sauce", "estimated_grams": 70.0, "confidence": "high"})
        comps.append({"name_ja": "チーズ", "name_en": "Cheese", "estimated_grams": 30.0, "confidence": "high"})
        if "エビ" in name or "えび" in name or "海老" in name:
            comps.append({"name_ja": "えび", "name_en": "Shrimp", "estimated_grams": 35.0, "confidence": "high"})
        elif "チキン" in name or "鶏" in name:
            comps.append({"name_ja": "蒸し鶏", "name_en": "Chicken", "estimated_grams": 45.0, "confidence": "high"})

    # 9. Burgers & Sandwiches (バーガー・サンド)
    elif "バーガー" in name or "サンド" in name:
        if "ライス" in name:
            comps.append({"name_ja": "ご飯", "name_en": "Rice Bun", "estimated_grams": 120.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "パン", "name_en": "Burger Bun", "estimated_grams": 75.0, "confidence": "high"})
        
        if "フィッシュ" in name:
            comps.append({"name_ja": "たら", "name_en": "Fish Patty", "estimated_grams": 75.0, "confidence": "high"})
        elif "チキン" in name:
            comps.append({"name_ja": "から揚げ", "name_en": "Chicken Patty", "estimated_grams": 85.0, "confidence": "high"})
        elif "エビ" in name or "海老" in name:
            comps.append({"name_ja": "えび", "name_en": "Shrimp Patty", "estimated_grams": 75.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "ハンバーグ", "name_en": "Beef Patty", "estimated_grams": 90.0, "confidence": "high"})
        comps.append({"name_ja": "キャベツ", "name_en": "Lettuce", "estimated_grams": 20.0, "confidence": "high"})
        comps.append({"name_ja": "マヨネーズ", "name_en": "Sauce", "estimated_grams": 10.0, "confidence": "high"})
        if "チーズ" in name:
            comps.append({"name_ja": "チーズ", "name_en": "Cheese", "estimated_grams": 18.0, "confidence": "high"})

    # 10. Salads (サラダ)
    elif "サラダ" in name:
        if "ポテト" in name:
            comps.append({"name_ja": "じゃがいも", "name_en": "Potato", "estimated_grams": 80.0, "confidence": "high"})
            comps.append({"name_ja": "マヨネーズ", "name_en": "Mayonnaise", "estimated_grams": 20.0, "confidence": "high"})
            comps.append({"name_ja": "キャベツ", "name_en": "Vegetables", "estimated_grams": 30.0, "confidence": "high"})
        else:
            comps.append({"name_ja": "キャベツ", "name_en": "Salad Greens", "estimated_grams": 70.0, "confidence": "high"})
            comps.append({"name_ja": "トマト", "name_en": "Tomato", "estimated_grams": 30.0, "confidence": "high"})
            comps.append({"name_ja": "調合油", "name_en": "Dressing", "estimated_grams": 15.0, "confidence": "high"})

            if "チキン" in name or "蒸し鶏" in name or "鶏" in name:
                comps.append({"name_ja": "蒸し鶏", "name_en": "Steamed Chicken Breast", "estimated_grams": 65.0, "confidence": "high"})
            elif "小エビ" in name or "えび" in name or "エビ" in name or "海老" in name:
                comps.append({"name_ja": "小エビ", "name_en": "Baby Shrimp", "estimated_grams": 40.0, "confidence": "high"})
            elif "ツナ" in name or "シーチキン" in name:
                comps.append({"name_ja": "まぐろ 缶詰", "name_en": "Tuna", "estimated_grams": 35.0, "confidence": "high"})
            elif "わかめ" in name or "海藻" in name:
                comps.append({"name_ja": "わかめ", "name_en": "Wakame Seaweed", "estimated_grams": 35.0, "confidence": "high"})
            elif "シーザー" in name:
                comps.append({"name_ja": "ベーコン", "name_en": "Bacon", "estimated_grams": 15.0, "confidence": "high"})
                comps.append({"name_ja": "チーズ", "name_en": "Parmesan Cheese", "estimated_grams": 15.0, "confidence": "high"})
            elif "モッツァレラ" in name or "カプレーゼ" in name:
                comps.append({"name_ja": "チーズ", "name_en": "Mozzarella Cheese", "estimated_grams": 40.0, "confidence": "high"})
            elif "生ハム" in name:
                comps.append({"name_ja": "生ハム", "name_en": "Prosciutto", "estimated_grams": 25.0, "confidence": "high"})
            elif "とうふ" in name or "豆腐" in name:
                comps.append({"name_ja": "絹ごし豆腐", "name_en": "Tofu", "estimated_grams": 80.0, "confidence": "high"})
            elif "コーン" in name:
                comps.append({"name_ja": "コーン", "name_en": "Sweet Corn", "estimated_grams": 35.0, "confidence": "high"})
            elif "たまご" in name or "玉子" in name or "卵" in name or "コブ" in name:
                comps.append({"name_ja": "卵", "name_en": "Boiled Egg", "estimated_grams": 50.0, "confidence": "high"})

    # 11. Sides, Soups & Appetizers (サイド・スープ・前菜)
    elif "コーンスープ" in name or "コーンクリームスープ" in name or "ポタージュ" in name:
        comps.append({"name_ja": "コーンクリームスープ", "name_en": "Corn Potage Soup", "estimated_grams": 160.0, "confidence": "high"})

    elif "ミネストローネ" in name:
        comps.append({"name_ja": "トマト", "name_en": "Tomato Broth", "estimated_grams": 80.0, "confidence": "high"})
        comps.append({"name_ja": "キャベツ", "name_en": "Vegetables", "estimated_grams": 40.0, "confidence": "high"})
        comps.append({"name_ja": "ベーコン", "name_en": "Bacon", "estimated_grams": 15.0, "confidence": "high"})

    elif "クラムチャウダー" in name:
        comps.append({"name_ja": "牛乳", "name_en": "Cream Soup", "estimated_grams": 100.0, "confidence": "high"})
        comps.append({"name_ja": "あさり", "name_en": "Clams", "estimated_grams": 30.0, "confidence": "high"})
        comps.append({"name_ja": "じゃがいも", "name_en": "Potato", "estimated_grams": 30.0, "confidence": "high"})

    elif "辛味チキン" in name:
        comps.append({"name_ja": "鶏肉", "name_en": "Spicy Bone-in Chicken Wing", "estimated_grams": 120.0, "confidence": "high"})
        comps.append({"name_ja": "調合油", "name_en": "Cooking Oil", "estimated_grams": 10.0, "confidence": "high"})

    elif "ポップコーンシュリンプ" in name:
        comps.append({"name_ja": "えび", "name_en": "Crispy Shrimp", "estimated_grams": 60.0, "confidence": "high"})
        comps.append({"name_ja": "調合油", "name_en": "Frying Oil", "estimated_grams": 15.0, "confidence": "high"})
        comps.append({"name_ja": "小麦粉", "name_en": "Batter", "estimated_grams": 15.0, "confidence": "high"})

    elif "エスカルゴ" in name:
        comps.append({"name_ja": "あさり", "name_en": "Escargot Shellfish", "estimated_grams": 40.0, "confidence": "high"})
        comps.append({"name_ja": "バター", "name_en": "Garlic Butter", "estimated_grams": 15.0, "confidence": "high"})

    elif "フォッカ" in name or "フォカッチャ" in name:
        comps.append({"name_ja": "パン", "name_en": "Focaccia Bread", "estimated_grams": 65.0, "confidence": "high"})
        comps.append({"name_ja": "植物油", "name_en": "Olive Oil", "estimated_grams": 6.0, "confidence": "high"})

    elif "ポテト" in name or "ポテトフライ" in name:
        comps.append({"name_ja": "フライドポテト", "name_en": "French Fries", "estimated_grams": 110.0, "confidence": "high"})

    elif "から揚げ" in name or "唐揚げ" in name:
        comps.append({"name_ja": "から揚げ", "name_en": "Fried Chicken", "estimated_grams": 130.0, "confidence": "high"})

    elif "餃子" in name or "ギョーザ" in name:
        comps.append({"name_ja": "餃子", "name_en": "Pan-fried Gyoza", "estimated_grams": 120.0, "confidence": "high"})

    elif "ソーセージ" in name or "チョリソー" in name:
        comps.append({"name_ja": "ソーセージ", "name_en": "Sausage", "estimated_grams": 75.0, "confidence": "high"})

    elif "枝豆" in name:
        comps.append({"name_ja": "枝豆", "name_en": "Edamame", "estimated_grams": 70.0, "confidence": "high"})

    elif "冷奴" in name:
        comps.append({"name_ja": "絹ごし豆腐", "name_en": "Tofu", "estimated_grams": 150.0, "confidence": "high"})
        comps.append({"name_ja": "しょうゆ", "name_en": "Soy Sauce", "estimated_grams": 10.0, "confidence": "high"})

    elif "納豆" in name:
        comps.append({"name_ja": "納豆", "name_en": "Natto", "estimated_grams": 50.0, "confidence": "high"})

    elif "みそ汁" in name or "味噌汁" in name:
        comps.append({"name_ja": "みそ", "name_en": "Miso Paste", "estimated_grams": 15.0, "confidence": "high"})
        comps.append({"name_ja": "だし汁", "name_en": "Dashi Broth", "estimated_grams": 150.0, "confidence": "high"})
        comps.append({"name_ja": "絹ごし豆腐", "name_en": "Tofu", "estimated_grams": 20.0, "confidence": "high"})

    # 12. Drinks & Desserts (ドリンク・デザート)
    elif "ビール" in name:
        comps.append({"name_ja": "ビール", "name_en": "Draft Beer", "estimated_grams": 350.0, "confidence": "high"})

    elif "ハイボール" in name:
        comps.append({"name_ja": "ウイスキー", "name_en": "Whisky", "estimated_grams": 40.0, "confidence": "high"})

    elif "プリン" in name:
        comps.append({"name_ja": "プリン", "name_en": "Custard Pudding", "estimated_grams": 95.0, "confidence": "high"})

    elif "ティラミス" in name:
        comps.append({"name_ja": "チーズ", "name_en": "Mascarpone", "estimated_grams": 30.0, "confidence": "high"})
        comps.append({"name_ja": "ショートケーキ", "name_en": "Sponge Cake", "estimated_grams": 30.0, "confidence": "high"})
        comps.append({"name_ja": "生クリーム", "name_en": "Cream", "estimated_grams": 20.0, "confidence": "high"})

    elif "パフェ" in name:
        comps.append({"name_ja": "アイスクリーム", "name_en": "Ice Cream", "estimated_grams": 90.0, "confidence": "high"})
        comps.append({"name_ja": "生クリーム", "name_en": "Whipped Cream", "estimated_grams": 30.0, "confidence": "high"})

    elif "アイス" in name or "ソフトクリーム" in name:
        comps.append({"name_ja": "アイスクリーム", "name_en": "Ice Cream", "estimated_grams": 90.0, "confidence": "high"})

    elif "ケーキ" in name:
        comps.append({"name_ja": "ショートケーキ", "name_en": "Cake", "estimated_grams": 85.0, "confidence": "high"})

    # 13. Generic Sets (セット)
    elif "セット" in name:
        comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": 200.0, "confidence": "high"})
        comps.append({"name_ja": "みそ", "name_en": "Miso Paste", "estimated_grams": 15.0, "confidence": "high"})
        comps.append({"name_ja": "だし汁", "name_en": "Dashi Broth", "estimated_grams": 150.0, "confidence": "high"})
        comps.append({"name_ja": "絹ごし豆腐", "name_en": "Tofu", "estimated_grams": 20.0, "confidence": "high"})
        comps.append({"name_ja": "豚肉", "name_en": "Main Dish Meat", "estimated_grams": 100.0, "confidence": "medium"})
        comps.append({"name_ja": "キャベツ", "name_en": "Shredded Cabbage", "estimated_grams": 50.0, "confidence": "high"})

    # 14. Standalone Rice Dishes (ライス、ごはん、白米、おにぎり)
    elif any(k in name for k in ("ライス", "ごはん", "ご飯", "白米", "麦ごはん", "麦飯", "おにぎり", "おむすび")) and not any(k in name for k in ("パン", "パスタ", "ピザ", "スライス")):
        if "おにぎり" in name or "おむすび" in name:
            comps.append({"name_ja": "ご飯", "name_en": "Rice Ball", "estimated_grams": 110.0, "confidence": "high"})
            comps.append({"name_ja": "のり", "name_en": "Nori Seaweed", "estimated_grams": 1.5, "confidence": "high"})
            if "鮭" in name or "サーモン" in name:
                comps.append({"name_ja": "サーモン", "name_en": "Salmon Filling", "estimated_grams": 15.0, "confidence": "high"})
            elif "ツナ" in name or "マヨ" in name:
                comps.append({"name_ja": "まぐろ 缶詰", "name_en": "Tuna Mayo", "estimated_grams": 15.0, "confidence": "high"})
        else:
            rice_g = 100.0 if any(k in name for k in ("半", "小", "ミニ")) else (280.0 if any(k in name for k in ("大盛", "大盛り", "大")) else 200.0)
            comps.append({"name_ja": "ご飯", "name_en": "Steamed Rice", "estimated_grams": rice_g, "confidence": "high"})

    else:
        comps.append({"name_ja": name, "name_en": name, "estimated_grams": 150.0, "confidence": "medium"})

    # Universal Post-check: If dish has explicit rice tag (e.g. てりたまハンバーグ（ライス付）) and rice wasn't added yet:
    if has_explicit_rice and not any(c["name_ja"] == "ご飯" for c in comps):
        rice_g = 100.0 if any(k in name for k in ("半", "小", "ミニ")) else (280.0 if any(k in name for k in ("大盛", "大盛り", "大")) else 200.0)
        comps.append({"name_ja": "ご飯", "name_en": "Accompaniment Rice", "estimated_grams": rice_g, "confidence": "high"})

    return comps



# 「＆」「＋」 and 「と」 join two dishes on one line: 「殻付き海老グリル＆大俵ハンバーグ」
# is a plate of shrimp AND a burger. The keyword ladder stops at its first match,
# so the shrimp was never read and the plate costed the same as the burger alone.
_COMBINED = re.compile(r"\s*(?:[＆&]|\+|＋)\s*")

# A weight the menu states about the dish itself: 「…ハンバーグ145g」, 「ダブル220g」,
# 「リブアイステーキ [300G]」. Not a pack size and not a price.
_STATED_G = re.compile(r"(\d{2,4})\s*(?:g|G|ｇ|グラム)?")

# What a stated weight is a weight OF. A menu that says 145g beside a burger is
# telling you the patty, not the sauce or the garnish, so the weight is applied
# to the heaviest protein component and the rest of the plate is left alone.
_MAIN_COMPONENT = (
    "ハンバーグ", "牛肉", "豚肉", "鶏肉", "とんかつ", "から揚げ", "ステーキ",
    "まぐろ", "サーモン", "えび", "うなぎ", "いくら", "ラム", "羊肉", "合いびき",
)


def _stated_grams(name):
    """The weight the dish name claims for itself, or None.

    A number under 20 g is a garnish or a typo rather than a portion, and one
    over 1000 g is a sharing platter the ladder cannot model either way.
    """
    best = None
    for m in _STATED_G.finditer(name or ""):
        g = float(m.group(1))
        if 20 <= g <= 1000:
            best = g if best is None else max(best, g)
    return best


def _apply_stated_grams(name, comps):
    """Scale the main component to the weight the name gives it.

    「濃厚ビーフシチューの包み焼きハンバーグ145g」, its 110g sibling and the ダブル220g
    all came out at 432.5 kcal because the ladder used a fixed patty weight and
    never looked at the number. They differ by exactly that number.
    """
    grams = _stated_grams(name)
    if not grams or not comps:
        return comps
    mains = [c for c in comps
             if any(k in (c.get("name_ja") or "") for k in _MAIN_COMPONENT)]
    if not mains:
        return comps
    main = max(mains, key=lambda c: c.get("estimated_grams") or 0)
    doubled = 2 if any(k in name for k in ("ダブル", "Ｗ", "W", "2枚", "二枚")) else 1
    main["estimated_grams"] = round(grams * doubled if doubled > 1 and grams < 200 else grams, 1)
    main["confidence"] = "high"
    main["grams_source"] = "stated"
    return comps


def _merge_components(comps):
    """One row per ingredient, weights added, order kept.

    Two halves of a combined dish both bring 「ご飯」; a reader should see one
    portion of rice with the two weights added, not the same word twice.
    """
    out, seen = [], {}
    for c in comps:
        key = c.get("name_ja")
        if key in seen:
            prev = seen[key]
            prev["estimated_grams"] = round(
                (prev.get("estimated_grams") or 0) + (c.get("estimated_grams") or 0), 1)
            continue
        seen[key] = c
        out.append(c)
    return out


def decompose_dish_text(dish_name: str, shop_name: str = None):
    """Decompose a named restaurant dish/meal into ingredients and grams.

    Uses Gemini when configured — it reads the whole name — or the keyword
    ladder, which does not. Around the ladder this splits a combined dish into
    its halves and applies any weight the name states, which is the difference
    between a figure about this dish and a figure about its main word.
    """
    name = (dish_name or "").strip()
    dishes = _decompose_with_model(name, shop_name)
    if dishes:
        return dishes

    parts = [p for p in _COMBINED.split(name) if p.strip()] or [name]
    comps = []
    for part in parts:
        comps.extend(_heuristic_components(part.strip(), shop_name))
    comps = _merge_components(comps)
    # Only when the dish is one thing. 「大俵ハンバーグ＆手ごねハンバーグ100g」 states
    # 100 g about the second patty alone, and applying it to the merged pair
    # turned two burgers into one small one.
    if len(parts) == 1:
        comps = _apply_stated_grams(name, comps)
    return [{
        "dish_ja": name,
        "dish_en": "Meal",
        "servings": 1,
        "components": comps,
    }]




@router.get("/analyze-dish")
@router.post("/analyze-dish")
async def analyze_named_dish(
    request: Request,
    dish: str = Query(..., description="Name of the restaurant dish / meal"),
    shop: str = Query(None, description="Name of the restaurant chain or cuisine"),
    lang: str = Query("ja")
):
    """Estimate the nutrition and ingredient breakdown for a named dish/meal."""
    if lang not in LANGS:
        raise HTTPException(status_code=400, detail=f"lang must be one of {', '.join(LANGS)}")
    dish_clean = (dish or "").strip()
    if not dish_clean:
        raise HTTPException(status_code=400, detail="dish name required")

    cache_key = hashlib.sha256(f"dish:{shop or ''}:{dish_clean}:{lang}".encode()).hexdigest()
    cached = _cache_get(cache_key, lang)
    if cached is not None:
        cached["cached"] = True
        return cached

    dishes_in = decompose_dish_text(dish_clean, shop)
    result = calculate_nutrition_for_dishes(dishes_in, lang=lang)
    result["dish_name"] = dish_clean
    result["shop_name"] = shop
    _cache_put(cache_key, lang, result)
    return result

