"""Offline builders for the public site: names, pages, links, search, sitemaps.

All idempotent — INSERT OR IGNORE / rebuild-in-place. Run via main.py CLI.
"""
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

from ..database.site_schema import create_site_tables
from ..calc.quantities import parse_recipe_lines
from ..site import seo
from ..site.i18n import LANGS

from ..api.database import DB_PATH

FOOD_SOURCES = ("MEXT Standard Tables", "USDA FoodData Central")
DISH_SOURCE = "MAFF Our Regional Cuisines"
FDC_RAW = Path("data/extracted/usda_fooddata_central")


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _llm_json(prompt, model=None):
    """One litellm call returning a parsed JSON object (same pattern as
    utils/translate.py)."""
    import litellm
    model = model or os.environ.get("HELM_LLM_MODEL", "gemini/gemini-2.5-flash")
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


# ---------------------------------------------------------------- names

def clean_mext_name(name):
    """`＜鳥肉類＞　にわとり　［親・主品目］　むね　皮つき　生` -> `にわとり 親・主品目 むね 皮つき 生`

    The ＜group＞ prefix is redundant (species is named), but ［...］ carries
    variant info (親 vs 若どり etc.) that distinguishes otherwise identical
    names — keep its content."""
    s = re.sub(r"＜[^＞]*＞", "", name)
    s = s.replace("［", " ").replace("］", " ")
    s = re.sub(r"[　\s]+", " ", s).strip()
    return s or name


def _fdc_portion_desc(p):
    desc = (p.get("portionDescription") or "").strip()
    if desc and desc.lower() != "quantity not specified":
        return desc
    amount = p.get("amount")
    unit = (p.get("measureUnit") or {}).get("name") or ""
    mod = (p.get("modifier") or "").strip()
    parts = [str(amount) if amount is not None else "", unit if unit != "undetermined" else "", mod]
    out = " ".join(x for x in parts if x).strip()
    return out or None


def build_names_fdc(conn):
    """Official English names + portions from the raw FoundationFoods JSON,
    joined on items.source_url = 'fdc_<fdcId>'."""
    raws = [p for p in FDC_RAW.glob("*.json") if p.name != "manifest.json"]
    if not raws:
        print("no FDC raw JSON found — skipping official EN names")
        return 0
    data = json.loads(raws[0].read_text(encoding="utf-8"))
    foods = data.get("FoundationFoods", data if isinstance(data, list) else [])
    by_ref = {f"fdc_{f['fdcId']}": f for f in foods if isinstance(f, dict) and f.get("fdcId")}

    items = conn.execute(
        "SELECT id, source_url FROM items WHERE source = 'USDA FoodData Central'"
    ).fetchall()
    matched = orphans = 0
    for it in items:
        f = by_ref.get(it["source_url"])
        if not f:
            orphans += 1
            continue
        matched += 1
        conn.execute(
            "INSERT OR IGNORE INTO item_names (item_id, lang, name, kind, is_primary)"
            " VALUES (?, 'en', ?, 'official', 1)",
            (it["id"], f["description"]))
        cat = (f.get("foodCategory") or {}).get("description")
        if cat:
            conn.execute(
                "INSERT OR IGNORE INTO item_names (item_id, lang, name, kind, is_primary)"
                " VALUES (?, 'en', ?, 'alias', 0)", (it["id"], cat))
        for p in f.get("foodPortions", []):
            gw, desc = p.get("gramWeight"), _fdc_portion_desc(p)
            if gw and desc:
                conn.execute(
                    "INSERT OR IGNORE INTO food_portions (item_id, description, gram_weight)"
                    " VALUES (?, ?, ?)", (it["id"], desc, gw))
    conn.commit()
    print(f"FDC: {matched} official EN names, {orphans} orphans (no fdcId in raw file; will be LLM-translated)")
    return matched


def build_names_ja(conn):
    """Cleaned JA display names for MEXT; JA primary = items.name for others."""
    n = 0
    for it in conn.execute(
        "SELECT id, name, source FROM items WHERE source IN (?, ?, ?)",
        (*FOOD_SOURCES, DISH_SOURCE)):
        ja = clean_mext_name(it["name"]) if it["source"] == "MEXT Standard Tables" else it["name"]
        cur = conn.execute(
            "INSERT OR IGNORE INTO item_names (item_id, lang, name, kind, is_primary)"
            " VALUES (?, 'ja', ?, 'alias', 1)", (it["id"], ja))
        n += cur.rowcount
    conn.commit()
    print(f"JA display names: {n} inserted")
    return n


