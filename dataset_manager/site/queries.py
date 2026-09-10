"""Read-only queries for the public site. Clean corpus only — every page query
joins through site_pages, which is never populated for OpenFoodFacts/Wikipedia/
Wikidata/FoodKeeper items, so quarantined and share-alike data is structurally
excluded from the public surface."""
import re
import sqlite3

from ..api.database import get_connection, get_license_info
from ..calc.nutrition import dish_nutrition
from . import claims, servings
from . import menuterms
from .brand_assets import get_chain_brand_badge, classify_dish_visual
from . import food_images
from .food_images import get_dish_image
from .i18n import MICRO_DV


def _row_get(row, key, default=None):
    """sqlite3.Row has no .get, and a database built before a column existed
    does not have it at all."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default

MIN_LINK_CONFIDENCE = 0.7
DISH_COVERAGE_THRESHOLD = 0.6

# Atwater factors — deterministic energy split for the PFC ratio bar.
def pfc_energy_split(nutrition):
    if not nutrition:
        return None
    p = (nutrition.get("protein_g") or 0) * 4
    f = (nutrition.get("fat_g") or 0) * 9
    c = (nutrition.get("carbohydrate_g") or 0) * 4
    total = p + f + c
    if total <= 0:
        return None
    # Largest-remainder rounding: the three shares drive the width of the PFC
    # bar, so they have to sum to exactly 100 — rounding each one on its own
    # leaves a gap at 99 or overflows at 101.
    exact = [p / total * 100, f / total * 100, c / total * 100]
    floors = [int(v) for v in exact]
    short = 100 - sum(floors)
    order = sorted(range(3), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in order[:short]:
        floors[i] += 1
    return {"p": floors[0], "f": floors[1], "c": floors[2]}


def get_page(lang, slug):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM site_pages WHERE lang = ? AND slug = ?", (lang, slug)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_names(conn, item_id):
    """{lang: {'primary': name, 'kind': kind, 'aliases': [...]}}"""
    out = {}
    for r in conn.execute(
        "SELECT lang, name, kind, is_primary FROM item_names WHERE item_id = ?"
        " ORDER BY is_primary DESC, id", (item_id,)
    ):
        d = out.setdefault(r["lang"], {"primary": None, "kind": None, "aliases": []})
        if r["is_primary"] and d["primary"] is None:
            d["primary"], d["kind"] = r["name"], r["kind"]
        else:
            d["aliases"].append(r["name"])
    return out


def get_alternates(conn, item_id):
    """{lang: (page_type, slug)} for hreflang / lang switcher."""
    return {
        r["lang"]: (r["page_type"], r["slug"])
        for r in conn.execute(
            "SELECT lang, page_type, slug FROM site_pages WHERE item_id = ?", (item_id,)
        )
    }


def display_name(names, item_row, lang):
    d = names.get(lang) or {}
    return d.get("primary") or item_row["name"]


def get_food_page_data(page):
    item_id, lang = page["item_id"], page["lang"]
    conn = get_connection()
    item = dict(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
    names = get_names(conn, item_id)
    nut = conn.execute("SELECT * FROM nutrition WHERE item_id = ?", (item_id,)).fetchone()
    nutrition = (
        {k: nut[k] for k in ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g")}
        if nut else None
    )
    nutrients = [
        dict(r) for r in conn.execute(
            "SELECT code, name, unit, amount, quality FROM nutrients WHERE item_id = ? ORDER BY id",
            (item_id,))
    ]
    portions = [
        dict(r) for r in conn.execute(
            "SELECT description, gram_weight FROM food_portions WHERE item_id = ? ORDER BY id",
            (item_id,))
    ]
    shelf_life = [
        dict(r) for r in conn.execute(
            "SELECT storage_method, min_days, max_days, tips FROM shelf_life WHERE item_id = ?",
            (item_id,))
    ]
    jdi8 = conn.execute("SELECT score FROM jdi8_scores WHERE item_id = ?", (item_id,)).fetchone()
    # 食塩相当量 (salt equivalent) — expected on Japanese nutrition labels.
    salt_g = next((n["amount"] for n in nutrients if n["code"] == "NACL_EQ"), None)
    # Which of the headline figures MEXT estimated rather than analysed. Energy
    # never is, but protein, fat and carbohydrate are on 12-14% of foods, and
    # those are exactly the numbers the calculator and the FAQ quote.
    _macro_codes = {"energy_kcal": "ENERC_KCAL", "protein_g": "PROT-", "fat_g": "FAT-",
                    "carbohydrate_g": "CHOCDF-", "salt_g": "NACL_EQ"}
    quality_by_code = {n["code"]: n["quality"] for n in nutrients}
    macro_quality = {
        field: quality_by_code.get(code)
        for field, code in _macro_codes.items()
        if quality_by_code.get(code) and quality_by_code.get(code) != "measured"
    }
    # Related: same source+category neighbors that have pages in this lang.
    related = [
        dict(r) for r in conn.execute(
            """SELECT sp.slug, sp.page_type, sp.title, i.id AS item_id,
                      COALESCE(nm.name, sp.title) AS name
               FROM site_pages sp JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND i.category = ? AND i.source = ? AND i.id != ?
               ORDER BY ABS(i.id - ?) LIMIT 8""",
            (lang, item["category"], item["source"], item_id, item_id))
    ]
    # The full MEXT taxonomy path, shown under the heading so the exact source
    # row stays visible even though the heading uses the short display name.
    qual = conn.execute(
        "SELECT name FROM item_names WHERE item_id = ? AND lang = 'ja' AND kind = 'full'",
        (item_id,)).fetchone()
    qualified_name = qual["name"] if qual else None
    alternates = get_alternates(conn, item_id)
    ranks = nutrient_ranks(conn, item, nutrition)
    notable = notable_nutrients(conn, item_id, MICRO_DV.get(lang) or MICRO_DV["ja"])
    # Which of Japan's own labelling criteria this composition would satisfy.
    nutrient_claims = claims.claims_for(nutrients, item["category"])
    conn.close()
    ja_name = (names.get("ja") or {}).get("primary") or item["name"]
    preps = prep_variants(item_id, lang, ja_name)
    # What one serving of this food is, when we have decided. The figures are
    # the same per-100g values scaled deterministically; the portion itself is
    # a kitchen convention and is labelled as one.
    serving = servings.for_food(ja_name)
    if serving and nutrition:
        serving = dict(serving, nutrition=servings.scale(nutrition, serving["grams"]),
                       salt_g=(salt_g * serving["grams"] / 100 if salt_g is not None else None))
    lic, warning = get_license_info(item["source"])
    return {
        "item": item, "names": names, "nutrition": nutrition,
        "nutrients": nutrients, "portions": portions, "shelf_life": shelf_life,
        "jdi8": jdi8["score"] if jdi8 else None,
        "salt_g": salt_g, "macro_quality": macro_quality, "serving": serving,
        "ranks": ranks, "notable": notable, "claims": nutrient_claims,
        "pfc": pfc_energy_split(nutrition),
        "preps": preps, "qualified_name": qualified_name,
        "related": related, "alternates": alternates,
        "license": lic, "license_warning": warning,
    }


# Facts about where a food sits among its neighbours. Not advice, and not a
# health claim: "higher in protein than 92% of 肉類" is a statement about the
# composition table, which is the only thing this site is in a position to
# say. Computed per request — a handful of counting queries over 2,538 rows,
# about 5 ms — rather than precomputed into a table that a later import could
# leave stale.
RANKED = (
    ("energy_kcal", "calories"),
    ("protein_g", "protein"),
    ("fat_g", "fat"),
    ("carbohydrate_g", "carbs"),
)
MIN_PEERS = 20          # below this a percentile says more than it knows


def nutrient_ranks(conn, item, nutrition):
    """[{field, label_key, percentile, peers}] within the food's own group."""
    if not nutrition or not item["category"] or item["category"] == "foundation":
        return []
    out = []
    for field, label_key in RANKED:
        value = nutrition.get(field)
        if value is None:
            continue
        row = conn.execute(
            f"""SELECT COUNT(*) AS peers,
                       SUM(CASE WHEN n.{field} < ? THEN 1 ELSE 0 END) AS below
                FROM nutrition n JOIN items i ON i.id = n.item_id
                WHERE i.category = ? AND i.source = ? AND n.{field} IS NOT NULL""",
            (value, item["category"], item["source"])).fetchone()
        if not row or (row["peers"] or 0) < MIN_PEERS:
            continue
        out.append({
            "field": field, "label_key": label_key,
            "percentile": round((row["below"] or 0) / row["peers"] * 100),
            "peers": row["peers"],
        })
    return out


def notable_nutrients(conn, item_id, dv_table, limit=3):
    """The components this food carries most of, as a share of the Japanese
    labelling reference value. A fact with its basis named, not a claim that
    the food is good for anything."""
    if not dv_table:
        return []
    codes = tuple(dv_table.keys())
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"""SELECT code, name, amount, unit, quality FROM nutrients
            WHERE item_id = ? AND code IN ({marks}) AND amount IS NOT NULL""",
        (item_id, *codes)).fetchall()
    scored = []
    for r in rows:
        label, dv, unit = dv_table[r["code"]]
        if not dv:
            continue
        pct = r["amount"] / dv * 100
        if pct >= 30:            # a third of a day's reference in 100 g
            scored.append({"code": r["code"], "label": label, "amount": r["amount"],
                           "unit": unit, "dv_pct": round(pct), "quality": r["quality"]})
    scored.sort(key=lambda x: -x["dv_pct"])
    return scored[:limit]


