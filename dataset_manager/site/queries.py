"""Read-only queries for the public site. Clean corpus only — every page query
joins through site_pages, which is never populated for OpenFoodFacts/Wikipedia/
Wikidata/FoodKeeper items, so quarantined and share-alike data is structurally
excluded from the public surface."""
from ..api.database import get_connection, get_license_info
from ..calc.nutrition import dish_nutrition


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
            "SELECT code, name, unit, amount FROM nutrients WHERE item_id = ? ORDER BY id",
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
    conn.close()
    ja_name = (names.get("ja") or {}).get("primary") or item["name"]
    preps = prep_variants(item_id, lang, ja_name)
    lic, warning = get_license_info(item["source"])
    return {
        "item": item, "names": names, "nutrition": nutrition,
        "nutrients": nutrients, "portions": portions, "shelf_life": shelf_life,
        "jdi8": jdi8["score"] if jdi8 else None,
        "salt_g": salt_g, "pfc": pfc_energy_split(nutrition),
        "preps": preps, "qualified_name": qualified_name,
        "related": related, "alternates": alternates,
        "license": lic, "license_warning": warning,
    }


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
    conn.close()
    lic, warning = get_license_info(item["source"])
    return {
        "item": item, "names": names, "dish": rd, "links": links,
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
                  n.energy_kcal, n.protein_g, n.fat_g, n.carbohydrate_g
           FROM item_names nm
           JOIN items i ON i.id = nm.item_id AND i.source = 'MEXT Standard Tables'
           JOIN site_pages sp ON sp.item_id = nm.item_id AND sp.lang = ?
           LEFT JOIN nutrition n ON n.item_id = nm.item_id
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
        "portions": portions,
    }