def _items_missing_en(conn):
    return conn.execute(
        """SELECT i.id, i.name, i.source,
                  (SELECT nm.name FROM item_names nm
                   WHERE nm.item_id = i.id AND nm.lang='ja' AND nm.is_primary=1) AS ja_name
           FROM items i
           WHERE i.source IN (?, ?, ?)
             AND NOT EXISTS (SELECT 1 FROM item_names nm
                             WHERE nm.item_id = i.id AND nm.lang='en' AND nm.is_primary=1)
           ORDER BY i.id""",
        (*FOOD_SOURCES, DISH_SOURCE)).fetchall()


def build_names_llm(conn, batch_size=50, limit=None):
    """LLM JA->EN translation for items without an official EN name.
    Stored kind='translated' (dishes also get a romanized alias)."""
    todo = _items_missing_en(conn)
    if limit:
        todo = todo[:limit]
    print(f"LLM EN names needed: {len(todo)}")
    done = 0
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        names = [it["ja_name"] or it["name"] for it in batch]
        is_dish = batch[0]["source"] == DISH_SOURCE
        prompt = (
            "You are translating Japanese food names for a nutrition database.\n"
            "For each Japanese name below, return natural, concise English food names.\n"
            "Respond ONLY with a JSON object mapping each exact input string to "
            + ('{"en": "English name", "romaji": "Hepburn romanization"}.'
               if is_dish else '{"en": "English name"}.')
            + "\nKeep preparation qualifiers (raw, boiled, skin-on) when present.\n\n"
            + "\n".join(names)
        )
        try:
            result = _llm_json(prompt)
        except Exception as e:
            print(f"  batch {i // batch_size}: LLM failed ({e}); skipping")
            continue
        for it, ja in zip(batch, names):
            entry = result.get(ja)
            if not entry:
                continue
            en = entry.get("en") if isinstance(entry, dict) else entry
            if not en or not isinstance(en, str):
                continue
            conn.execute(
                "INSERT OR IGNORE INTO item_names (item_id, lang, name, kind, is_primary)"
                " VALUES (?, 'en', ?, 'translated', 1)", (it["id"], en.strip()))
            if isinstance(entry, dict) and entry.get("romaji"):
                conn.execute(
                    "INSERT OR IGNORE INTO item_names (item_id, lang, name, kind, is_primary)"
                    " VALUES (?, 'en', ?, 'romanized', 0)", (it["id"], entry["romaji"].strip()))
            done += 1
        conn.commit()
        print(f"  {min(i + batch_size, len(todo))}/{len(todo)}")
    print(f"LLM EN names stored: {done}")
    return done


def build_display_names(conn):
    """Promote a readable short name to primary for MEXT items and keep the
    full taxonomy path as kind='full' for the qualified-name line on pages."""
    from ..site.display import resolve_display_names

    rows = conn.execute(
        """SELECT nm.item_id, nm.name FROM item_names nm
           JOIN items i ON i.id = nm.item_id
           WHERE i.source = 'MEXT Standard Tables' AND nm.lang = 'ja'
             AND nm.is_primary = 1 AND nm.kind != 'display'
           ORDER BY nm.item_id""").fetchall()
    if not rows:
        print("display names: nothing to do (already built)")
        return 0
    display = resolve_display_names([(r["item_id"], r["name"]) for r in rows])
    changed = 0
    for r in rows:
        item_id, full = r["item_id"], r["name"]
        short = display[item_id]
        if short == full:
            continue
        conn.execute(
            "UPDATE item_names SET kind = 'full', is_primary = 0"
            " WHERE item_id = ? AND lang = 'ja' AND name = ?", (item_id, full))
        conn.execute(
            "INSERT OR IGNORE INTO item_names (item_id, lang, name, kind, is_primary)"
            " VALUES (?, 'ja', ?, 'display', 1)", (item_id, short))
        changed += 1
    conn.commit()
    print(f"display names: {changed} shortened, {len(rows) - changed} already minimal")
    return changed


