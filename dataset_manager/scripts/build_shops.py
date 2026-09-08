"""Resolve menu dishes to composition-table entries, then build the shop pages.

TWO RULES GOVERN THIS FILE.

1. **No number on a shop page comes from a model.** The LLM here does exactly
   what it already does in build_links: pick which existing table row a Japanese
   name refers to. The kcal itself is then read from that row and scaled by
   deterministic arithmetic in calc/. `POST /items/{id}/estimate` asks Gemini for
   macros directly — it must never feed one of these pages.

2. **A shop page earns its index slot or does not get one.** A menu is published
   by the restaurant, by Tabelog and by Hotpepper; reprinting it adds nothing and
   is what got kalori.jp's menu pages deindexed. What we can add that nobody else
   has is the calorie column — so a page is indexable only when enough of its
   dishes actually resolved to measured nutrition. Pages that fail still render
   (noindex, follow) because they still pass link equity to the food pages.

    uv run python main.py match-menus --limit 200   # resolve dish names
    uv run python main.py build-shops               # slugs, titles, index gate
    uv run python main.py build-shops --report
"""
import re

from . import build_site
from ..database.site_schema import create_site_tables
from ..site import foodterms, menuterms

# --- the index gate ---------------------------------------------------------
# A page below any of these is a menu reprint with no added fact on it.
MIN_ITEMS = 15              # fewer dishes than this is not a menu, it is a sign
MIN_RESOLVED_SHARE = 0.40   # share of dishes carrying a real, sourced kcal
MIN_PRICED = 1              # at least one price the source did not contradict

LLM_BATCH = 25


def _nutrition_items(conn):
    """Item ids that actually carry an energy value — a match to a row with no
    nutrition is not a resolved dish, it is a link to an empty page."""
    return {
        r[0] for r in conn.execute(
            "SELECT item_id FROM nutrition WHERE energy_kcal IS NOT NULL")
    }


def _shop_stats(conn, shop_id, with_nutrition):
    """Counts the index gate reads for one shop.

    A dish counts as RESOLVED when it carries a calorie figure we can attribute:
    the chain's own published number first (the only honest source for a composed
    dish), else a composition-table row that actually has energy. Everything else
    renders as a dash.
    """
    items = conn.execute(
        """SELECT smi.item_id, smi.price_yen, cn.energy_kcal AS chain_kcal
           FROM shop_menu_items smi
           LEFT JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
           WHERE smi.shop_id = ?""", (shop_id,)).fetchall()
    return {
        "items": len(items),
        "resolved": sum(1 for i in items
                        if i["chain_kcal"] is not None or i["item_id"] in with_nutrition),
        "priced": sum(1 for i in items if i["price_yen"]),
    }


def _table_name_index(conn):
    """{comparable name: item_id} over the composition tables.

    Both the full display name and its last segment are indexed: MEXT writes
    「こめ 水稲めし 精白米 うるち米」, and a menu writes 「うるち米」.
    """
    index, tails = {}, {}
    for item_id, name in conn.execute(
            """SELECT nm.item_id, nm.name FROM item_names nm JOIN items i ON i.id = nm.item_id
               WHERE nm.lang = 'ja'
                 AND i.source IN ('MEXT Standard Tables', 'MAFF Our Regional Cuisines')"""):
        index.setdefault(_squash(name), item_id)
        parts = name.split()
        if len(parts) > 1:
            tails.setdefault(_squash(parts[-1]), set()).add(item_id)
    # A tail is only a name when exactly one entry ends in it. 「プレーン」 and
    # 「フルーツ」 are the tails of several rows each, so matching a menu's
    # 「プレーン」 to whichever one happened to be read first is a coin toss —
    # the same refuse-on-ambiguity rule the chain-nutrition join uses.
    for tail, owners in tails.items():
        if len(owners) == 1 and tail not in index:
            index[tail] = next(iter(owners))
    # ponytail: a tail unique in the tables can still be generic on a menu —
    # 「フルーツ」 resolves to 乳飲料 フルーツ, a fruit milk drink, because that is
    # the only row ending in the word. 1 of 345 matches, and it only affects which
    # food page the dish links to, never a calorie. Tighten with a category check
    # if a real page shows a link that reads as wrong.
    return index


def _squash(value):
    return re.sub(r"[\s　]", "", value or "")


_NAME_INDEX = {}


def _table_name_match(conn, dish_name):
    """The item this dish IS, by name equality — or None. Never a containment."""
    if id(conn) not in _NAME_INDEX:
        _NAME_INDEX.clear()
        _NAME_INDEX[id(conn)] = _table_name_index(conn)
    index = _NAME_INDEX[id(conn)]
    for variant in menuterms.variants(dish_name):
        hit = index.get(_squash(variant))
        if hit:
            return hit
    return None