def get_dish_page_data(page):
    item_id, lang = page["item_id"], page["lang"]
    conn = get_connection()
    item = dict(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
    names = get_names(conn, item_id)
    rd_row = conn.execute("SELECT * FROM regional_dishes WHERE item_id = ?", (item_id,)).fetchone()
    rd = dict(rd_row) if rd_row else {}

    links = [
        dict(r) for r in conn.execute(
            """SELECT l.*, sp.slug AS mext_slug
               FROM recipe_ingredient_links l
               LEFT JOIN site_pages sp ON sp.item_id = l.mext_item_id AND sp.lang = ?
               WHERE l.dish_item_id = ? ORDER BY l.line_no""",
            (lang, item_id))
    ]
    usable = [
        ln for ln in links
        if ln["mext_item_id"] and (ln["confidence"] or 0) >= MIN_LINK_CONFIDENCE
    ]
    nut_by_item = {}
    if usable:
        ids = [ln["mext_item_id"] for ln in usable]
        q = ",".join("?" * len(ids))
        for r in conn.execute(f"SELECT * FROM nutrition WHERE item_id IN ({q})", ids):
            nut_by_item[r["item_id"]] = {
                k: r[k] for k in ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g")
            }
    computed = dish_nutrition(
        [{"grams": ln["grams"], "mext_item_id": ln["mext_item_id"]} for ln in usable],
        nut_by_item,
    )
    computed["n_total"] = len(links)
    # The weight the figures are for. MAFF recipes are written for a household
    # pot — けの汁 starts with 2kg of daikon — so a bare calorie number reads as
    # a portion and is wrong by an order of magnitude.
    computed["grams"] = round(sum(ln["grams"] for ln in usable if ln["grams"]), 1)
    # Weights the recipe did not state. 「にんじん1本」 is a count, and a carrot
    # is about 150 g rather than exactly 150 g, so the page says how much of
    # its total rests on that assumption.
    # Per 100 g as well as per pot. MAFF recipes are household quantities and
    # only 13 of 1,364 say how many they serve, so the whole-recipe total is
    # not comparable between dishes and per 100 g is.
    if computed["grams"]:
        computed["per_100g"] = {
            k: (v * 100 / computed["grams"] if isinstance(v, (int, float)) else v)
            for k, v in (computed["totals"] or {}).items()
        }
    else:
        computed["per_100g"] = None
    computed["n_assumed"] = sum(
        1 for ln in usable
        if ln["grams"] is not None and _row_get(ln, "grams_source") == "unit")
    show_nutrition = (
        len(links) > 0
        and computed["n_resolved"] >= 2
        and computed["n_resolved"] / len(links) >= DISH_COVERAGE_THRESHOLD
    )
    # Per-ingredient breakdown for the transparent math table.
    breakdown = []
    if show_nutrition:
        for ln in usable:
            per100 = nut_by_item.get(ln["mext_item_id"])
            if per100 and ln["grams"] is not None:
                breakdown.append({
                    "raw_name": ln["raw_name"], "grams": ln["grams"],
                    "kcal": (per100["energy_kcal"] or 0) * ln["grams"] / 100.0,
                    "slug": ln["mext_slug"],
                })

    related = [
        dict(r) for r in conn.execute(
            """SELECT sp.slug, sp.page_type, sp.title,
                      COALESCE(nm.name, sp.title) AS name
               FROM site_pages sp JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND i.category = ? AND i.source = ? AND i.id != ?
               ORDER BY ABS(i.id - ?) LIMIT 8""",
            (lang, item["category"], item["source"], item_id, item_id))
    ]
    alternates = get_alternates(conn, item_id)
    jdi8 = conn.execute("SELECT score FROM jdi8_scores WHERE item_id = ?", (item_id,)).fetchone()
    try:
        img_row = conn.execute(
            "SELECT * FROM item_images WHERE item_id = ?", (item_id,)).fetchone()
        image = dict(img_row) if img_row else None
    except sqlite3.OperationalError:
        image = None      # table newer than the deployed extract
    conn.close()
    lic, warning = get_license_info(item["source"])
    return {
        "item": item, "names": names, "dish": rd, "links": links, "image": image,
        "computed": computed, "show_nutrition": show_nutrition, "breakdown": breakdown,
        "pfc": pfc_energy_split(computed["totals"]) if show_nutrition else None,
        "related": related, "alternates": alternates,
        "jdi8": jdi8["score"] if jdi8 else None,
        "license": lic, "license_warning": warning,
    }


def search(q, lang, limit=20):
    """Search the clean-corpus index. Query tokens are ANDed: tokens of 3+
    chars go through FTS trigram (fast, substring-capable for Japanese);
    shorter tokens (common in Japanese: むね, 生) are LIKE post-filters —
    trigram cannot match under 3 chars."""
    q = (q or "").strip()
    if not q:
        return []
    tokens = q.split()
    long_t = [t for t in tokens if len(t) >= 3]
    short_t = [t for t in tokens if 0 < len(t) < 3]
    conn = get_connection()

    base_select = """
        SELECT f.item_id, sp.slug, sp.page_type, sp.title, n.energy_kcal, i.source,
               COALESCE(nm.name, sp.title) AS name
        FROM search_fts f
        JOIN site_pages sp ON sp.item_id = f.item_id AND sp.lang = ?
        JOIN items i ON i.id = f.item_id
        LEFT JOIN item_names nm ON nm.item_id = f.item_id
             AND nm.lang = sp.lang AND nm.is_primary = 1
        LEFT JOIN nutrition n ON n.item_id = f.item_id
        WHERE f.lang = ?"""
    like_clause = " AND (f.name LIKE ? OR f.category LIKE ?)"

    if long_t:
        match = " AND ".join('"' + t.replace('"', '""') + '"' for t in long_t)
        sql = base_select + " AND search_fts MATCH ?" + like_clause * len(short_t) + \
            " ORDER BY rank LIMIT ?"
        params = [lang, lang, match]
    else:
        sql = base_select + like_clause * len(short_t) + \
            " ORDER BY LENGTH(f.name) LIMIT ?"
        params = [lang, lang]
    for t in short_t:
        params += [f"%{t}%", f"%{t}%"]
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()

    if not rows and long_t:
        # FTS miss (e.g. spelling variant): LIKE-AND over the same index.
        sql = base_select + like_clause * len(tokens) + " ORDER BY LENGTH(f.name) LIMIT ?"
        params = [lang, lang]
        for t in tokens:
            params += [f"%{t}%", f"%{t}%"]
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    conn.close()
    # Source priority: MEXT first, then FDC, then dishes/others, preserving rank inside groups.
    prio = {"MEXT Standard Tables": 0, "USDA FoodData Central": 1}
    return sorted((dict(r) for r in rows), key=lambda r: prio.get(r["source"], 2))


# Everyday staples for the home page (matched against JA names; a real
# popularity signal can replace this once analytics exist).
CURATED_HOME_FOODS = (
    "水稲めし 精白米 うるち米", "にわとり 若どり・主品目 むね 皮なし 生",
    "ぶた 大型種肉 ロース 脂身つき 生", "しろさけ 生", "鶏卵 全卵 生",
    "普通牛乳", "糸引き納豆", "木綿豆腐", "バナナ 生", "りんご 皮なし 生",
    "角形食パン 食パン", "ブロッコリー 花序 生",
)


def corpus_counts(lang="ja"):
    """What the site actually holds, for the pages that describe it.

    Counted rather than written down: an About page quoting a number that has
    drifted from the database is worse than one quoting none.
    """
    conn = get_connection()
    counts = {
        r["page_type"]: r["c"] for r in conn.execute(
            "SELECT page_type, COUNT(*) c FROM site_pages WHERE lang = ? GROUP BY page_type",
            (lang,))
    }
    nutrients = conn.execute(
        """SELECT MAX(c) m FROM (SELECT COUNT(*) c FROM nutrients GROUP BY item_id)""").fetchone()
    conn.close()
    return {
        "foods": counts.get("food", 0),
        "dishes": counts.get("dish", 0),
        "nutrients": (nutrients["m"] if nutrients else 0) or 0,
    }


def home_data(lang):
    conn = get_connection()
    counts = {
        r["page_type"]: r["c"] for r in conn.execute(
            "SELECT page_type, COUNT(*) c FROM site_pages WHERE page_type IS NOT NULL AND lang = ? GROUP BY page_type",
            (lang,))
    }
    foods, seen = [], set()
    for term in CURATED_HOME_FOODS:
        r = conn.execute(
            """SELECT sp.slug, sp.title, n.energy_kcal,
                      COALESCE(dn.name, sp.title) AS name
               FROM item_names nm
               JOIN site_pages sp ON sp.item_id = nm.item_id AND sp.lang = ? AND sp.page_type = 'food'
               JOIN nutrition n ON n.item_id = nm.item_id
               LEFT JOIN item_names dn ON dn.item_id = nm.item_id
                    AND dn.lang = sp.lang AND dn.is_primary = 1
               WHERE nm.lang = 'ja' AND nm.name LIKE ? LIMIT 1""",
            (lang, f"%{term}%")).fetchone()
        if r and r["slug"] not in seen:
            seen.add(r["slug"])
            foods.append(dict(r))
    if len(foods) < 12:
        for r in conn.execute(
            """SELECT sp.slug, sp.title, n.energy_kcal,
                      COALESCE(nm.name, sp.title) AS name
               FROM site_pages sp
               JOIN nutrition n ON n.item_id = sp.item_id
               JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND sp.page_type = 'food'
               ORDER BY CASE i.source WHEN 'MEXT Standard Tables' THEN 0 ELSE 1 END,
                        sp.item_id LIMIT 12""", (lang,)):
            if r["slug"] not in seen and len(foods) < 12:
                seen.add(r["slug"])
                foods.append(dict(r))
    # One dish per prefecture for variety.
    dishes = [
        dict(r) for r in conn.execute(
            """SELECT sp.slug, sp.title, i.category, MIN(sp.item_id),
                      COALESCE(nm.name, sp.title) AS name
               FROM site_pages sp JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND sp.page_type = 'dish'
               GROUP BY i.category ORDER BY i.category LIMIT 12""", (lang,))
    ]
    categories = [
        dict(r) for r in conn.execute(
            """SELECT i.category, COUNT(*) c FROM items i
               JOIN site_pages sp ON sp.item_id = i.id AND sp.lang = ?
               WHERE i.source = 'MEXT Standard Tables'
               GROUP BY i.category ORDER BY c DESC""", (lang,))
    ]
    # The atlas only earns the hero slot when there are enough foods to show a
    # shape. English stays below this until the name translations are built.
    # Counts every food that has a page in either language, matching what the
    # atlas actually plots.
    atlas_count = conn.execute(
        """SELECT COUNT(DISTINCT sp.item_id) c FROM site_pages sp
           JOIN nutrition n ON n.item_id = sp.item_id
           WHERE sp.page_type = 'food' AND n.energy_kcal IS NOT NULL""").fetchone()["c"]
    conn.close()
    return {"counts": counts, "foods": foods, "dishes": dishes,
            "categories": categories, "atlas_count": atlas_count}


# MEXT encodes preparation as the final token of a food name, so the same food
# appears as separate rows (うどん 生 / うどん ゆで). Grouping them turns 693
# rows into real "how cooking changes the numbers" comparisons — measured,
# not estimated.
PREP_TOKENS = (
    "生", "ゆで", "焼き", "乾", "水煮", "油いため", "蒸し", "天ぷら", "フライ",
    "素揚げ", "ソテー", "電子レンジ調理", "いり", "冷凍", "水煮缶詰", "缶詰",
    "素干し", "煮干し", "つくだ煮", "塩漬", "塩抜き", "味付け", "浸出液",
)
PREP_LABELS_EN = {
    "生": "Raw", "ゆで": "Boiled", "焼き": "Grilled", "乾": "Dried",
    "水煮": "Simmered in water", "油いため": "Stir-fried in oil", "蒸し": "Steamed",
    "天ぷら": "Tempura", "フライ": "Deep-fried, breaded", "素揚げ": "Deep-fried, plain",
    "ソテー": "Sautéed", "電子レンジ調理": "Microwaved", "いり": "Dry-roasted",
    "冷凍": "Frozen", "水煮缶詰": "Canned in water", "缶詰": "Canned",
    "素干し": "Sun-dried", "煮干し": "Dried (niboshi)", "つくだ煮": "Simmered in soy",
    "塩漬": "Salted", "塩抜き": "Desalted", "味付け": "Seasoned", "浸出液": "Infusion",
}


def split_prep(name):
    """('うどん 生') -> ('うどん', '生'); returns (name, None) if no prep token."""
    parts = name.split()
    if len(parts) > 1 and parts[-1] in PREP_TOKENS:
        return " ".join(parts[:-1]), parts[-1]
    return name, None


def prep_variants(item_id, lang, ja_name):
    """Sibling items that are the same food prepared differently."""
    base, prep = split_prep(ja_name)
    if not prep:
        return []
    conn = get_connection()
    rows = conn.execute(
        """SELECT nm.item_id, nm.name AS ja_name, sp.slug, sp.title,
                  n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g,
                  cy.rate_percent
           FROM item_names nm
           JOIN items i ON i.id = nm.item_id AND i.source = 'MEXT Standard Tables'
           JOIN site_pages sp ON sp.item_id = nm.item_id AND sp.lang = ?
           LEFT JOIN nutrition n ON n.item_id = nm.item_id
           LEFT JOIN cooking_yield cy ON cy.item_id = nm.item_id
           WHERE nm.lang = 'ja' AND nm.is_primary = 1 AND nm.name LIKE ?
           ORDER BY n.energy_kcal DESC""",
        (lang, base + " %")).fetchall()
    conn.close()
    out = []
    for r in rows:
        b, p = split_prep(r["ja_name"])
        if b != base or not p:
            continue
        out.append({
            "item_id": r["item_id"], "slug": r["slug"],
            "prep": PREP_LABELS_EN.get(p, p) if lang == "en" else p,
            "is_current": r["item_id"] == item_id,
            "energy_kcal": r["energy_kcal"], "protein_g": r["protein_g"],
            "fat_g": r["fat_g"], "carbohydrate_g": r["carbohydrate_g"],
            # 100 g of the raw food becomes this much once cooked, so the
            # cooked row can also be read as "what that raw 100 g became".
            "yield_pct": _row_get(r, "rate_percent"),
            "from_raw_100g": (
                r["energy_kcal"] * _row_get(r, "rate_percent") / 100
                if r["energy_kcal"] is not None and _row_get(r, "rate_percent") else None),
        })
    return out if len(out) > 1 else []


def cooking_effect(lang, limit=40):
    """Foods that appear in the table both raw and cooked, ranked by how much
    the preparation changes their energy density.

    This is the comparison a reader actually wants — and unlike written guides
    that estimate it, both numbers here are separate laboratory analyses.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT nm.item_id, nm.name, sp.slug, i.category, n.energy_kcal,
                  n.protein_g, n.fat_g, n.carbohydrate_g
           FROM item_names nm
           JOIN items i ON i.id = nm.item_id AND i.source = 'MEXT Standard Tables'
           JOIN site_pages sp ON sp.item_id = nm.item_id AND sp.lang = ?
           JOIN nutrition n ON n.item_id = nm.item_id
           WHERE nm.lang = 'ja' AND nm.is_primary = 1 AND n.energy_kcal IS NOT NULL""",
        (lang,)).fetchall()
    conn.close()

    families = {}
    for r in rows:
        base, prep = split_prep(r["name"])
        if not prep:
            continue
        families.setdefault(base, []).append({
            "prep": PREP_LABELS_EN.get(prep, prep) if lang == "en" else prep,
            "slug": r["slug"], "category": r["category"],
            "kcal": r["energy_kcal"], "protein_g": r["protein_g"],
            "fat_g": r["fat_g"], "carbohydrate_g": r["carbohydrate_g"],
            "base": base,
        })

    out = []
    for base, members in families.items():
        if len(members) < 2:
            continue
        lo = min(members, key=lambda m: m["kcal"])
        hi = max(members, key=lambda m: m["kcal"])
        if lo["kcal"] <= 0 or hi is lo:
            continue
        out.append({
            "base": base, "category": members[0]["category"],
            "low": lo, "high": hi,
            "ratio": hi["kcal"] / lo["kcal"],
            "delta": hi["kcal"] - lo["kcal"],
            "n": len(members),
        })
    out.sort(key=lambda x: -x["ratio"])
    return {"rows": out[:limit], "total": len(out)}


