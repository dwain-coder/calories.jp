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

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from ..calc.nutrition import meal_insights, scale, sum_components
from ..site import queries
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

VISION_PROMPT = """You are a food-recognition assistant. Identify the distinct foods/components visible in this meal photo.
For each component estimate the edible quantity in grams (typical serving reasoning; be conservative).
Respond ONLY with a JSON object:
{"foods": [{"name_ja": "...", "name_en": "...", "estimated_grams": <number>, "confidence": "high"|"medium"|"low"}]}
If you cannot identify something confidently, still list it with confidence "low" or omit it. Do not guess exotic foods."""


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


def _match_food(name_ja, name_en, lang):
    """Best clean-corpus match (MEXT > FDC priority is applied inside search)."""
    for q in (name_ja, name_en):
        if not q:
            continue
        hits = queries.search(q, lang, limit=3)
        foods = [h for h in hits if h["page_type"] == "food"]
        if foods:
            return foods[0]
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
        return cached                      # served from cache, costs nothing

    _rate_limit(request.client.host if request.client else "unknown")

    from .server import get_gemini_client  # reuse existing client + key handling
    from google.genai import types
    client = get_gemini_client()
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime),
                VISION_PROMPT,
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        detected = json.loads(resp.text).get("foods", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI analysis unavailable: {e}")

    components, unmatched, parts = [], [], []
    for f in detected:
        name_ja, name_en = f.get("name_ja"), f.get("name_en")
        grams = f.get("estimated_grams")
        conf = f.get("confidence", "low")
        try:
            grams = float(grams) if grams is not None else None
        except (TypeError, ValueError):
            grams = None
        match = _match_food(name_ja, name_en, lang)
        if not match:
            unmatched.append({"name_ja": name_ja, "name_en": name_en, "confidence": conf})
            continue
        nut = queries.food_nutrition_json(match["item_id"])
        per100 = nut["per_100g"] if nut else None
        scaled = scale(per100, grams) if (per100 and grams) else None
        if scaled:
            parts.append(scaled)
        lic, _ = get_license_info(match["source"])
        components.append({
            "identified": {"name_ja": name_ja, "name_en": name_en, "confidence": conf},
            "ai_estimate": {"estimated_grams": grams, "estimated": True},
            "db_match": {
                "item_id": match["item_id"],
                "title": match["title"],
                "url": f"/{lang}/food/{match['slug']}",
                "source": match["source"],
                "license": lic,
                "per_100g": per100,
            },
            "calculated": scaled,  # deterministic: DB per-100g x AI grams
        })

    totals, missing = sum_components(parts)

    # Micronutrients + fiber + salt: deterministic sums of MEXT laboratory
    # values scaled by the AI-estimated grams of each matched component.
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

    result = {
        "components": components,
        "unmatched": unmatched,
        "totals": totals,
        "salt_g": round(salt_g, 2) if salt_g is not None else None,
        "fiber_g": round(fiber_g, 1) if fiber_g is not None else None,
        "macro_dv": dv,
        "micronutrients": micronutrients,
        "micros_from": n_micro,
        "insights": insights,
        "totals_note": "Deterministic calculation from database per-100g values and AI-estimated quantities. Quantities are AI estimates, not measurements.",
        "missing_fields": missing,
        "cached": False,
    }
    _cache_put(sha, lang, result)
    return result