def match_items(conn, limit=None, rebuild=False, use_llm=True):
    """Resolve shop_menu_items.name → items.id.

    Deterministic first (the curated vocabulary in site/foodterms), model second,
    and a declined match is RECORDED ('llm-none') so a re-run does not pay to ask
    the same question again — the mistake build_links already made once.
    """
    create_site_tables(conn)
    if rebuild:
        n = conn.execute(
            "UPDATE shop_menu_items SET item_id = NULL, match_confidence = NULL, "
            "match_method = NULL").rowcount
        conn.commit()
        print(f"cleared {n} existing matches")

    rows = conn.execute(
        """SELECT id, name FROM shop_menu_items
           WHERE item_id IS NULL AND match_method IS NULL ORDER BY id"""
    ).fetchall()
    if limit:
        rows = rows[:limit]
    print(f"dishes to match: {len(rows)}")

    pending = []
    for row in rows:
        name = row["name"]
        if foodterms.is_ignorable(name):
            conn.execute(
                "UPDATE shop_menu_items SET match_method = 'ignorable' WHERE id = ?",
                (row["id"],))
            continue
        # The raw name first, then the name with menu decoration stripped —
        # 「炙りはまちゆず塩」 is はまち, and the table only knows the fish.
        cands, matched_on = [], name
        for variant in menuterms.variants(name):
            cands = build_site._mext_candidates(conn, variant)
            if cands:
                matched_on = variant
                break
        # ONLY a whole-name match is accepted, and the composition-table link is
        # used for INTERLINKING — never as this dish's calorie figure. The chain's
        # own published number is the figure (extractors/chains.py); MEXT tells us
        # which food page this dish belongs next to.
        #
        # Anything looser was measured and is wrong: matching on a term CONTAINED
        # in the name resolves 「まぐろ醤油ラーメン」 to soy sauce, a cheeseburger to
        # cheese, and a champagne to French bread, because the curated vocabulary
        # exists to read recipe ingredient lines, where that answer is correct.
        equal_to = _table_name_match(conn, name)
        if equal_to:
            conn.execute(
                """UPDATE shop_menu_items
                   SET item_id = ?, match_confidence = 1.0, match_method = 'name-equal'
                   WHERE id = ?""", (equal_to, row["id"]))
        elif cands:
            pending.append((row["id"], name, cands))
        else:
            # Nothing in the tables is even a candidate. Common and correct: a
            # 竹鶴ハイボール is not in a food-composition table and never will be.
            conn.execute(
                "UPDATE shop_menu_items SET match_method = 'no-candidate' WHERE id = ?",
                (row["id"],))
    conn.commit()

    if not use_llm:
        print(f"deterministic pass done; {len(pending)} ambiguous dishes left for the model")
        return
    print(f"model resolution needed: {len(pending)} dishes")
    for i in range(0, len(pending), LLM_BATCH):
        batch = pending[i:i + LLM_BATCH]
        entries = []
        for j, (_, name, cands) in enumerate(batch):
            listed = "; ".join(f'{c["id"]}={c["name"]}' for c in cands) or "(none)"
            entries.append(f'{j}: dish "{name}" candidates: {listed}')
        prompt = (
            "You match dishes on a Japanese restaurant menu to entries of the MEXT "
            "Standard Tables of Food Composition. For each numbered dish, pick the "
            "candidate id for the food it is mainly made of, or null if none of them "
            "is that food. A drink, an alcoholic product or a branded item with no "
            "plain-food equivalent should be null. NEVER invent an id not listed.\n"
            'Respond ONLY with JSON: {"<number>": {"id": <candidate id or null>, '
            '"confidence": <0.0-1.0>}}\n\n' + "\n".join(entries)
        )
        try:
            result = build_site._llm_json(prompt)
        except Exception as e:
            print(f"  batch {i // LLM_BATCH}: model failed ({e}); leaving unresolved")
            continue
        for j, (row_id, name, cands) in enumerate(batch):
            entry = result.get(str(j)) or {}
            cid, conf = entry.get("id"), entry.get("confidence")
            if cid and any(c["id"] == cid for c in cands):
                conn.execute(
                    """UPDATE shop_menu_items
                       SET item_id = ?, match_confidence = ?, match_method = 'llm'
                       WHERE id = ? AND item_id IS NULL""",
                    (cid, float(conf or 0.75), row_id))
            else:
                conn.execute(
                    "UPDATE shop_menu_items SET match_method = 'llm-none' WHERE id = ? "
                    "AND item_id IS NULL", (row_id,))
        conn.commit()
        print(f"  {min(i + LLM_BATCH, len(pending))}/{len(pending)}")
    print("match-menus done")