def group_ranking(lang, ja_category, metric="protein_g", limit=25):
    """Top foods in one group by a chosen measurement."""
    if metric not in ("protein_g", "fat_g", "carbohydrate_g", "energy_kcal"):
        return None
    conn = get_connection()
    rows = [
        dict(r) for r in conn.execute(
            f"""SELECT sp.slug, COALESCE(nm.name, sp.title) AS name,
                       n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
                FROM site_pages sp
                JOIN items i ON i.id = sp.item_id
                JOIN nutrition n ON n.item_id = sp.item_id
                LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                     AND nm.lang = sp.lang AND nm.is_primary = 1
                WHERE sp.lang = ? AND i.category = ? AND n.{metric} IS NOT NULL
                ORDER BY n.{metric} DESC LIMIT ?""",
            (lang, ja_category, limit))
    ]
    conn.close()
    return rows


def nutrient_ranking(lang, code, limit=60):
    """Foods carrying the most of one component, per 100 g.

    Measured values only. A value MEXT prints in parentheses is its own estimate
    for that food, and a ranking is a claim that THIS food holds more than THAT
    one — an estimate cannot settle it, and a `Tr` is not a quantity at all.

    Serving figures ride along where the portion table knows one, because
    「100 g あたり」 is not how anyone eats seaweed or liver.
    """
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT sp.slug, COALESCE(nm.name, sp.title) AS name, i.category,
                      n.amount, n.unit, n.name AS nutrient_name,
                      nu.energy_kcal
               FROM nutrients n
               JOIN site_pages sp ON sp.item_id = n.item_id
                    AND sp.lang = ? AND sp.page_type = 'food' AND sp.indexable = 1
               JOIN items i ON i.id = n.item_id
               LEFT JOIN nutrition nu ON nu.item_id = n.item_id
               LEFT JOIN item_names nm ON nm.item_id = n.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE n.code = ? AND n.amount IS NOT NULL AND n.amount > 0
                     AND n.quality = 'measured'
               ORDER BY n.amount DESC
               LIMIT ?""", (lang, code, limit))]
    finally:
        conn.close()
    for r in rows:
        portion = servings.for_food(r.get("name"))
        if portion:
            r["serving"] = portion
            r["serving_amount"] = round(r["amount"] * portion["grams"] / 100, 2)
    return rows


def nutrient_corpus_stats(lang, code):
    """How many foods carry a measured value for this component, and the spread.

    Printed on the page so a reader knows what the ranking is a ranking OF:
    「2,338食品中」 is the difference between a fact and a top-ten listicle.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS n, MAX(n.amount) AS top, AVG(n.amount) AS mean,
                      MIN(n.unit) AS unit
               FROM nutrients n
               JOIN site_pages sp ON sp.item_id = n.item_id
                    AND sp.lang = ? AND sp.page_type = 'food' AND sp.indexable = 1
               WHERE n.code = ? AND n.amount IS NOT NULL AND n.amount > 0
                     AND n.quality = 'measured'""", (lang, code)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def nutrient_index(lang, codes):
    """Count, maximum and the food holding it, for many components at once.

    The index page asked two queries per nutrient — 84 of them — and took three
    seconds to answer. One pass over the same rows does it: a window function
    ranks each component's foods, and the outer query keeps the first.
    """
    if not codes:
        return {}
    marks = ",".join("?" * len(codes))
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""WITH ranked AS (
                    SELECT n.code, n.amount, n.unit, sp.slug,
                           COALESCE(nm.name, sp.title) AS name,
                           COUNT(*) OVER (PARTITION BY n.code) AS n_foods,
                           ROW_NUMBER() OVER (PARTITION BY n.code
                                              ORDER BY n.amount DESC) AS rn
                    FROM nutrients n
                    JOIN site_pages sp ON sp.item_id = n.item_id
                         AND sp.lang = ? AND sp.page_type = 'food' AND sp.indexable = 1
                    LEFT JOIN item_names nm ON nm.item_id = n.item_id
                         AND nm.lang = sp.lang AND nm.is_primary = 1
                    WHERE n.code IN ({marks}) AND n.amount IS NOT NULL
                          AND n.amount > 0 AND n.quality = 'measured'
                )
                SELECT code, n_foods, amount AS top, unit, slug, name
                FROM ranked WHERE rn = 1""", (lang, *codes)).fetchall()
    finally:
        conn.close()
    return {r["code"]: dict(r) for r in rows}


# The 47 prefectures, as MAFF's own dataset labels them. A category is a
# prefecture when it is one of these; everything else in items.category is a
# MEXT food group, and the two want different pages.
PREFECTURES = (
    "北海道県", "北海道",
    "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)


def is_prefecture(category):
    return category in PREFECTURES


def prefecture_data(lang, prefecture):
    """One prefecture's regional dishes, and what makes its cooking its own.

    MAFF publishes 「うちの郷土料理」 per prefecture and this corpus costs every
    recipe, so the two together answer something neither does alone: not only
    what 青森県 cooks, but what 青森県 cooks WITH that the rest of the country
    does not.
    """
    conn = get_connection()
    try:
        dishes = [dict(r) for r in conn.execute(
            # No calorie column: a dish is costed from its ingredients at
            # request time and has no stored figure, so the category template's
            # kcal column renders thirty blanks. MAFF's own 主な材料 says more
            # about a regional dish than a number would anyway.
            """SELECT sp.slug, COALESCE(nm.name, sp.title) AS name,
                      rd.region, rd.main_ingredients, rd.occasion
               FROM site_pages sp
               JOIN items i ON i.id = sp.item_id
               JOIN regional_dishes rd ON rd.item_id = i.id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND sp.page_type = 'dish' AND i.category = ?
               ORDER BY sp.title""", (lang, prefecture))]
        if not dishes:
            return None

        # An ingredient is characteristic when this prefecture reaches for it far
        # more often than the country does. Sugar and soy sauce are in everything,
        # so a raw count says nothing; the ratio is what carries the fact.
        signature = [dict(r) for r in conn.execute(
            """WITH here AS (
                   SELECT l.mext_item_id AS iid, COUNT(DISTINCT l.dish_item_id) AS n
                   FROM recipe_ingredient_links l
                   JOIN items d ON d.id = l.dish_item_id AND d.category = ?
                   WHERE l.mext_item_id IS NOT NULL GROUP BY l.mext_item_id
               ), everywhere AS (
                   SELECT mext_item_id AS iid, COUNT(DISTINCT dish_item_id) AS n
                   FROM recipe_ingredient_links
                   WHERE mext_item_id IS NOT NULL GROUP BY mext_item_id
               )
               SELECT COALESCE(nm.name, i.name) AS name, sp.slug,
                      here.n AS used_here, everywhere.n AS used_total
               FROM here JOIN everywhere USING (iid)
               JOIN items i ON i.id = here.iid
               LEFT JOIN site_pages sp ON sp.item_id = i.id AND sp.lang = ?
                    AND sp.page_type = 'food'
               LEFT JOIN item_names nm ON nm.item_id = i.id AND nm.lang = ?
                    AND nm.is_primary = 1
               WHERE here.n >= 2
               ORDER BY (1.0 * here.n / everywhere.n) DESC, here.n DESC
               LIMIT 8""", (prefecture, lang, lang))]
    finally:
        conn.close()

    # Sub-regions as MAFF writes them, minus the ones that just say "everywhere".
    areas = sorted({d["region"] for d in dishes
                    if d.get("region") and "全域" not in d["region"]})
    return {
        "dishes": dishes,
        "n": len(dishes),
        "signature": signature,
        "areas": areas[:12],
    }


def item_image(item_id):
    """The photograph for one item, with what has to be shown beside it.

    Returns None when there is none, which is the common case: about a fifth of
    the regional dishes have a freely-licensed photograph and the rest render
    without one rather than with a picture of something else.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM item_images WHERE item_id = ?", (item_id,)).fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError:
        # The table arrived after the deployed extract was built.
        return None
    finally:
        conn.close()


def images_for(item_ids):
    """{item_id: image} for a list of items, in one query, for index pages."""
    ids = [i for i in item_ids if i]
    if not ids:
        return {}
    conn = get_connection()
    try:
        marks = ",".join("?" * len(ids))
        return {r["item_id"]: dict(r) for r in conn.execute(
            f"SELECT * FROM item_images WHERE item_id IN ({marks})", ids)}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def cooking_yields(lang):
    """Every 重量変化率 MEXT publishes, with the food it belongs to.

    A recipe is written in raw weights and a composition table is written in
    cooked ones, so 100 g of dried hijiki is not 100 g of cooked hijiki — it is
    870 g of it. The rate is the bridge, and MEXT publishes it for 497 foods.
    """
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT cy.rate_percent, cy.method, sp.slug, i.category,
                      COALESCE(nm.name, sp.title) AS name, n.energy_kcal
               FROM cooking_yield cy
               JOIN site_pages sp ON sp.item_id = cy.item_id
                    AND sp.lang = ? AND sp.page_type = 'food'
               JOIN items i ON i.id = cy.item_id
               LEFT JOIN nutrition n ON n.item_id = cy.item_id
               LEFT JOIN item_names nm ON nm.item_id = cy.item_id
                    AND nm.lang = ? AND nm.is_primary = 1
               WHERE cy.rate_percent IS NOT NULL
               ORDER BY i.category, cy.rate_percent DESC""", (lang, lang))]
    finally:
        conn.close()
    for r in rows:
        rate = r["rate_percent"]
        # What 100 g of the raw food becomes, and what that weighs in calories.
        # Stated this way round because a cook measures what goes in.
        r["from_raw_100g"] = round(r["energy_kcal"] * rate / 100, 0) if r["energy_kcal"] else None
    return rows


def atlas_points(lang):
    """Every food with macros, as a point in protein/fat/carb energy space.

    The three shares sum to 100, so each food is one point in a triangle —
    barycentric coordinates straight from the composition table. Returned in
    parallel arrays to keep the payload small.
    """
    # A food's position comes from its composition, which has no language, so
    # the atlas shows the whole corpus on both sites. Only the label and the
    # link localise: prefer this language's page and name, fall back to the
    # other one rather than dropping the point.
    conn = get_connection()
    rows = conn.execute(
        """SELECT COALESCE(own.slug, alt.slug) AS slug,
                  COALESCE(own.lang, alt.lang) AS page_lang,
                  i.category,
                  COALESCE(own_nm.name, alt_nm.name, COALESCE(own.title, alt.title)) AS name,
                  n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
           FROM items i
           JOIN nutrition n ON n.item_id = i.id
           LEFT JOIN site_pages own ON own.item_id = i.id AND own.lang = ?
                AND own.page_type = 'food'
           LEFT JOIN site_pages alt ON alt.item_id = i.id AND alt.lang != ?
                AND alt.page_type = 'food'
           LEFT JOIN item_names own_nm ON own_nm.item_id = i.id AND own_nm.lang = ?
                AND own_nm.is_primary = 1
           LEFT JOIN item_names alt_nm ON alt_nm.item_id = i.id AND alt_nm.lang = 'ja'
                AND alt_nm.is_primary = 1
           WHERE COALESCE(own.slug, alt.slug) IS NOT NULL
           GROUP BY i.id
           ORDER BY i.id""", (lang, lang, lang)).fetchall()
    conn.close()

    groups, gindex = [], {}
    p, f, c, g, names, slugs, kcals = [], [], [], [], [], [], []
    for r in rows:
        split = pfc_energy_split({
            "protein_g": r["protein_g"], "fat_g": r["fat_g"],
            "carbohydrate_g": r["carbohydrate_g"],
        })
        if not split:
            continue                      # no macros -> no position to plot
        cat = r["category"] or ""
        if cat not in gindex:
            gindex[cat] = len(groups)
            groups.append(cat)
        p.append(split["p"]); f.append(split["f"]); c.append(split["c"])
        g.append(gindex[cat])
        names.append(r["name"])
        # Slug carries its own language so a point can link across sites while
        # English names are still being built.
        slugs.append(f'{r["page_lang"]}/{r["slug"]}')
        kcals.append(round(r["energy_kcal"]) if r["energy_kcal"] is not None else None)
    return {"p": p, "f": f, "c": c, "g": g,
            "names": names, "slugs": slugs, "kcal": kcals, "groups": groups}