def build_names(limit=None):
    conn = get_conn()
    create_site_tables(conn)
    build_names_ja(conn)
    build_display_names(conn)
    build_names_fdc(conn)
    build_names_llm(conn, limit=limit)
    conn.close()


# ---------------------------------------------------------------- pages

def slugify_en(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s


def slugify_ja(name):
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"[\s　/?#%&=+．。、・（）()［］\[\]｛｝{}<>＜＞\"']+", "-", s).strip("-")
    return s


def _titles(lang, name, kcal, page_type, category):
    if page_type == "food":
        if lang == "en":
            title = f"{name} — Calories & Nutrition Facts"
            meta = (f"{name}: {round(kcal):d} kcal per 100 g. " if kcal is not None else f"{name}. ") + \
                "Protein, fat, carbohydrates and full nutrition facts with a serving-size calculator."
        else:
            title = f"{name}のカロリー・栄養成分"
            meta = (f"{name}のカロリーは100gあたり{round(kcal):d}kcal。" if kcal is not None else f"{name}。") + \
                "たんぱく質・脂質・炭水化物などの栄養成分表と分量計算ツール。"
    else:
        if lang == "en":
            title = f"{name} — Japanese Regional Dish, Recipe & Calories"
            meta = f"{name}: traditional dish from {category or 'Japan'}. Ingredients, recipe steps and nutrition information."
        else:
            title = f"{name}（{category or '郷土料理'}）のレシピ・カロリー"
            meta = f"{category or '日本'}の郷土料理「{name}」。材料・作り方と栄養情報。"
    return title, meta


def build_pages():
    conn = get_conn()
    create_site_tables(conn)
    # The items table holds duplicate FDC rows from repeated transform runs
    # (same source_url up to 3x). One page per real food: keep the lowest
    # item id per source_url.
    rows = conn.execute(
        """SELECT i.id, i.name, i.source, i.source_url, i.category, n.energy_kcal
           FROM items i LEFT JOIN nutrition n ON n.item_id = i.id
           WHERE (i.source IN (?, ?) AND n.energy_kcal IS NOT NULL) OR i.source = ?
           ORDER BY i.id""",
        (*FOOD_SOURCES, DISH_SOURCE)).fetchall()
    seen_urls = set()
    deduped = []
    for r in rows:
        if r["source"] == "USDA FoodData Central":
            if r["source_url"] in seen_urls:
                continue
            seen_urls.add(r["source_url"])
        deduped.append(r)
    rows = deduped
    names = {}
    for r in conn.execute("SELECT item_id, lang, name FROM item_names WHERE is_primary = 1"):
        names.setdefault(r["item_id"], {})[r["lang"]] = r["name"]

    taken = {  # (lang, slug) already in table (idempotent reruns)
        (r["lang"], r["slug"]) for r in conn.execute("SELECT lang, slug FROM site_pages")
    }
    existing = {
        (r["item_id"], r["lang"]) for r in conn.execute("SELECT item_id, lang FROM site_pages")
    }
    made = skipped = 0
    for it in rows:
        page_type = "dish" if it["source"] == DISH_SOURCE else "food"
        for lang in LANGS:
            if (it["id"], lang) in existing:
                continue
            name = names.get(it["id"], {}).get(lang)
            if not name:
                skipped += 1
                continue
            base = slugify_en(name) if lang == "en" else slugify_ja(name)
            if not base:
                skipped += 1
                continue
            slug, n = base, 2
            if (lang, slug) in taken and page_type == "dish" and it["category"]:
                # Same dish name in several prefectures: disambiguate by
                # prefecture, which is also what the title shows.
                cat = slugify_en(it["category"]) if lang == "en" else slugify_ja(it["category"])
                if cat:
                    slug = f"{base}-{cat}"
            while (lang, slug) in taken:
                slug, n = f"{base}-{n}", n + 1
            taken.add((lang, slug))
            title, meta = _titles(lang, name, it["energy_kcal"], page_type, it["category"])
            conn.execute(
                """INSERT INTO site_pages (item_id, lang, slug, page_type, title,
                       meta_description, indexable, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'))""",
                (it["id"], lang, slug, page_type, title, meta))
            made += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) c FROM site_pages").fetchone()["c"]
    conn.close()
    print(f"pages: +{made} new, {skipped} skipped (missing name), {total} total")


# ---------------------------------------------------------------- links

