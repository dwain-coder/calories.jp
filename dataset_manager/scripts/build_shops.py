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
import unicodedata

from . import build_site
from ..database.site_schema import create_site_tables
from ..site import foodterms, menuterms
from ..site.brand_assets import classify_dish_visual

# --- the index gate ---------------------------------------------------------
# A page below any of these is a menu reprint with no added fact on it.
#
# The share counts only figures the chain published or a composition-table row
# supplied — NOT the tier-3 estimates in menu_item_nutrition, even though those
# are what most of the calorie column prints.
#
# Counting them was tried and reverted. It lifted the number of indexable pages
# from 4 to 96, but tier 3 decomposes a dish NAME against a small library of
# standard recipes, and the recipe is chosen on one keyword: 「ハンバーグ」. It does
# not read the rest of the name. So 「濃厚ビーフシチューの包み焼きハンバーグ145g」,
# the 110g and the ダブル220g all come out at 432.5 kcal, and 「殻付き海老グリル＆
# 大俵ハンバーグ」 matches plain 「大俵ハンバーグ」 at 361.9 — the shrimp is not read.
# かつや's 78 dishes hold 10 distinct values between them; KFC's 43 hold 6.
#
# A page whose calorie column repeats one number down the menu is not a page
# that earned an index slot on the strength of its calorie column.
MIN_ITEMS = 15              # fewer dishes than this is not a menu, it is a sign
MIN_RESOLVED_SHARE = 0.40   # share of dishes carrying a real, sourced kcal
MIN_PRICED = 1              # at least one price the source did not contradict

LLM_BATCH = 25


# --- what is actually a restaurant ------------------------------------------
# The source CSV is one row per MENU, and a restaurant that publishes its lunch
# card separately from its dinner card arrives as two menus. Most keep the
# restaurant's name on both; some carry only the name of the section, so `shops`
# ended up holding rows called 「Lunch」, 「Restaurant」, 「本日のおすすめ」 and
# 「ラーメン」 — a course, a time slot and a food category, none of them a business.
#
# The test for this list is deliberately narrow: a name goes in only if it
# identifies NO business at all. 「萬作 おしながき」 and 「大衆酒場 八銭 名物料理」 are
# also section names, but each carries a real restaurant in front of it, so they
# keep their page and the gate decides whether it is worth indexing. Guessing
# which half of a name is the shop is how you delete a real restaurant.
NOT_A_RESTAURANT = frozenset({
    # course / service / time slot
    "lunch", "dinner", "food", "grand", "restaurant", "cafétime", "café time",
    "cafetime", "ランチメニューlunchmenu11:00~15:00", "besideseasideweekdaylunch",
    "お食事", "居酒屋", "キッズ", "お得なセット!!", "お通しなし お席料なし",
    "お通しなしお席料なし", "本日の", "本日のおすすめ",
    # a food category, not a shop
    "pizza", "crepe", "coffee&latte", "homeroastedcoffee", "freshmelondessert",
    "ラーメン", "季節限定うどん", "牡蠣", "台湾料理", "朝引き鶏", "野菜肉巻き串",
    "煮干し出汁のらーめん", "さぬき名物", "フルーツサンド", "フリット＆ドリンク",
    "フリット&ドリンク", "ボウラーのための燃料", "大漁海鮮丼定食",
})

# One chain, written two ways. The source has 「MOS BURGER」 and 「モスバーガー」 as
# separate menus of the same chain, and a reader who sees both in the index is
# looking at a bug. Only exact, unambiguous pairs — a branch name
# (「餃子の王将 グランツリー武蔵小杉店」) is left alone, because a branch really does
# publish a different menu from the chain's national one.
SAME_CHAIN = {
    "mosburger": "モスバーガー",
    "kfc": "ケンタッキーフライドチキン",
    "【公式】kfcクリスマスメニュー2025": "ケンタッキーフライドチキン",
    "falafelbrothers": "ファラフェルブラザーズ",
    "ファラフェルブラザーズ|大手町": "ファラフェルブラザーズ",
    "t.y.harbor": "t.y.ハーバーブルワリーレストラン",
    "globaldiningoriginalbreadbartizanbreadfactory": "bartizanbreadfactory",
}


def chain_key(name):
    """The identity of the business behind a menu name.

    Case and width folded and whitespace dropped, so 「Ivy Place」/「IVY PLACE」 and
    「ファラフェル ブラザーズ」/「ファラフェルブラザーズ」 land on one key.
    """
    key = unicodedata.normalize("NFKC", name or "").casefold()
    key = re.sub(r"\s+", "", key)
    return SAME_CHAIN.get(key, key)


def is_a_restaurant(name):
    """False when the row names a menu section rather than a business."""
    return chain_key(name) not in NOT_A_RESTAURANT


_JA = re.compile(r"[぀-ヿ一-鿿]")