def browse_foods(lang, page=1, size=48, category=None, sort="name"):
    """Paginated food-database browse. Clean corpus only (site_pages join)."""
    conn = get_connection()
    where = ["sp.lang = ?", "sp.page_type = 'food'"]
    params = [lang]
    if category:
        where.append("i.category = ?")
        params.append(category)
    where_sql = " AND ".join(where)
    total = conn.execute(
        f"""SELECT COUNT(*) c FROM site_pages sp JOIN items i ON i.id = sp.item_id
            WHERE {where_sql}""", params).fetchone()["c"]
    order = {
        "kcal_desc": "n.energy_kcal DESC",
        "kcal_asc": "n.energy_kcal ASC",
        "protein": "n.protein_g DESC",
    }.get(sort, "sp.title")
    rows = [
        dict(r) for r in conn.execute(
            f"""SELECT sp.slug, sp.title, i.category,
                       COALESCE(nm.name, sp.title) AS name,
                       n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
                FROM site_pages sp
                JOIN items i ON i.id = sp.item_id
                LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                     AND nm.lang = sp.lang AND nm.is_primary = 1
                LEFT JOIN nutrition n ON n.item_id = sp.item_id
                WHERE {where_sql}
                ORDER BY {order} LIMIT ? OFFSET ?""",
            params + [size, (page - 1) * size])
    ]
    conn.close()
    return {"rows": rows, "total": total, "page": page, "size": size,
            "pages": max(1, -(-total // size))}


def category_data(lang, ja_category):
    """All pages in one items.category (MEXT food group or MAFF prefecture),
    with per-100g macros where present — the comparison-table page."""
    conn = get_connection()
    rows = [
        dict(r) for r in conn.execute(
            """SELECT sp.slug, sp.page_type, sp.title,
                      COALESCE(nm.name, sp.title) AS name,
                      n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
               FROM site_pages sp
               JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               LEFT JOIN nutrition n ON n.item_id = sp.item_id
               WHERE sp.lang = ? AND i.category = ?
               ORDER BY n.energy_kcal DESC""",
            (lang, ja_category))
    ]
    conn.close()
    if not rows:
        return None
    kcals = [r["energy_kcal"] for r in rows if r["energy_kcal"] is not None]
    return {
        "rows": rows,
        "n": len(rows),
        "kcal_min": min(kcals) if kcals else None,
        "kcal_max": max(kcals) if kcals else None,
        "has_nutrition": bool(kcals),
    }


def sum_micros(item_grams, codes):
    """Deterministic micronutrient totals: sum nutrients rows (per 100 g,
    MEXT laboratory values) scaled by each component's grams.

    item_grams: [(item_id, grams)]; codes: MEXT nutrient codes to include.
    Returns ({code: amount}, n_contributing_items).
    """
    if not item_grams:
        return {}, 0
    conn = get_connection()
    totals = {}
    contributing = set()
    for item_id, grams in item_grams:
        if grams is None:
            continue
        for r in conn.execute(
            "SELECT code, amount FROM nutrients WHERE item_id = ? AND code IN (%s)"
            % ",".join("?" * len(codes)), (item_id, *codes)):
            if r["amount"] is not None:
                totals[r["code"]] = totals.get(r["code"], 0.0) + r["amount"] * grams / 100.0
                contributing.add(item_id)
    conn.close()
    return totals, len(contributing)


ALCOHOLIC = re.compile(
    r"ビール|ハイボール|サワー|チューハイ|酎ハイ|ウイスキー|ウィスキー|焼酎|日本酒|ワイン"
    r"|カクテル|ジン|ラム|ウォッカ|ウオッカ|テキーラ|梅酒|マッコリ|シャンパン|スパークリング"
    r"|生中|生大|角瓶|ホッピー|麦酒|酒$|ブラン$|ロゼ|ヴァン")


def _macros_reconcile(kcal, protein_g, fat_g, carbs_g, fibre_g, name):
    """Whether protein, fat and carbohydrate account for the stated energy.

    Not naive Atwater. Applied as 4/9/4 this rejects 282 of 2,621 MEXT food
    pages — 10.8% — and every one of them is correct: MEXT counts dietary fibre
    at about 2 kcal a gram while 炭水化物 includes it, so agar comes out at 160
    kcal against 330 implied. Counting fibre at 2 takes those 282 down to 15.

    Ethanol is 7 kcal a gram and appears in none of the three columns, so
    spirits report zero macros against 237 kcal and are exempt entirely.

    Both a relative AND an absolute threshold, because on a 8 kcal serving of
    こんにゃく a 6 kcal rounding difference is 75% and means nothing.
    """
    if not kcal or None in (protein_g, fat_g, carbs_g):
        return True
    if menuterms.is_drink(name) or ALCOHOLIC.search(name or ""):
        return True
    fibre = fibre_g or 0
    implied = (protein_g * 4 + fat_g * 9
               + max(carbs_g - fibre, 0) * 4 + fibre * 2)
    gap = abs(implied - kcal)
    return gap <= 50 or gap / kcal <= 0.30


def _row_get(row, key, default=None):
    """sqlite3.Row has no .get, and a database built before a column existed
    does not have it at all."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default

MIN_LINK_CONFIDENCE = 0.7
DISH_COVERAGE_THRESHOLD = 0.6

# Atwater factors — deterministic energy split for the PFC ratio bar.
def pfc_energy_split(nutrition):
    if not nutrition:
        return None
    p = (nutrition.get("protein_g") or 0) * 4
    f = (nutrition.get("fat_g") or 0) * 9
    c = (nutrition.get("carbohydrate_g") or 0) * 4
    total = p + f + c
    if total <= 0:
        return None
    # Largest-remainder rounding: the three shares drive the width of the PFC
    # bar, so they have to sum to exactly 100 — rounding each one on its own
    # leaves a gap at 99 or overflows at 101.
    exact = [p / total * 100, f / total * 100, c / total * 100]
    floors = [int(v) for v in exact]
    short = 100 - sum(floors)
    order = sorted(range(3), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in order[:short]:
        floors[i] += 1
    return {"p": floors[0], "f": floors[1], "c": floors[2]}
    return dict(row) if row else None


def get_names(conn, item_id):
    """{lang: {'primary': name, 'kind': kind, 'aliases': [...]}}"""
    out = {}
    for r in conn.execute(
        "SELECT lang, name, kind, is_primary FROM item_names WHERE item_id = ?"
        " ORDER BY is_primary DESC, id", (item_id,)
    ):
        d = out.setdefault(r["lang"], {"primary": None, "kind": None, "aliases": []})
        if r["is_primary"] and d["primary"] is None:
            d["primary"], d["kind"] = r["name"], r["kind"]
        else:
            d["aliases"].append(r["name"])
    return out


def get_alternates(conn, item_id):
    """{lang: (page_type, slug)} for hreflang / lang switcher."""
    return {
        r["lang"]: (r["page_type"], r["slug"])
        for r in conn.execute(
            "SELECT lang, page_type, slug FROM site_pages WHERE item_id = ?", (item_id,)
        )
    }


def display_name(names, item_row, lang):
    d = names.get(lang) or {}
    return d.get("primary") or item_row["name"]


def get_food_page_data(page):
    item_id, lang = page["item_id"], page["lang"]
    conn = get_connection()
    item = dict(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
    names = get_names(conn, item_id)
    nut = conn.execute("SELECT * FROM nutrition WHERE item_id = ?", (item_id,)).fetchone()
    nutrition = (
        {k: nut[k] for k in ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g")}
        if nut else None
    )
    nutrients = [
        dict(r) for r in conn.execute(
            "SELECT code, name, unit, amount, quality FROM nutrients WHERE item_id = ? ORDER BY id",
            (item_id,))
    ]
    portions = [
        dict(r) for r in conn.execute(
            "SELECT description, gram_weight FROM food_portions WHERE item_id = ? ORDER BY id",
            (item_id,))
    ]
    shelf_life = [
        dict(r) for r in conn.execute(
            "SELECT storage_method, min_days, max_days, tips FROM shelf_life WHERE item_id = ?",
            (item_id,))
    ]
    jdi8 = conn.execute("SELECT score FROM jdi8_scores WHERE item_id = ?", (item_id,)).fetchone()
    # 食塩相当量 (salt equivalent) — expected on Japanese nutrition labels.
    salt_g = next((n["amount"] for n in nutrients if n["code"] == "NACL_EQ"), None)
    # Which of the headline figures MEXT estimated rather than analysed. Energy
    # never is, but protein, fat and carbohydrate are on 12-14% of foods, and
    # those are exactly the numbers the calculator and the FAQ quote.
    _macro_codes = {"energy_kcal": "ENERC_KCAL", "protein_g": "PROT-", "fat_g": "FAT-",
                    "carbohydrate_g": "CHOCDF-", "salt_g": "NACL_EQ"}
    quality_by_code = {n["code"]: n["quality"] for n in nutrients}
    macro_quality = {
        field: quality_by_code.get(code)
        for field, code in _macro_codes.items()
        if quality_by_code.get(code) and quality_by_code.get(code) != "measured"
    }
    # Related: same source+category neighbors that have pages in this lang.
    related = [
        dict(r) for r in conn.execute(
            """SELECT sp.slug, sp.page_type, sp.title, i.id AS item_id,
                      COALESCE(nm.name, sp.title) AS name
               FROM site_pages sp JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND i.category = ? AND i.source = ? AND i.id != ?
               ORDER BY ABS(i.id - ?) LIMIT 8""",
            (lang, item["category"], item["source"], item_id, item_id))
    ]
    # The full MEXT taxonomy path, shown under the heading so the exact source
    # row stays visible even though the heading uses the short display name.
    qual = conn.execute(
        "SELECT name FROM item_names WHERE item_id = ? AND lang = 'ja' AND kind = 'full'",
        (item_id,)).fetchone()
    qualified_name = qual["name"] if qual else None
    alternates = get_alternates(conn, item_id)
    ranks = nutrient_ranks(conn, item, nutrition)
    notable = notable_nutrients(conn, item_id, MICRO_DV.get(lang) or MICRO_DV["ja"])
    # Which of Japan's own labelling criteria this composition would satisfy.
    nutrient_claims = claims.claims_for(nutrients, item["category"])
    conn.close()
    ja_name = (names.get("ja") or {}).get("primary") or item["name"]
    preps = prep_variants(item_id, lang, ja_name)
    # What one serving of this food is, when we have decided. The figures are
    # the same per-100g values scaled deterministically; the portion itself is
    # a kitchen convention and is labelled as one.
    serving = servings.for_food(ja_name)
    if serving and nutrition:
        serving = dict(serving, nutrition=servings.scale(nutrition, serving["grams"]),
                       salt_g=(salt_g * serving["grams"] / 100 if salt_g is not None else None))
    lic, warning = get_license_info(item["source"])
    return {
        "item": item, "names": names, "nutrition": nutrition,
        "nutrients": nutrients, "portions": portions, "shelf_life": shelf_life,
        "jdi8": jdi8["score"] if jdi8 else None,
        "salt_g": salt_g, "macro_quality": macro_quality, "serving": serving,
        "ranks": ranks, "notable": notable, "claims": nutrient_claims,
        "pfc": pfc_energy_split(nutrition),
        "preps": preps, "qualified_name": qualified_name,
        "related": related, "alternates": alternates,
        "license": lic, "license_warning": warning,
    }


# Facts about where a food sits among its neighbours. Not advice, and not a
# health claim: "higher in protein than 92% of 肉類" is a statement about the
# composition table, which is the only thing this site is in a position to
# say. Computed per request — a handful of counting queries over 2,538 rows,
# about 5 ms — rather than precomputed into a table that a later import could
# leave stale.
RANKED = (
    ("energy_kcal", "calories"),
    ("protein_g", "protein"),
    ("fat_g", "fat"),
    ("carbohydrate_g", "carbs"),
)
MIN_PEERS = 20          # below this a percentile says more than it knows


def nutrient_ranks(conn, item, nutrition):
    """[{field, label_key, percentile, peers}] within the food's own group."""
    if not nutrition or not item["category"] or item["category"] == "foundation":
        return []
    out = []
    for field, label_key in RANKED:
        value = nutrition.get(field)
        if value is None:
            continue
        row = conn.execute(
            f"""SELECT COUNT(*) AS peers,
                       SUM(CASE WHEN n.{field} < ? THEN 1 ELSE 0 END) AS below
                FROM nutrition n JOIN items i ON i.id = n.item_id
                WHERE i.category = ? AND i.source = ? AND n.{field} IS NOT NULL""",
            (value, item["category"], item["source"])).fetchone()
        if not row or (row["peers"] or 0) < MIN_PEERS:
            continue
        out.append({
            "field": field, "label_key": label_key,
            "percentile": round((row["below"] or 0) / row["peers"] * 100),
            "peers": row["peers"],
        })
    return out


def notable_nutrients(conn, item_id, dv_table, limit=3):
    """The components this food carries most of, as a share of the Japanese
    labelling reference value. A fact with its basis named, not a claim that
    the food is good for anything."""
    if not dv_table:
        return []
    codes = tuple(dv_table.keys())
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"""SELECT code, name, amount, unit, quality FROM nutrients
            WHERE item_id = ? AND code IN ({marks}) AND amount IS NOT NULL""",
        (item_id, *codes)).fetchall()
    scored = []
    for r in rows:
        label, dv, unit = dv_table[r["code"]]
        if not dv:
            continue
        pct = r["amount"] / dv * 100
        if pct >= 30:            # a third of a day's reference in 100 g
            scored.append({"code": r["code"], "label": label, "amount": r["amount"],
                           "unit": unit, "dv_pct": round(pct), "quality": r["quality"]})
    scored.sort(key=lambda x: -x["dv_pct"])
    return scored[:limit]


def get_dish_page_data(page):
    item_id, lang = page["item_id"], page["lang"]
    conn = get_connection()
    item = dict(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
    names = get_names(conn, item_id)
    rd_row = conn.execute("SELECT * FROM regional_dishes WHERE item_id = ?", (item_id,)).fetchone()
    rd = dict(rd_row) if rd_row else {}

    links = [
        dict(r) for r in conn.execute(
            """SELECT l.*, sp.slug AS mext_slug
               FROM recipe_ingredient_links l
               LEFT JOIN site_pages sp ON sp.item_id = l.mext_item_id AND sp.lang = ?
               WHERE l.dish_item_id = ? ORDER BY l.line_no""",
            (lang, item_id))
    ]
    usable = [
        ln for ln in links
        if ln["mext_item_id"] and (ln["confidence"] or 0) >= MIN_LINK_CONFIDENCE
    ]
    nut_by_item = {}
    if usable:
        ids = [ln["mext_item_id"] for ln in usable]
        q = ",".join("?" * len(ids))
        for r in conn.execute(f"SELECT * FROM nutrition WHERE item_id IN ({q})", ids):
            nut_by_item[r["item_id"]] = {
                k: r[k] for k in ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g")
            }
    computed = dish_nutrition(
        [{"grams": ln["grams"], "mext_item_id": ln["mext_item_id"]} for ln in usable],
        nut_by_item,
    )
    computed["n_total"] = len(links)
    # The weight the figures are for. MAFF recipes are written for a household
    # pot — けの汁 starts with 2kg of daikon — so a bare calorie number reads as
    # a portion and is wrong by an order of magnitude.
    computed["grams"] = round(sum(ln["grams"] for ln in usable if ln["grams"]), 1)
    # Weights the recipe did not state. 「にんじん1本」 is a count, and a carrot
    # is about 150 g rather than exactly 150 g, so the page says how much of
    # its total rests on that assumption.
    # Per 100 g as well as per pot. MAFF recipes are household quantities and
    # only 13 of 1,364 say how many they serve, so the whole-recipe total is
    # not comparable between dishes and per 100 g is.
    if computed["grams"]:
        computed["per_100g"] = {
            k: (v * 100 / computed["grams"] if isinstance(v, (int, float)) else v)
            for k, v in (computed["totals"] or {}).items()
        }
    else:
        computed["per_100g"] = None
    computed["n_assumed"] = sum(
        1 for ln in usable
        if ln["grams"] is not None and _row_get(ln, "grams_source") == "unit")
    show_nutrition = (
        len(links) > 0
        and computed["n_resolved"] >= 2
        and computed["n_resolved"] / len(links) >= DISH_COVERAGE_THRESHOLD
    )
    # Per-ingredient breakdown for the transparent math table.
    breakdown = []
    if show_nutrition:
        for ln in usable:
            per100 = nut_by_item.get(ln["mext_item_id"])
            if per100 and ln["grams"] is not None:
                breakdown.append({
                    "raw_name": ln["raw_name"], "grams": ln["grams"],
                    "kcal": (per100["energy_kcal"] or 0) * ln["grams"] / 100.0,
                    "slug": ln["mext_slug"],
                })

    related = [
        dict(r) for r in conn.execute(
            """SELECT sp.slug, sp.page_type, sp.title,
                      COALESCE(nm.name, sp.title) AS name
               FROM site_pages sp JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND i.category = ? AND i.source = ? AND i.id != ?
               ORDER BY ABS(i.id - ?) LIMIT 8""",
            (lang, item["category"], item["source"], item_id, item_id))
    ]
    alternates = get_alternates(conn, item_id)
    jdi8 = conn.execute("SELECT score FROM jdi8_scores WHERE item_id = ?", (item_id,)).fetchone()
    try:
        img_row = conn.execute(
            "SELECT * FROM item_images WHERE item_id = ?", (item_id,)).fetchone()
        image = dict(img_row) if img_row else None
    except sqlite3.OperationalError:
        image = None      # table newer than the deployed extract
    conn.close()
    lic, warning = get_license_info(item["source"])
    return {
        "item": item, "names": names, "dish": rd, "links": links, "image": image,
        "computed": computed, "show_nutrition": show_nutrition, "breakdown": breakdown,
        "pfc": pfc_energy_split(computed["totals"]) if show_nutrition else None,
        "related": related, "alternates": alternates,
        "jdi8": jdi8["score"] if jdi8 else None,
        "license": lic, "license_warning": warning,
    }


def search(q, lang, limit=20):
    """Search the clean-corpus index. Query tokens are ANDed: tokens of 3+
    chars go through FTS trigram (fast, substring-capable for Japanese);
    shorter tokens (common in Japanese: むね, 生) are LIKE post-filters —
    trigram cannot match under 3 chars."""
    q = (q or "").strip()
    if not q:
        return []
    tokens = q.split()
    long_t = [t for t in tokens if len(t) >= 3]
    short_t = [t for t in tokens if 0 < len(t) < 3]
    conn = get_connection()

    base_select = """
        SELECT f.item_id, sp.slug, sp.page_type, sp.title, n.energy_kcal, i.source,
               COALESCE(nm.name, sp.title) AS name
        FROM search_fts f
        JOIN site_pages sp ON sp.item_id = f.item_id AND sp.lang = ?
        JOIN items i ON i.id = f.item_id
        LEFT JOIN item_names nm ON nm.item_id = f.item_id
             AND nm.lang = sp.lang AND nm.is_primary = 1
        LEFT JOIN nutrition n ON n.item_id = f.item_id
        WHERE f.lang = ?"""
    like_clause = " AND (f.name LIKE ? OR f.category LIKE ?)"

    if long_t:
        match = " AND ".join('"' + t.replace('"', '""') + '"' for t in long_t)
        sql = base_select + " AND search_fts MATCH ?" + like_clause * len(short_t) + \
            " ORDER BY rank LIMIT ?"
        params = [lang, lang, match]
    else:
        sql = base_select + like_clause * len(short_t) + \
            " ORDER BY LENGTH(f.name) LIMIT ?"
        params = [lang, lang]
    for t in short_t:
        params += [f"%{t}%", f"%{t}%"]
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()

    if not rows and long_t:
        # FTS miss (e.g. spelling variant): LIKE-AND over the same index.
        sql = base_select + like_clause * len(tokens) + " ORDER BY LENGTH(f.name) LIMIT ?"
        params = [lang, lang]
        for t in tokens:
            params += [f"%{t}%", f"%{t}%"]
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    conn.close()
    # Source priority: MEXT first, then FDC, then dishes/others, preserving rank inside groups.
    prio = {"MEXT Standard Tables": 0, "USDA FoodData Central": 1}
    return sorted((dict(r) for r in rows), key=lambda r: prio.get(r["source"], 2))


# Everyday staples for the home page (matched against JA names; a real
# popularity signal can replace this once analytics exist).
CURATED_HOME_FOODS = (
    "水稲めし 精白米 うるち米", "にわとり 若どり・主品目 むね 皮なし 生",
    "ぶた 大型種肉 ロース 脂身つき 生", "しろさけ 生", "鶏卵 全卵 生",
    "普通牛乳", "糸引き納豆", "木綿豆腐", "バナナ 生", "りんご 皮なし 生",
    "角形食パン 食パン", "ブロッコリー 花序 生",
)


def corpus_counts(lang="ja"):
    """What the site actually holds, for the pages that describe it.

    Counted rather than written down: an About page quoting a number that has
    drifted from the database is worse than one quoting none.
    """
    conn = get_connection()
    counts = {
        r["page_type"]: r["c"] for r in conn.execute(
            "SELECT page_type, COUNT(*) c FROM site_pages WHERE lang = ? GROUP BY page_type",
            (lang,))
    }
    nutrients = conn.execute(
        """SELECT MAX(c) m FROM (SELECT COUNT(*) c FROM nutrients GROUP BY item_id)""").fetchone()
    conn.close()
    return {
        "foods": counts.get("food", 0),
        "dishes": counts.get("dish", 0),
        "nutrients": (nutrients["m"] if nutrients else 0) or 0,
    }


def home_data(lang):
    conn = get_connection()
    counts = {
        r["page_type"]: r["c"] for r in conn.execute(
            "SELECT page_type, COUNT(*) c FROM site_pages WHERE page_type IS NOT NULL AND lang = ? GROUP BY page_type",
            (lang,))
    }
    foods, seen = [], set()
    for term in CURATED_HOME_FOODS:
        r = conn.execute(
            """SELECT sp.slug, sp.title, n.energy_kcal,
                      COALESCE(dn.name, sp.title) AS name
               FROM item_names nm
               JOIN site_pages sp ON sp.item_id = nm.item_id AND sp.lang = ? AND sp.page_type = 'food'
               JOIN nutrition n ON n.item_id = nm.item_id
               LEFT JOIN item_names dn ON dn.item_id = nm.item_id
                    AND dn.lang = sp.lang AND dn.is_primary = 1
               WHERE nm.lang = 'ja' AND nm.name LIKE ? LIMIT 1""",
            (lang, f"%{term}%")).fetchone()
        if r and r["slug"] not in seen:
            seen.add(r["slug"])
            foods.append(dict(r))
    if len(foods) < 12:
        for r in conn.execute(
            """SELECT sp.slug, sp.title, n.energy_kcal,
                      COALESCE(nm.name, sp.title) AS name
               FROM site_pages sp
               JOIN nutrition n ON n.item_id = sp.item_id
               JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND sp.page_type = 'food'
               ORDER BY CASE i.source WHEN 'MEXT Standard Tables' THEN 0 ELSE 1 END,
                        sp.item_id LIMIT 12""", (lang,)):
            if r["slug"] not in seen and len(foods) < 12:
                seen.add(r["slug"])
                foods.append(dict(r))
    # One dish per prefecture for variety.
    dishes = [
        dict(r) for r in conn.execute(
            """SELECT sp.slug, sp.title, i.category, MIN(sp.item_id),
                      COALESCE(nm.name, sp.title) AS name
               FROM site_pages sp JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND sp.page_type = 'dish'
               GROUP BY i.category ORDER BY i.category LIMIT 12""", (lang,))
    ]
    categories = [
        dict(r) for r in conn.execute(
            """SELECT i.category, COUNT(*) c FROM items i
               JOIN site_pages sp ON sp.item_id = i.id AND sp.lang = ?
               WHERE i.source = 'MEXT Standard Tables'
               GROUP BY i.category ORDER BY c DESC""", (lang,))
    ]
    # The atlas only earns the hero slot when there are enough foods to show a
    # shape. English stays below this until the name translations are built.
    # Counts every food that has a page in either language, matching what the
    # atlas actually plots.
    atlas_count = conn.execute(
        """SELECT COUNT(DISTINCT sp.item_id) c FROM site_pages sp
           JOIN nutrition n ON n.item_id = sp.item_id
           WHERE sp.page_type = 'food' AND n.energy_kcal IS NOT NULL""").fetchone()["c"]
    conn.close()
    return {"counts": counts, "foods": foods, "dishes": dishes,
            "categories": categories, "atlas_count": atlas_count}


# MEXT encodes preparation as the final token of a food name, so the same food
# appears as separate rows (うどん 生 / うどん ゆで). Grouping them turns 693
# rows into real "how cooking changes the numbers" comparisons — measured,
# not estimated.
PREP_TOKENS = (
    "生", "ゆで", "焼き", "乾", "水煮", "油いため", "蒸し", "天ぷら", "フライ",
    "素揚げ", "ソテー", "電子レンジ調理", "いり", "冷凍", "水煮缶詰", "缶詰",
    "素干し", "煮干し", "つくだ煮", "塩漬", "塩抜き", "味付け", "浸出液",
)
PREP_LABELS_EN = {
    "生": "Raw", "ゆで": "Boiled", "焼き": "Grilled", "乾": "Dried",
    "水煮": "Simmered in water", "油いため": "Stir-fried in oil", "蒸し": "Steamed",
    "天ぷら": "Tempura", "フライ": "Deep-fried, breaded", "素揚げ": "Deep-fried, plain",
    "ソテー": "Sautéed", "電子レンジ調理": "Microwaved", "いり": "Dry-roasted",
    "冷凍": "Frozen", "水煮缶詰": "Canned in water", "缶詰": "Canned",
    "素干し": "Sun-dried", "煮干し": "Dried (niboshi)", "つくだ煮": "Simmered in soy",
    "塩漬": "Salted", "塩抜き": "Desalted", "味付け": "Seasoned", "浸出液": "Infusion",
}


def split_prep(name):
    """('うどん 生') -> ('うどん', '生'); returns (name, None) if no prep token."""
    parts = name.split()
    if len(parts) > 1 and parts[-1] in PREP_TOKENS:
        return " ".join(parts[:-1]), parts[-1]
    return name, None


def prep_variants(item_id, lang, ja_name):
    """Sibling items that are the same food prepared differently."""
    base, prep = split_prep(ja_name)
    if not prep:
        return []
    conn = get_connection()
    rows = conn.execute(
        """SELECT nm.item_id, nm.name AS ja_name, sp.slug, sp.title,
                  n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g,
                  cy.rate_percent
           FROM item_names nm
           JOIN items i ON i.id = nm.item_id AND i.source = 'MEXT Standard Tables'
           JOIN site_pages sp ON sp.item_id = nm.item_id AND sp.lang = ?
           LEFT JOIN nutrition n ON n.item_id = nm.item_id
           LEFT JOIN cooking_yield cy ON cy.item_id = nm.item_id
           WHERE nm.lang = 'ja' AND nm.is_primary = 1 AND nm.name LIKE ?
           ORDER BY n.energy_kcal DESC""",
        (lang, base + " %")).fetchall()
    conn.close()
    out = []
    for r in rows:
        b, p = split_prep(r["ja_name"])
        if b != base or not p:
            continue
        out.append({
            "item_id": r["item_id"], "slug": r["slug"],
            "prep": PREP_LABELS_EN.get(p, p) if lang == "en" else p,
            "is_current": r["item_id"] == item_id,
            "energy_kcal": r["energy_kcal"], "protein_g": r["protein_g"],
            "fat_g": r["fat_g"], "carbohydrate_g": r["carbohydrate_g"],
            # 100 g of the raw food becomes this much once cooked, so the
            # cooked row can also be read as "what that raw 100 g became".
            "yield_pct": _row_get(r, "rate_percent"),
            "from_raw_100g": (
                r["energy_kcal"] * _row_get(r, "rate_percent") / 100
                if r["energy_kcal"] is not None and _row_get(r, "rate_percent") else None),
        })
    return out if len(out) > 1 else []


def cooking_effect(lang, limit=40):
    """Foods that appear in the table both raw and cooked, ranked by how much
    the preparation changes their energy density.

    This is the comparison a reader actually wants — and unlike written guides
    that estimate it, both numbers here are separate laboratory analyses.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT nm.item_id, nm.name, sp.slug, i.category, n.energy_kcal,
                  n.protein_g, n.fat_g, n.carbohydrate_g
           FROM item_names nm
           JOIN items i ON i.id = nm.item_id AND i.source = 'MEXT Standard Tables'
           JOIN site_pages sp ON sp.item_id = nm.item_id AND sp.lang = ?
           JOIN nutrition n ON n.item_id = nm.item_id
           WHERE nm.lang = 'ja' AND nm.is_primary = 1 AND n.energy_kcal IS NOT NULL""",
        (lang,)).fetchall()
    conn.close()

    families = {}
    for r in rows:
        base, prep = split_prep(r["name"])
        if not prep:
            continue
        families.setdefault(base, []).append({
            "prep": PREP_LABELS_EN.get(prep, prep) if lang == "en" else prep,
            "slug": r["slug"], "category": r["category"],
            "kcal": r["energy_kcal"], "protein_g": r["protein_g"],
            "fat_g": r["fat_g"], "carbohydrate_g": r["carbohydrate_g"],
            "base": base,
        })

    out = []
    for base, members in families.items():
        if len(members) < 2:
            continue
        lo = min(members, key=lambda m: m["kcal"])
        hi = max(members, key=lambda m: m["kcal"])
        if lo["kcal"] <= 0 or hi is lo:
            continue
        out.append({
            "base": base, "category": members[0]["category"],
            "low": lo, "high": hi,
            "ratio": hi["kcal"] / lo["kcal"],
            "delta": hi["kcal"] - lo["kcal"],
            "n": len(members),
        })
    out.sort(key=lambda x: -x["ratio"])
    return {"rows": out[:limit], "total": len(out)}


def group_ranking(lang, ja_category, metric="protein_g", limit=25):
    """Top foods in one group by a chosen measurement."""
    if metric not in ("protein_g", "fat_g", "carbohydrate_g", "energy_kcal"):
        return None
    conn = get_connection()
    rows = [
        dict(r) for r in conn.execute(
            f"""SELECT sp.slug, COALESCE(nm.name, sp.title) AS name,
                       n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
                FROM site_pages sp
                JOIN items i ON i.id = sp.item_id
                JOIN nutrition n ON n.item_id = sp.item_id
                LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                     AND nm.lang = sp.lang AND nm.is_primary = 1
                WHERE sp.lang = ? AND i.category = ? AND n.{metric} IS NOT NULL
                ORDER BY n.{metric} DESC LIMIT ?""",
            (lang, ja_category, limit))
    ]
    conn.close()
    return rows


def nutrient_ranking(lang, code, limit=60):
    """Foods carrying the most of one component, per 100 g.

    Measured values only. A value MEXT prints in parentheses is its own estimate
    for that food, and a ranking is a claim that THIS food holds more than THAT
    one — an estimate cannot settle it, and a `Tr` is not a quantity at all.

    Serving figures ride along where the portion table knows one, because
    「100 g あたり」 is not how anyone eats seaweed or liver.
    """
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT sp.slug, COALESCE(nm.name, sp.title) AS name, i.category,
                      n.amount, n.unit, n.name AS nutrient_name,
                      nu.energy_kcal
               FROM nutrients n
               JOIN site_pages sp ON sp.item_id = n.item_id
                    AND sp.lang = ? AND sp.page_type = 'food' AND sp.indexable = 1
               JOIN items i ON i.id = n.item_id
               LEFT JOIN nutrition nu ON nu.item_id = n.item_id
               LEFT JOIN item_names nm ON nm.item_id = n.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE n.code = ? AND n.amount IS NOT NULL AND n.amount > 0
                     AND n.quality = 'measured'
               ORDER BY n.amount DESC
               LIMIT ?""", (lang, code, limit))]
    finally:
        conn.close()
    for r in rows:
        portion = servings.for_food(r.get("name"))
        if portion:
            r["serving"] = portion
            r["serving_amount"] = round(r["amount"] * portion["grams"] / 100, 2)
    return rows


def nutrient_corpus_stats(lang, code):
    """How many foods carry a measured value for this component, and the spread.

    Printed on the page so a reader knows what the ranking is a ranking OF:
    「2,338食品中」 is the difference between a fact and a top-ten listicle.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS n, MAX(n.amount) AS top, AVG(n.amount) AS mean,
                      MIN(n.unit) AS unit
               FROM nutrients n
               JOIN site_pages sp ON sp.item_id = n.item_id
                    AND sp.lang = ? AND sp.page_type = 'food' AND sp.indexable = 1
               WHERE n.code = ? AND n.amount IS NOT NULL AND n.amount > 0
                     AND n.quality = 'measured'""", (lang, code)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def nutrient_index(lang, codes):
    """Count, maximum and the food holding it, for many components at once.

    The index page asked two queries per nutrient — 84 of them — and took three
    seconds to answer. One pass over the same rows does it: a window function
    ranks each component's foods, and the outer query keeps the first.
    """
    if not codes:
        return {}
    marks = ",".join("?" * len(codes))
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""WITH ranked AS (
                    SELECT n.code, n.amount, n.unit, sp.slug,
                           COALESCE(nm.name, sp.title) AS name,
                           COUNT(*) OVER (PARTITION BY n.code) AS n_foods,
                           ROW_NUMBER() OVER (PARTITION BY n.code
                                              ORDER BY n.amount DESC) AS rn
                    FROM nutrients n
                    JOIN site_pages sp ON sp.item_id = n.item_id
                         AND sp.lang = ? AND sp.page_type = 'food' AND sp.indexable = 1
                    LEFT JOIN item_names nm ON nm.item_id = n.item_id
                         AND nm.lang = sp.lang AND nm.is_primary = 1
                    WHERE n.code IN ({marks}) AND n.amount IS NOT NULL
                          AND n.amount > 0 AND n.quality = 'measured'
                )
                SELECT code, n_foods, amount AS top, unit, slug, name
                FROM ranked WHERE rn = 1""", (lang, *codes)).fetchall()
    finally:
        conn.close()
    return {r["code"]: dict(r) for r in rows}


# The 47 prefectures, as MAFF's own dataset labels them. A category is a
# prefecture when it is one of these; everything else in items.category is a
# MEXT food group, and the two want different pages.
PREFECTURES = (
    "北海道県", "北海道",
    "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)


def is_prefecture(category):
    return category in PREFECTURES


def prefecture_data(lang, prefecture):
    """One prefecture's regional dishes, and what makes its cooking its own.

    MAFF publishes 「うちの郷土料理」 per prefecture and this corpus costs every
    recipe, so the two together answer something neither does alone: not only
    what 青森県 cooks, but what 青森県 cooks WITH that the rest of the country
    does not.
    """
    conn = get_connection()
    try:
        dishes = [dict(r) for r in conn.execute(
            # No calorie column: a dish is costed from its ingredients at
            # request time and has no stored figure, so the category template's
            # kcal column renders thirty blanks. MAFF's own 主な材料 says more
            # about a regional dish than a number would anyway.
            """SELECT sp.slug, COALESCE(nm.name, sp.title) AS name,
                      rd.region, rd.main_ingredients, rd.occasion
               FROM site_pages sp
               JOIN items i ON i.id = sp.item_id
               JOIN regional_dishes rd ON rd.item_id = i.id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               WHERE sp.lang = ? AND sp.page_type = 'dish' AND i.category = ?
               ORDER BY sp.title""", (lang, prefecture))]
        if not dishes:
            return None

        # An ingredient is characteristic when this prefecture reaches for it far
        # more often than the country does. Sugar and soy sauce are in everything,
        # so a raw count says nothing; the ratio is what carries the fact.
        signature = [dict(r) for r in conn.execute(
            """WITH here AS (
                   SELECT l.mext_item_id AS iid, COUNT(DISTINCT l.dish_item_id) AS n
                   FROM recipe_ingredient_links l
                   JOIN items d ON d.id = l.dish_item_id AND d.category = ?
                   WHERE l.mext_item_id IS NOT NULL GROUP BY l.mext_item_id
               ), everywhere AS (
                   SELECT mext_item_id AS iid, COUNT(DISTINCT dish_item_id) AS n
                   FROM recipe_ingredient_links
                   WHERE mext_item_id IS NOT NULL GROUP BY mext_item_id
               )
               SELECT COALESCE(nm.name, i.name) AS name, sp.slug,
                      here.n AS used_here, everywhere.n AS used_total
               FROM here JOIN everywhere USING (iid)
               JOIN items i ON i.id = here.iid
               LEFT JOIN site_pages sp ON sp.item_id = i.id AND sp.lang = ?
                    AND sp.page_type = 'food'
               LEFT JOIN item_names nm ON nm.item_id = i.id AND nm.lang = ?
                    AND nm.is_primary = 1
               WHERE here.n >= 2
               ORDER BY (1.0 * here.n / everywhere.n) DESC, here.n DESC
               LIMIT 8""", (prefecture, lang, lang))]
    finally:
        conn.close()

    # Sub-regions as MAFF writes them, minus the ones that just say "everywhere".
    areas = sorted({d["region"] for d in dishes
                    if d.get("region") and "全域" not in d["region"]})
    return {
        "dishes": dishes,
        "n": len(dishes),
        "signature": signature,
        "areas": areas[:12],
    }


def item_image(item_id):
    """The photograph for one item, with what has to be shown beside it.

    Returns None when there is none, which is the common case: about a fifth of
    the regional dishes have a freely-licensed photograph and the rest render
    without one rather than with a picture of something else.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM item_images WHERE item_id = ?", (item_id,)).fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError:
        # The table arrived after the deployed extract was built.
        return None
    finally:
        conn.close()


def images_for(item_ids):
    """{item_id: image} for a list of items, in one query, for index pages."""
    ids = [i for i in item_ids if i]
    if not ids:
        return {}
    conn = get_connection()
    try:
        marks = ",".join("?" * len(ids))
        return {r["item_id"]: dict(r) for r in conn.execute(
            f"SELECT * FROM item_images WHERE item_id IN ({marks})", ids)}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def cooking_yields(lang):
    """Every 重量変化率 MEXT publishes, with the food it belongs to.

    A recipe is written in raw weights and a composition table is written in
    cooked ones, so 100 g of dried hijiki is not 100 g of cooked hijiki — it is
    870 g of it. The rate is the bridge, and MEXT publishes it for 497 foods.
    """
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT cy.rate_percent, cy.method, cy.base, sp.slug, i.category,
                      COALESCE(nm.name, sp.title) AS name, n.energy_kcal
               FROM cooking_yield cy
               JOIN site_pages sp ON sp.item_id = cy.item_id
                    AND sp.lang = ? AND sp.page_type = 'food'
               JOIN items i ON i.id = cy.item_id
               LEFT JOIN nutrition n ON n.item_id = cy.item_id
               LEFT JOIN item_names nm ON nm.item_id = cy.item_id
                    AND nm.lang = ? AND nm.is_primary = 1
               WHERE cy.rate_percent IS NOT NULL
               ORDER BY i.category, cy.rate_percent DESC""", (lang, lang))]
        before = _raw_food_index(conn, lang)
    finally:
        conn.close()
    for r in rows:
        rate = r["rate_percent"]
        # What 100 g of the raw food becomes, and what that weighs in calories.
        # Stated this way round because a cook measures what goes in.
        r["from_raw_100g"] = round(r["energy_kcal"] * rate / 100, 0) if r["energy_kcal"] else None
        # One row in 497 is a percentage of the BOILED weight rather than the
        # raw food, and it is not this table's job to hide that.
        r["before"] = None if r.get("base") else before.get(_yield_stem(r["name"]))
    return rows