# Common recipe-ingredient spellings -> MEXT-style kana/base food, used for
# deterministic candidate lookup before any LLM involvement.
KANJI_TO_KANA = {
    "大根": "だいこん", "人参": "にんじん", "にんじん": "にんじん", "牛蒡": "ごぼう",
    "ごぼう": "ごぼう", "玉ねぎ": "たまねぎ", "玉葱": "たまねぎ", "じゃがいも": "じゃがいも",
    "馬鈴薯": "じゃがいも", "里芋": "さといも", "さつまいも": "さつまいも", "薩摩芋": "さつまいも",
    "白菜": "はくさい", "キャベツ": "キャベツ", "ほうれん草": "ほうれんそう", "小松菜": "こまつな",
    "ねぎ": "ねぎ", "長ねぎ": "ねぎ", "葱": "ねぎ", "しょうが": "しょうが", "生姜": "しょうが",
    "にんにく": "にんにく", "大蒜": "にんにく", "きゅうり": "きゅうり", "胡瓜": "きゅうり",
    "なす": "なす", "茄子": "なす", "かぼちゃ": "かぼちゃ", "南瓜": "かぼちゃ",
    "れんこん": "れんこん", "蓮根": "れんこん", "たけのこ": "たけのこ", "筍": "たけのこ",
    "しいたけ": "しいたけ", "椎茸": "しいたけ", "干ししいたけ": "しいたけ",
    "豆腐": "豆腐", "油揚げ": "油揚げ", "厚揚げ": "生揚げ", "こんにゃく": "こんにゃく",
    "米": "こめ", "もち米": "もち", "小麦粉": "小麦粉", "片栗粉": "でん粉",
    "砂糖": "砂糖", "塩": "食塩", "しょうゆ": "しょうゆ", "醤油": "しょうゆ",
    "みそ": "みそ", "味噌": "みそ", "赤味噌": "みそ", "白味噌": "みそ",
    "みりん": "みりん", "酒": "清酒", "酢": "食酢", "だし汁": "かつお・昆布だし",
    "サラダ油": "調合油", "油": "調合油", "ごま油": "ごま油", "バター": "バター",
    "卵": "鶏卵", "鶏卵": "鶏卵", "牛乳": "牛乳", "豚肉": "ぶた", "鶏肉": "にわとり",
    "牛肉": "うし", "鶏もも肉": "にわとり もも", "鶏むね肉": "にわとり むね",
    "昆布": "こんぶ", "わかめ": "わかめ", "ひじき": "ひじき", "のり": "あまのり",
    "ごま": "ごま", "小豆": "あずき", "大豆": "だいず", "こしあん": "あん",
}


def _mext_candidates(conn, raw_name, limit=6):
    terms = [raw_name]
    for k, v in KANJI_TO_KANA.items():
        if k in raw_name:
            terms.append(v)
            break
    seen, out = set(), []
    for term in terms:
        for r in conn.execute(
            """SELECT nm.item_id, nm.name FROM item_names nm
               JOIN items i ON i.id = nm.item_id
               WHERE i.source = 'MEXT Standard Tables' AND nm.lang = 'ja'
                 AND nm.name LIKE ?
               ORDER BY LENGTH(nm.name) LIMIT ?""",
            (f"%{term}%", limit)):
            if r["item_id"] not in seen:
                seen.add(r["item_id"])
                out.append({"id": r["item_id"], "name": r["name"]})
    return out[:limit]