def pick_canonical(shops, sourced=None):
    """{shop id: display name} — one page per business.

    Four rows are called 「AZABUDAI HILLS CAFE」 and three 「IKEA」; they are one
    venue's menu split by section, so they get one page.

    The winner is the menu carrying the most SOURCED calories, not the longest
    one. 「MOS BURGER」 lists 116 dishes with one figure behind them and
    「モスバーガー」 106 dishes with 81, so ranking by length would have published
    the emptier of the two pages. Length breaks the tie; the lower id breaks
    that, so a rebuild does not move a page to a different slug.

    The name is chosen separately, and on a different rule again: the Japanese
    one, when the business has one — a Japanese-only site should not title a
    page 「MOS BURGER」, the fault already fixed once for eight food pages.

    `sourced` maps shop id to how many of its dishes carry a chain figure or a
    composition-table row; without it the function ranks on length alone.
    """
    sourced = sourced or {}
    groups = {}
    for shop in shops:
        if not is_a_restaurant(shop["name"]):
            continue
        groups.setdefault(chain_key(shop["name"]), []).append(shop)

    def rank(s):
        return (sourced.get(s["id"], 0), s["item_count"], -s["id"])

    out = {}
    for rows in groups.values():
        canonical = max(rows, key=rank)
        japanese = [s for s in rows if _JA.search(s["name"] or "")]
        out[canonical["id"]] = max(japanese, key=rank)["name"] if japanese else canonical["name"]
    return out


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
        """SELECT smi.name, smi.item_id, smi.price_yen, cn.energy_kcal AS chain_kcal,
                  min.energy_kcal AS shown_kcal, min.provenance
           FROM shop_menu_items smi
           LEFT JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
           LEFT JOIN menu_item_nutrition min ON min.shop_menu_item_id = smi.id
           WHERE smi.shop_id = ?""", (shop_id,)).fetchall()
    # Count the menu a reader sees. Drinks and condiments are filtered out of
    # the page, so leaving them in here would gate on a menu nobody is shown
    # and print a 品数 that disagrees with the rows under it.
    items = [i for i in items if not (
        menuterms.is_extra(i["name"])
        or menuterms.is_drink(i["name"], classify_dish_visual(i["name"])["category"]))]

    def sourced(i):
        """The chain's own figure, or a composition-table row for this dish."""
        return i["chain_kcal"] is not None or i["item_id"] in with_nutrition

    return {
        "items": len(items),
        "resolved": sum(1 for i in items if sourced(i)),
        # What the page actually prints, which is mostly tier-3 estimates. Kept
        # for the report so the gap between the two is visible.
        "shown": sum(1 for i in items if i["shown_kcal"] is not None or sourced(i)),
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

    shops = conn.execute(
        "SELECT id, name, item_count, price_min, price_max, imported_at "
        "FROM shops ORDER BY id").fetchall()

    # A page per business, not a page per menu. Rows that name a section rather
    # than a restaurant, and the smaller duplicates of a business that appears
    # more than once, are dropped here — including any page an earlier build
    # already gave them, which is how they leave the index and the sitemap.
    sourced = {r[0]: r[1] for r in conn.execute(
        """SELECT shop_id, COUNT(*) FROM shop_menu_items
           WHERE chain_nutrition_id IS NOT NULL OR item_id IN
                 (SELECT item_id FROM nutrition WHERE energy_kcal IS NOT NULL)
           GROUP BY shop_id""")}
    keep = pick_canonical(shops, sourced)
    dropped = [s for s in shops if s["id"] not in keep]
    for shop in dropped:
        conn.execute("DELETE FROM shop_pages WHERE shop_id = ?", (shop["id"],))

    made = updated = indexable = 0
    for shop in shops:
        if shop["id"] not in keep:
            continue
        name = keep[shop["id"]]
        if name != shop["name"]:
            # Written back rather than threaded through the page: the index, the
            # page heading, the title and the JSON-LD all read shops.name, and one
            # UPDATE keeps them agreeing instead of four places to forget.
            conn.execute("UPDATE shops SET name = ? WHERE id = ?", (name, shop["id"]))
        stats = _shop_stats(conn, shop["id"], with_nutrition)
        if stats["items"] != shop["item_count"]:
            conn.execute("UPDATE shops SET item_count = ? WHERE id = ?",
                         (stats["items"], shop["id"]))
        stats["price_min"] = shop["price_min"]
        stats["price_max"] = shop["price_max"]
        ok, reason = gate(stats)
        title, meta = _titles(name, stats, shop["imported_at"])

        slug = existing.get(shop["id"])
        if slug is None:
            base = build_site.slugify_ja(name) or f"shop-{shop['id']}"
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
    sections = sum(1 for s in dropped if not is_a_restaurant(s["name"]))
    print(f"shop pages: +{made} new, {updated} refreshed, {total} total — "
          f"{indexable} pass the index gate, {total - indexable} are noindex,follow")
    print(f"  skipped {len(dropped)} menus: {sections} name a section not a shop, "
          f"{len(dropped) - sections} are duplicates of a shop that is already here")


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