def atlas_points(lang):
    """Every food with macros, as a point in protein/fat/carb energy space.

    The three shares sum to 100, so each food is one point in a triangle —
    barycentric coordinates straight from the composition table. Returned in
    parallel arrays to keep the payload small.
    """
    # A food's position comes from its composition, which has no language, so
    # the atlas shows the whole corpus on both sites. Only the label and the
    # link localise: prefer this language's page and name, fall back to the
    # other one rather than dropping the point.
    conn = get_connection()
    rows = conn.execute(
        """SELECT COALESCE(own.slug, alt.slug) AS slug,
                  COALESCE(own.lang, alt.lang) AS page_lang,
                  i.category,
                  COALESCE(own_nm.name, alt_nm.name, COALESCE(own.title, alt.title)) AS name,
                  n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
           FROM items i
           JOIN nutrition n ON n.item_id = i.id
           LEFT JOIN site_pages own ON own.item_id = i.id AND own.lang = ?
                AND own.page_type = 'food'
           LEFT JOIN site_pages alt ON alt.item_id = i.id AND alt.lang != ?
                AND alt.page_type = 'food'
           LEFT JOIN item_names own_nm ON own_nm.item_id = i.id AND own_nm.lang = ?
                AND own_nm.is_primary = 1
           LEFT JOIN item_names alt_nm ON alt_nm.item_id = i.id AND alt_nm.lang = 'ja'
                AND alt_nm.is_primary = 1
           WHERE COALESCE(own.slug, alt.slug) IS NOT NULL
           GROUP BY i.id
           ORDER BY i.id""", (lang, lang, lang)).fetchall()
    conn.close()

    groups, gindex = [], {}
    p, f, c, g, names, slugs, kcals = [], [], [], [], [], [], []
    for r in rows:
        split = pfc_energy_split({
            "protein_g": r["protein_g"], "fat_g": r["fat_g"],
            "carbohydrate_g": r["carbohydrate_g"],
        })
        if not split:
            continue                      # no macros -> no position to plot
        cat = r["category"] or ""
        if cat not in gindex:
            gindex[cat] = len(groups)
            groups.append(cat)
        p.append(split["p"]); f.append(split["f"]); c.append(split["c"])
        g.append(gindex[cat])
        names.append(r["name"])
        # Slug carries its own language so a point can link across sites while
        # English names are still being built.
        slugs.append(f'{r["page_lang"]}/{r["slug"]}')
        kcals.append(round(r["energy_kcal"]) if r["energy_kcal"] is not None else None)
    return {"p": p, "f": f, "c": c, "g": g,
            "names": names, "slugs": slugs, "kcal": kcals, "groups": groups}