def build_links(limit=None, report=False):
    conn = get_conn()
    create_site_tables(conn)
    if report:
        _links_report(conn)
        conn.close()
        return

    dishes = conn.execute(
        """SELECT i.id, rd.recipe_ingredients FROM items i
           JOIN regional_dishes rd ON rd.item_id = i.id
           WHERE i.source = ? AND rd.recipe_ingredients IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM recipe_ingredient_links l WHERE l.dish_item_id = i.id)
           ORDER BY i.id""", (DISH_SOURCE,)).fetchall()
    if limit:
        dishes = dishes[:limit]
    print(f"dishes to link: {len(dishes)}")

    pending_llm = []  # (dish_id, line_no, raw_name, candidates)
    for d in dishes:
        for line_no, name, qty, grams in parse_recipe_lines(d["recipe_ingredients"]):
            cands = _mext_candidates(conn, name)
            # Deterministic pick: single candidate whose name starts with the
            # mapped/base term is a confident exact-ish match.
            if len(cands) == 1:
                conn.execute(
                    """INSERT OR IGNORE INTO recipe_ingredient_links
                       (dish_item_id, line_no, raw_name, raw_quantity, grams,
                        mext_item_id, confidence, method)
                       VALUES (?, ?, ?, ?, ?, ?, 0.9, 'exact')""",
                    (d["id"], line_no, name, qty, grams, cands[0]["id"]))
            else:
                conn.execute(
                    """INSERT OR IGNORE INTO recipe_ingredient_links
                       (dish_item_id, line_no, raw_name, raw_quantity, grams,
                        mext_item_id, confidence, method)
                       VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)""",
                    (d["id"], line_no, name, qty, grams))
                if grams is not None:  # only worth LLM effort if it can count toward totals
                    pending_llm.append((d["id"], line_no, name, cands))
    conn.commit()

    print(f"LLM resolution needed: {len(pending_llm)} ingredient lines")
    batch_size = 25
    for i in range(0, len(pending_llm), batch_size):
        batch = pending_llm[i:i + batch_size]
        entries = []
        for j, (_, _, name, cands) in enumerate(batch):
            cand_txt = "; ".join(f'{c["id"]}={c["name"]}' for c in cands) or "(none)"
            entries.append(f'{j}: ingredient "{name}" candidates: {cand_txt}')
        prompt = (
            "You match Japanese recipe ingredients to entries of the MEXT Standard "
            "Tables of Food Composition. For each numbered ingredient, pick the "
            "candidate id that is the same food (prefer raw/生 forms), or null if "
            "none matches. NEVER invent an id not listed.\n"
            'Respond ONLY with JSON: {"<number>": {"id": <candidate id or null>, '
            '"confidence": <0.0-1.0>}}\n\n' + "\n".join(entries)
        )
        try:
            result = _llm_json(prompt)
        except Exception as e:
            print(f"  batch {i // batch_size}: LLM failed ({e}); leaving unresolved")
            continue
        for j, (dish_id, line_no, name, cands) in enumerate(batch):
            entry = result.get(str(j)) or {}
            cid, conf = entry.get("id"), entry.get("confidence")
            if cid and any(c["id"] == cid for c in cands):
                conn.execute(
                    """UPDATE recipe_ingredient_links
                       SET mext_item_id = ?, confidence = ?, method = 'llm'
                       WHERE dish_item_id = ? AND line_no = ? AND mext_item_id IS NULL""",
                    (cid, float(conf or 0.75), dish_id, line_no))
        conn.commit()
        print(f"  {min(i + batch_size, len(pending_llm))}/{len(pending_llm)}")
    conn.close()
    print("build-links done")


def _links_report(conn):
    total = conn.execute("SELECT COUNT(*) c FROM recipe_ingredient_links").fetchone()["c"]
    resolved = conn.execute(
        "SELECT COUNT(*) c FROM recipe_ingredient_links WHERE mext_item_id IS NOT NULL"
        " AND confidence >= 0.7").fetchone()["c"]
    with_grams = conn.execute(
        "SELECT COUNT(*) c FROM recipe_ingredient_links WHERE grams IS NOT NULL").fetchone()["c"]
    print(f"links: {total} lines, {with_grams} with grams, {resolved} resolved (conf>=0.7)")
    print("\ncoverage per dish (resolved/total), sample of computable dishes:")
    for r in conn.execute(
        """SELECT dish_item_id,
                  SUM(CASE WHEN mext_item_id IS NOT NULL AND confidence >= 0.7
                           AND grams IS NOT NULL THEN 1 ELSE 0 END) AS ok,
                  COUNT(*) AS n
           FROM recipe_ingredient_links GROUP BY dish_item_id
           HAVING ok * 1.0 / n >= 0.6 AND ok >= 2 LIMIT 10"""):
        print(f"  dish {r['dish_item_id']}: {r['ok']}/{r['n']}")
    ok_dishes = conn.execute(
        """SELECT COUNT(*) c FROM (
             SELECT dish_item_id FROM recipe_ingredient_links GROUP BY dish_item_id
             HAVING SUM(CASE WHEN mext_item_id IS NOT NULL AND confidence >= 0.7
                             AND grams IS NOT NULL THEN 1 ELSE 0 END) >= 2
                AND SUM(CASE WHEN mext_item_id IS NOT NULL AND confidence >= 0.7
                             AND grams IS NOT NULL THEN 1 ELSE 0 END) * 1.0 / COUNT(*) >= 0.6)"""
    ).fetchone()["c"]
    print(f"\ndishes with computed nutrition shown: {ok_dishes}")
    print("\nrandom LLM-resolved sample for eyeball check:")
    for r in conn.execute(
        """SELECT l.raw_name, l.confidence, nm.name FROM recipe_ingredient_links l
           JOIN item_names nm ON nm.item_id = l.mext_item_id AND nm.lang='ja' AND nm.is_primary=1
           WHERE l.method = 'llm' ORDER BY RANDOM() LIMIT 20"""):
        print(f"  {r['raw_name']} -> {r['name']} ({r['confidence']})")