def gate(shop_stats):
    """Should this shop's page be indexable? Returns (bool, reason).

    Pure so the rule is testable without a corpus. `shop_stats` carries
    items / resolved / priced counts.
    """
    items = shop_stats["items"]
    if items < MIN_ITEMS:
        return False, f"only {items} dishes (min {MIN_ITEMS})"
    if shop_stats["priced"] < MIN_PRICED:
        return False, "no usable price"
    share = shop_stats["resolved"] / items if items else 0.0
    if share < MIN_RESOLVED_SHARE:
        return False, f"only {share:.0%} of dishes have sourced nutrition (min {MIN_RESOLVED_SHARE:.0%})"
    return True, f"{items} dishes, {share:.0%} with sourced nutrition"


def _titles(name, stats, imported_at):
    """Title + meta for a shop page. States an ESTIMATE, because that is what a
    composition-table figure for a restaurant's own recipe is."""
    title = f"{name}のメニュー・カロリー一覧"
    price = ""
    if stats.get("price_min") and stats.get("price_max"):
        price = f"価格は{stats['price_min']:,}円〜{stats['price_max']:,}円。"
    when = f"メニューは{imported_at[:7].replace('-', '年')}月時点。" if imported_at else ""
    meta = (f"{name}のメニュー{stats['items']}品を、値段と推定カロリーで一覧。{price}"
            f"カロリーは日本食品標準成分表に基づく推計です。{when}")
    return title, meta


def build_pages(conn, lang="ja"):
    """Create/refresh one shop_pages row per shop, with the index gate applied.

    JA only: 253 English pages of translated Japanese restaurant menus would be
    thin duplicate content and would double the deindex exposure for no traffic.
    """
    create_site_tables(conn)
    with_nutrition = _nutrition_items(conn)

    taken = {r[0] for r in conn.execute(
        "SELECT slug FROM shop_pages WHERE lang = ?", (lang,))}
    existing = {r[0]: r[1] for r in conn.execute(
        "SELECT shop_id, slug FROM shop_pages WHERE lang = ?", (lang,))}

    made = updated = indexable = 0
    for shop in conn.execute(
            "SELECT id, name, item_count, price_min, price_max, imported_at "
            "FROM shops ORDER BY id").fetchall():
        stats = _shop_stats(conn, shop["id"], with_nutrition)
        stats["price_min"] = shop["price_min"]
        stats["price_max"] = shop["price_max"]
        ok, reason = gate(stats)
        title, meta = _titles(shop["name"], stats, shop["imported_at"])

        slug = existing.get(shop["id"])
        if slug is None:
            base = build_site.slugify_ja(shop["name"]) or f"shop-{shop['id']}"
            slug, n = base, 2
            while slug in taken:
                slug, n = f"{base}-{n}", n + 1
            taken.add(slug)
            conn.execute(
                """INSERT INTO shop_pages (shop_id, lang, slug, page_type, title,
                       meta_description, indexable, updated_at)
                   VALUES (?, ?, ?, 'shop', ?, ?, ?, datetime('now'))""",
                (shop["id"], lang, slug, title, meta, 1 if ok else 0))
            made += 1
        else:
            conn.execute(
                """UPDATE shop_pages SET title = ?, meta_description = ?, indexable = ?,
                       updated_at = datetime('now')
                   WHERE shop_id = ? AND lang = ?""",
                (title, meta, 1 if ok else 0, shop["id"], lang))
            updated += 1
        if ok:
            indexable += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM shop_pages").fetchone()[0]
    print(f"shop pages: +{made} new, {updated} refreshed, {total} total — "
          f"{indexable} pass the index gate, {total - indexable} are noindex,follow")


def report(conn):
    """Coverage, and what the gate would do. Read-only."""
    with_nutrition = _nutrition_items(conn)
    total_items = conn.execute("SELECT COUNT(*) FROM shop_menu_items").fetchone()[0]
    matched = conn.execute(
        "SELECT COUNT(*) FROM shop_menu_items WHERE item_id IS NOT NULL").fetchone()[0]
    print(f"dishes: {total_items}, matched to a table row: {matched} "
          f"({matched / total_items:.0%})" if total_items else "no dishes imported")
    print("by method:")
    for r in conn.execute(
            "SELECT COALESCE(match_method, '(unattempted)') m, COUNT(*) c "
            "FROM shop_menu_items GROUP BY m ORDER BY c DESC"):
        print(f"  {r[0]:<16} {r[1]}")

    passing = failing = 0
    for shop in conn.execute("SELECT id FROM shops"):
        ok, _ = gate(_shop_stats(conn, shop[0], with_nutrition))
        passing += ok
        failing += not ok
    print(f"shops passing the index gate: {passing} / {passing + failing}")