def browse_foods(lang, page=1, size=48, category=None, sort="name"):
    """Paginated food-database browse. Clean corpus only (site_pages join)."""
    conn = get_connection()
    where = ["sp.lang = ?", "sp.page_type = 'food'"]
    params = [lang]
    if category:
        where.append("i.category = ?")
        params.append(category)
    where_sql = " AND ".join(where)
    total = conn.execute(
        f"""SELECT COUNT(*) c FROM site_pages sp JOIN items i ON i.id = sp.item_id
            WHERE {where_sql}""", params).fetchone()["c"]
    order = {
        "kcal_desc": "n.energy_kcal DESC",
        "kcal_asc": "n.energy_kcal ASC",
        "protein": "n.protein_g DESC",
    }.get(sort, "sp.title")
    rows = [
        dict(r) for r in conn.execute(
            f"""SELECT sp.slug, sp.title, i.category,
                       COALESCE(nm.name, sp.title) AS name,
                       n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
                FROM site_pages sp
                JOIN items i ON i.id = sp.item_id
                LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                     AND nm.lang = sp.lang AND nm.is_primary = 1
                LEFT JOIN nutrition n ON n.item_id = sp.item_id
                WHERE {where_sql}
                ORDER BY {order} LIMIT ? OFFSET ?""",
            params + [size, (page - 1) * size])
    ]
    conn.close()
    return {"rows": rows, "total": total, "page": page, "size": size,
            "pages": max(1, -(-total // size))}


def category_data(lang, ja_category):
    """All pages in one items.category (MEXT food group or MAFF prefecture),
    with per-100g macros where present — the comparison-table page."""
    conn = get_connection()
    rows = [
        dict(r) for r in conn.execute(
            """SELECT sp.slug, sp.page_type, sp.title,
                      COALESCE(nm.name, sp.title) AS name,
                      n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
               FROM site_pages sp
               JOIN items i ON i.id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = sp.lang AND nm.is_primary = 1
               LEFT JOIN nutrition n ON n.item_id = sp.item_id
               WHERE sp.lang = ? AND i.category = ?
               ORDER BY n.energy_kcal DESC""",
            (lang, ja_category))
    ]
    conn.close()
    if not rows:
        return None
    kcals = [r["energy_kcal"] for r in rows if r["energy_kcal"] is not None]
    return {
        "rows": rows,
        "n": len(rows),
        "kcal_min": min(kcals) if kcals else None,
        "kcal_max": max(kcals) if kcals else None,
        "has_nutrition": bool(kcals),
    }


def sum_micros(item_grams, codes):
    """Deterministic micronutrient totals: sum nutrients rows (per 100 g,
    MEXT laboratory values) scaled by each component's grams.

    item_grams: [(item_id, grams)]; codes: MEXT nutrient codes to include.
    Returns ({code: amount}, n_contributing_items).
    """
    if not item_grams:
        return {}, 0
    conn = get_connection()
    totals = {}
    contributing = set()
    for item_id, grams in item_grams:
        if grams is None:
            continue
        for r in conn.execute(
            "SELECT code, amount FROM nutrients WHERE item_id = ? AND code IN (%s)"
            % ",".join("?" * len(codes)), (item_id, *codes)):
            if r["amount"] is not None:
                totals[r["code"]] = totals.get(r["code"], 0.0) + r["amount"] * grams / 100.0
                contributing.add(item_id)
    conn.close()
    return totals, len(contributing)


def food_nutrition_json(item_id):
    """Per-100g full-precision macros + portions, only for items with a page
    (clean corpus gate)."""
    conn = get_connection()
    page = conn.execute(
        "SELECT item_id FROM site_pages WHERE item_id = ? LIMIT 1", (item_id,)
    ).fetchone()
    if not page:
        conn.close()
        return None
    item = conn.execute("SELECT id, name, source FROM items WHERE id = ?", (item_id,)).fetchone()
    nut = conn.execute("SELECT * FROM nutrition WHERE item_id = ?", (item_id,)).fetchone()
    portions = [
        dict(r) for r in conn.execute(
            "SELECT description, gram_weight FROM food_portions WHERE item_id = ?", (item_id,))
    ]
    nutrients = food_nutrients(conn, item_id)
    yields = food_cooking_yield(conn, item_id)
    names = get_names(conn, item_id)
    conn.close()
    lic, _ = get_license_info(item["source"])
    return {
        "item_id": item["id"],
        "name": {lang: d.get("primary") for lang, d in names.items()} or {"ja": item["name"]},
        "source": item["source"],
        "license": lic,
        "per_100g": (
            {k: nut[k] for k in ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g")}
            if nut else None
        ),
        "nutrients": nutrients,
        "cooking_yield": yields,
        "portions": portions,
    }


def food_nutrients(conn, item_id):
    """Every published value for a food, each carrying how it was arrived at.

    `per_100g` above is four numbers with nothing attached, which is fine for a
    page that renders its own footnote and wrong for anything reading over the
    wire: 15.8% of what MEXT publishes is a parenthesised estimate and `Tr` is
    stored as a zero. A consumer that cannot tell those apart will restate an
    estimate as a measurement.

    quality is 'measured' | 'estimated' | 'trace'. Salt (NACL_EQ) and the
    micronutrients live here too — they are not in the `nutrition` table.
    """
    return [dict(r) for r in conn.execute(
        """SELECT code, name, unit, amount, quality
           FROM nutrients WHERE item_id = ? ORDER BY id""", (item_id,))]


def food_cooking_yield(conn, item_id):
    """The 重量変化率 rows MEXT publishes for this food, if any."""
    return [dict(r) for r in conn.execute(
        """SELECT method, rate_percent FROM cooking_yield
           WHERE item_id = ? AND rate_percent IS NOT NULL
           ORDER BY rate_percent""", (item_id,))]


def cooking_yield_search(q, lang="ja", limit=20):
    """Weight-change rates by food name, for callers that have a name not an id.

    Same clean-corpus gate as everything else here: joined through site_pages,
    so an ODbL row cannot answer.
    """
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT cy.item_id, COALESCE(nm.name, sp.title) AS name,
                      cy.method, cy.rate_percent, sp.slug
               FROM cooking_yield cy
               JOIN site_pages sp ON sp.item_id = cy.item_id
                    AND sp.lang = ? AND sp.page_type = 'food'
               LEFT JOIN item_names nm ON nm.item_id = cy.item_id
                    AND nm.lang = ? AND nm.is_primary = 1
               WHERE cy.rate_percent IS NOT NULL
                 AND COALESCE(nm.name, sp.title) LIKE ?
               ORDER BY cy.rate_percent
               LIMIT ?""", (lang, lang, f"%{q}%", limit))]
    finally:
        conn.close()


# ---------------------------------------------------------------- sitemaps

SITEMAP_SECTIONS = ("foods", "dishes", "shops", "categories", "nutrients", "column", "pages")
STATIC_PAGES = ("", "foods", "menu", "nutrients", "cooking-yield", "meal-calculator",
                "analyzer", "goals", "sources", "api", "column", "embed",
                "guides/cooking-and-calories", "about", "privacy", "terms", "contact")

# Routes that serve HTML and are deliberately kept out of the sitemap. Named
# here rather than merely absent, so the test below can tell "excluded on
# purpose" from "someone added a page and forgot".
UNLISTED_PAGES = frozenset({
    "/search",           # a query's results are thin and duplicate the pages they link to
    "/embed/analyzer",   # the widget itself; noindex, canonical to /analyzer
})


def sitemap_slugs(lang, section):
    """The paths one sitemap section covers, straight from the database.

    Built per request rather than read from files: the generated files live
    under data/, which is not in the repository or the image, so production
    served an empty sitemap index for every one of its 4,072 pages. Querying
    is cheap, and it cannot go stale against the pages it lists.
    """
    conn = get_connection()
    try:
        if section in ("foods", "dishes"):
            ptype = "food" if section == "foods" else "dish"
            return [f"/{ptype}/{r['slug']}" for r in conn.execute(
                "SELECT slug FROM site_pages WHERE indexable = 1 AND lang = ?"
                " AND page_type = ? ORDER BY id", (lang, ptype))]
        if section == "categories":
            return [f"/category/{r['category']}" for r in conn.execute(
                """SELECT i.category FROM items i
                   JOIN site_pages sp ON sp.item_id = i.id AND sp.lang = ?
                   WHERE i.category IS NOT NULL AND i.category != 'foundation'
                   GROUP BY i.category ORDER BY i.category""", (lang,))]
        if section == "shops":
            # indexable = 1 only: a chain menu page earns its sitemap slot by
            # carrying enough published calorie figures (scripts/build_shops).
            return [f"/menu/{r['slug']}" for r in conn.execute(
                "SELECT slug FROM shop_pages WHERE indexable = 1 AND lang = ?"
                " ORDER BY id", (lang,))]
        if section == "column":
            # The module and its tables are named `blog`; the site says コラム,
            # which is what a Japanese reader calls this kind of page.
            from ..blog import store as blog_store
            return [f"/column/{slug}" for slug in blog_store.slugs()]
        if section == "nutrients":
            from . import nutrient_pages
            return [f"/nutrient/{slug}" for slug in nutrient_pages.SLUGS]
        if section == "pages":
            return [f"/{p}" for p in STATIC_PAGES]
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------- chain menus

ROMAJI_CHAIN_ALIASES = {
    "sushiro": "スシロー",
    "hamazushi": "はま寿司",
    "hama-sushi": "はま寿司",
    "kurasushi": "くら寿司",
    "kura-sushi": "くら寿司",
    "mcdonalds": "マクドナルド",
    "mcdonald": "マクドナルド",
    "saizeriya": "サイゼリヤ",
    "saize": "サイゼリヤ",
    "yoshinoya": "吉野家",
    "matsuya": "松屋",
    "sukiya": "すき家",
    "mosburger": "モスバーガー",
    "mos-burger": "モスバーガー",
    "marugame": "丸亀製麺",
    "marugame-seimen": "丸亀製麺",
    "cocoichi": "カレーハウスCoCo壱番屋",
    "coco-ichibanya": "カレーハウスCoCo壱番屋",
    "ootoya": "大戸屋",
    "otoya": "大戸屋",
    "yayoiken": "やよい軒",
    "yayoi-ken": "やよい軒",
    "katsuya": "かつや",
    "tenya": "天丼てんや",
    "ippudo": "一風堂",
    "ichiran": "一蘭",
    "komeda": "コメダ珈琲店",
    "doutor": "ドトールコーヒー",
    "tullys": "タリーズコーヒー",
    "starbucks": "スターバックス-コーヒー",
    "gusto": "ガスト",
    "dennys": "デニーズ",
    "jonathan": "ジョナサン",
    "bamiyan": "バーミヤン",
    "bikkuri-donkey": "びっくりドンキー",
    "ringer-hut": "リンガーハット",
    "gyukaku": "牛角",
    "torikizoku": "鳥貴族",
    "hidakaya": "日高屋",
    "fujisoba": "名代富士そば",
    "hoshino": "星乃珈琲店",
}


def get_shop_page(lang, slug):
    """The shop_pages row for a slug, or None."""
    conn = get_connection()
    try:
        # 1. Exact match
        row = conn.execute(
            "SELECT * FROM shop_pages WHERE lang = ? AND slug = ?", (lang, slug)).fetchone()
        if row:
            return dict(row)

        # 2. Known romaji alias
        norm = (slug or "").lower().strip()
        if norm in ROMAJI_CHAIN_ALIASES:
            alias_slug = ROMAJI_CHAIN_ALIASES[norm]
            row = conn.execute(
                "SELECT * FROM shop_pages WHERE lang = ? AND slug = ?", (lang, alias_slug)).fetchone()
            if row:
                return dict(row)

        # 3. Case-insensitive slug match
        row = conn.execute(
            "SELECT * FROM shop_pages WHERE lang = ? AND slug = ? COLLATE NOCASE", (lang, slug)).fetchone()
        if row:
            return dict(row)

        # 4. Match by shop name
        row = conn.execute(
            """SELECT sp.* FROM shop_pages sp
               JOIN shops s ON s.id = sp.shop_id
               WHERE sp.lang = ? AND (s.name = ? OR s.name = ? COLLATE NOCASE)""",
            (lang, slug, slug)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_shop_page_data(page):
    """Everything one chain-menu page renders.

    ATTRIBUTION IS STRUCTURAL HERE. A calorie figure is only carried out of this
    function together with the source it came from, so a template cannot print a
    number that has no provenance — the row simply has no `kcal` without one.
    Dishes the chain has not published a figure for come back with kcal None and
    render as 「未公表」, which is the honest answer and the one we can defend.
    """
    conn = get_connection()
    try:
        shop = conn.execute(
            "SELECT * FROM shops WHERE id = ?", (page["shop_id"],)).fetchone()
        rows = conn.execute(
            """SELECT smi.id AS item_id_pk, smi.name, smi.price_yen, smi.price_max_yen, smi.tax_incl,
                      smi.mealtime, smi.position,
                      cn.energy_kcal AS chain_kcal, cn.protein_g AS chain_p,
                      cn.fat_g AS chain_f, cn.carbohydrate_g AS chain_c, cn.salt_g AS chain_salt,
                      cn.name AS official_name,
                      cn.source_page, cn.source_url, cn.source_updated,
                      n.energy_kcal AS table_kcal, n.protein_g AS table_p,
                      n.fat_g AS table_f, n.carbohydrate_g AS table_c,
                      min.energy_kcal AS min_kcal, min.protein_g AS min_p,
                      min.fat_g AS min_f, min.carbohydrate_g AS min_c, min.salt_g AS min_salt,
                      min.provenance AS min_provenance,
                      sp.slug AS food_slug, sp.page_type AS food_page_type,
                      ii.url AS db_image_url,
                      pp.file AS product_image,
                      fib.amount AS fibre_g
               FROM shop_menu_items smi
               LEFT JOIN product_photos pp ON pp.shop_menu_item_id = smi.id
               LEFT JOIN nutrients fib ON fib.item_id = smi.item_id AND fib.code = 'FIB-'
               LEFT JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
               LEFT JOIN nutrition n ON n.item_id = smi.item_id
               LEFT JOIN menu_item_nutrition min ON min.shop_menu_item_id = smi.id
               LEFT JOIN site_pages sp ON sp.item_id = smi.item_id AND sp.lang = ?
               LEFT JOIN item_images ii ON ii.item_id = smi.item_id
               WHERE smi.shop_id = ?
               -- Dishes with verified figures first
               ORDER BY (cn.energy_kcal IS NULL AND min.energy_kcal IS NULL AND n.energy_kcal IS NULL),
                        smi.position""", (page["lang"], page["shop_id"])).fetchall()

        # Named `menu`, not `items`: Jinja resolves `d.items` to the dict's own
        # .items() method, so a key called "items" silently renders a bound method.
        menu, sources, with_figure = [], {}, 0
        for r in rows:
            # A glass of water, a side of mustard and 「追加チーズ」 are on the menu
            # but are not what anyone came to count; they padded the table
            # without adding a figure to it. Drinks go with them.
            visual = classify_dish_visual(r["name"])
            if menuterms.is_extra(r["name"]) or menuterms.is_drink(r["name"], visual["category"]):
                continue
            # A photograph of THIS dish if we licensed one, otherwise a bundled
            # photograph of the right KIND of dish, labelled as such. The
            # catalogue's Unsplash URLs are deliberately not used: a chain menu
            # renders 200-340 rows, and hotlinking that many third-party images
            # costs the reader a request each and tells Unsplash who is reading.
            food_img = get_dish_image(r["name"], visual["category"])
            # url is now a local photograph of that kind of dish; the
            # bundled file behind local_fallback is what onerror falls to.
            # A photograph of THIS dish at THIS chain first, then a licensed
            # photograph of the food itself, then one of the right kind of
            # dish, then nothing. Only the last two are illustrations.
            exact = _row_get(r, "product_image") or r["db_image_url"]
            # Photo-led pages: a card with a coloured square where the food
            # should be reads as broken. Same predicate the 品数 count uses.
            if not food_images.has_photo(r["name"], exact):
                continue
            image_url = exact or food_img["url"]
            image_card_url = exact or food_img["card_url"]
            image_full_url = image_url
            image_fallback = food_img["local_fallback"]
            representational_note = ("" if exact
                                     else food_img["representational_note"])
            kcal = source = protein_g = fat_g = carbs_g = salt_g = None
            if r["chain_kcal"] is not None and r["source_page"]:
                # The chain's own published numbers, with the page it came from.
                kcal, source = r["chain_kcal"], "chain"
                protein_g = r["chain_p"]
                fat_g = r["chain_f"]
                carbs_g = r["chain_c"]
                salt_g = r["chain_salt"]
                sources.setdefault("chain", {
                    "page": r["source_page"],
                    "file": r["source_url"],
                    "updated": r["source_updated"],
                })
            elif r["table_kcal"] is not None:
                # A composition-table entry the dish IS
                kcal, source = r["table_kcal"], "table"
                protein_g = r["table_p"]
                fat_g = r["table_f"]
                carbs_g = r["table_c"]
            elif r["min_kcal"] is not None:
                # Precomputed MEXT culinary decomposition or linked entry
                kcal, source = r["min_kcal"], r["min_provenance"] or "mext_calc"
                protein_g = r["min_p"]
                fat_g = r["min_f"]
                carbs_g = r["min_c"]
                salt_g = r["min_salt"]

            # Macros that do not add up to the calories beside them are wrong
            # whichever of the two is at fault, and showing both invites the
            # reader to spot the contradiction. 「ひじき入り鶏つくね」 came out at
            # 87.6 g of carbohydrate because the estimator matched ひじき and
            # weighed it as the DRIED seaweed; the energy figure was fine.
            # Drop the breakdown and keep the calorie, rather than print a set
            # that cannot all be true.
            if not _macros_reconcile(kcal, protein_g, fat_g, carbs_g,
                                     _row_get(r, "fibre_g"), r["name"]):
                protein_g = fat_g = carbs_g = None

            # A row carrying neither a price nor a calorie is a name and two
            # dashes. This page exists to put those two side by side.
            if menuterms.says_nothing(r["price_yen"], kcal):
                continue

            if kcal is not None:
                with_figure += 1
            menu.append({
                "id": r["item_id_pk"],
                "name": r["name"],
                "price_yen": r["price_yen"],
                "price_max_yen": r["price_max_yen"],
                "tax_incl": bool(r["tax_incl"]),
                "mealtime": r["mealtime"],
                "kcal": kcal,
                "kcal_source": source,
                "protein_g": protein_g,
                "fat_g": fat_g,
                "carbs_g": carbs_g,
                "salt_g": salt_g,
                "official_name": r["official_name"],
                "food_slug": r["food_slug"],
                "food_page_type": r["food_page_type"],
                "visual": visual,
                "image_url": image_url,
                "image_card_url": image_card_url,
                "image_full_url": image_full_url,
                "image_fallback": image_fallback,
                "representational_note": representational_note,
            })
        shop_dict = dict(shop) if shop else {}
        shop_dict["brand_logo"] = get_chain_brand_badge(shop_dict.get("name") or page.get("slug") or "")
        return {
            "shop": shop_dict,
            "menu": menu,
            "sources": sources,
            "with_figure": with_figure,
        }
    finally:
        conn.close()


def shops_index(lang):
    """Chains that have a page, most complete first. Non-indexable ones are still
    listed — they are reachable, they just do not go in the sitemap."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT sp.slug, sp.indexable, s.name, s.item_count, s.price_min, s.price_max,
                      COUNT(cn.id) AS published
               FROM shop_pages sp
               JOIN shops s ON s.id = sp.shop_id
               LEFT JOIN shop_menu_items smi ON smi.shop_id = s.id
               LEFT JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
               WHERE sp.lang = ?
               GROUP BY sp.id
               ORDER BY published DESC, s.item_count DESC""", (lang,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["brand_logo"] = get_chain_brand_badge(d.get("name") or d.get("slug") or "")
            out.append(d)
        return out
    finally:
        conn.close()


# ------------------------------------------------------- the food before cooking

# MEXT's 重量変化率 is a percentage of the 調理前 food, and names only the cooked
# one. The raw entry is its sibling in the same 食品番号 group: the same name with
# the 調理法 replaced by 生 or 乾 — 「にわとり 若どり もも 皮つき 焼き」 against
# 「にわとり 若どり もも 皮つき 生」.
#
# Named ONLY where exactly one sibling exists. まいたけ publishes both 生 and 乾
# and nothing in the name says which one 油いため started from, so that row keeps
# MEXT's own wording, 調理前の食品, and names no food at all. 372 of 497 resolve;
# guessing at the other 125 would put a specific claim where there is none.
RAW_FORMS = ("生", "乾")


def _yield_stem(name):
    parts = (name or "").split()
    return " ".join(parts[:-1]) if len(parts) > 1 else ""


def _raw_food_index(conn, lang):
    """{stem: {name, slug, energy_kcal}} for every stem with ONE raw entry."""
    found = {}
    for row in conn.execute(
            """SELECT COALESCE(nm.name, sp.title) AS name, sp.slug, n.energy_kcal
               FROM site_pages sp
               JOIN items i ON i.id = sp.item_id
               LEFT JOIN nutrition n ON n.item_id = sp.item_id
               LEFT JOIN item_names nm ON nm.item_id = sp.item_id
                    AND nm.lang = ? AND nm.is_primary = 1
               WHERE sp.lang = ? AND sp.page_type = 'food'
                 AND i.source_url LIKE 'mext_%'""", (lang, lang)):
        name = row["name"] or ""
        parts = name.split()
        if len(parts) < 2 or parts[-1] not in RAW_FORMS:
            continue
        stem = " ".join(parts[:-1])
        if stem in found:
            found[stem] = None          # two raw forms: which one is not stated
            continue
        found[stem] = {"name": name, "slug": row["slug"],
                       "energy_kcal": row["energy_kcal"]}
    return {k: v for k, v in found.items() if v}