# ---------------------------------------------------------------- search / sitemaps

def build_search():
    conn = get_conn()
    create_site_tables(conn)
    conn.execute("DELETE FROM search_fts")
    n = 0
    for r in conn.execute(
        """SELECT sp.item_id, sp.lang, i.category, i.source,
                  group_concat(nm.name, ' / ') AS names,
                  rd.main_ingredients
           FROM site_pages sp
           JOIN items i ON i.id = sp.item_id
           LEFT JOIN item_names nm ON nm.item_id = sp.item_id AND nm.lang = sp.lang
           LEFT JOIN regional_dishes rd ON rd.item_id = sp.item_id
           GROUP BY sp.item_id, sp.lang"""):
        text = " / ".join(x for x in (r["names"], r["main_ingredients"]) if x)
        conn.execute(
            "INSERT INTO search_fts (item_id, lang, name, category) VALUES (?, ?, ?, ?)",
            (r["item_id"], r["lang"], text, r["category"] or ""))
        n += 1
    conn.commit()
    conn.close()
    print(f"search_fts: {n} rows")


def build_sitemaps():
    """Split sitemaps per type and language: foods, dishes, categories, pages."""
    from ..site.i18n import MEXT_GROUPS_EN
    conn = get_conn()
    out_dir = Path("data/sitemaps")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("sitemap-*.xml"):
        old.unlink()

    alternates = {}
    for r in conn.execute("SELECT item_id, lang, page_type, slug FROM site_pages WHERE indexable=1"):
        alternates.setdefault(r["item_id"], {})[r["lang"]] = (r["page_type"], r["slug"])

    def write(name, entries):
        if not entries:
            return
        (out_dir / f"{name}.xml").write_text(seo.sitemap_xml(entries), encoding="utf-8")
        print(f"{name}.xml: {len(entries)} urls")

    for lang in LANGS:
        for ptype, plural in (("food", "foods"), ("dish", "dishes")):
            entries = []
            for r in conn.execute(
                "SELECT item_id, slug FROM site_pages WHERE indexable=1 AND lang=? AND page_type=? ORDER BY id",
                (lang, ptype)):
                entries.append({
                    "loc": seo.page_url(lang, ptype, r["slug"]),
                    "alternates": seo.hreflang_links(alternates.get(r["item_id"], {})),
                })
            write(f"sitemap-{plural}-{lang}", entries)

        # Category pages: only categories with pages in this lang.
        from urllib.parse import quote
        cat_entries = []
        for r in conn.execute(
            """SELECT i.category, COUNT(*) c FROM items i
               JOIN site_pages sp ON sp.item_id = i.id AND sp.lang = ?
               WHERE i.category IS NOT NULL AND i.category != 'foundation'
               GROUP BY i.category""", (lang,)):
            cat = r["category"]
            if lang == "en":
                en = MEXT_GROUPS_EN.get(cat)
                if not en:
                    continue  # no EN slugs for prefectures v1
                slug = slugify_en(en)
            else:
                slug = cat
            cat_entries.append({"loc": seo.base_url(lang) + f"/{lang}/category/{quote(slug)}"})
        write(f"sitemap-categories-{lang}", cat_entries)

        # Static tool pages.
        page_entries = [
            {"loc": seo.base_url(lang) + f"/{lang}/{p}"}
            for p in ("", "foods", "meal-calculator", "analyzer", "goals", "sources",
                      "guides/cooking-and-calories")
        ]
        write(f"sitemap-pages-{lang}", page_entries)
    conn.close()
