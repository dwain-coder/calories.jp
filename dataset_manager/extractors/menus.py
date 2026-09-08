"""Import the restaurant-menu snapshot into shops / shop_menu_items.

This is an IMPORT, not a scraper. The CSV is a frozen drop from an extractor
that no longer exists, so there is no refresh path and none is built here — when
a real, licensed source appears, this is the module it lands in.

What is deliberately NOT imported, per the 2026-09-06 decision to ship the
snapshot data-only: the scraped `description` column and the store photos. Dish
names and prices are facts about a menu; a scraped blurb and a photo of someone's
restaurant are someone else's copy. The calorie figure the page is actually for
is computed later, from the composition tables, by scripts/build_shops.py.

    uv run python main.py import-menus data/raw/menus/menu-items.ja.csv
"""
import csv
import datetime
import io

from ..database.site_schema import create_site_tables
from ..validators.menus import (
    collapse_duplicates,
    is_non_food,
    is_section_label,
    mealtime_of,
    price_of,
)

REQUIRED_COLUMNS = ("menu_id", "restaurant_name", "item_name", "price")


def read_rows(text):
    """CSV text → validated menu rows, grouped per shop, with a rejection tally.

    Returns (shops, stats). `shops` is a list of dicts:
        {menu_id, name, items: [{source_item_id, name, price_yen,
                                 price_max_yen, tax_incl, mealtime, position}]}
    Pure: no database, no filesystem. Every drop is counted, never silent.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"CSV is missing column(s): {', '.join(missing)}")

    stats = {"rows": 0, "blank": 0, "non_food": 0, "section_label": 0,
             "no_price": 0, "duplicates": 0}
    order = []
    by_shop = {}

    for row in reader:
        stats["rows"] += 1
        menu_id = (row.get("menu_id") or "").strip()
        name = (row.get("item_name") or "").strip()
        shop_name = (row.get("restaurant_name") or "").strip()
        if not menu_id or not name:
            stats["blank"] += 1
            continue
        if is_non_food(name):
            stats["non_food"] += 1
            continue
        if is_section_label(shop_name):
            # Counted per ROW here; the shop it would have created is never made.
            stats["section_label"] += 1
            continue

        if menu_id not in by_shop:
            by_shop[menu_id] = {"menu_id": menu_id, "name": shop_name or menu_id, "items": []}
            order.append(menu_id)

        price_yen, tax_incl = price_of(row.get("price"), row.get("price_tax_incl"))
        if price_yen is None:
            stats["no_price"] += 1
        by_shop[menu_id]["items"].append({
            "source_item_id": (row.get("item_id") or "").strip() or None,
            "name": name,
            "price_yen": price_yen,
            "price_max_yen": None,
            "tax_incl": 1 if tax_incl else 0,
            # The description is read ONLY to guess a meal-time bucket and is
            # then dropped — it never reaches the database or a page.
            "mealtime": mealtime_of(f"{name} {(row.get('description') or '').strip()}"),
        })

    shops = []
    for menu_id in order:
        shop = by_shop[menu_id]
        before = len(shop["items"])
        items = collapse_duplicates(shop["items"])
        stats["duplicates"] += before - len(items)
        for position, item in enumerate(items):
            item["position"] = position
        shop["items"] = items
        shops.append(shop)
    return shops, stats


def import_menus(conn, text, imported_at=None):
    """Write the parsed snapshot into the corpus. Idempotent: re-running replaces
    a shop's items in place, so a corrected CSV can simply be re-imported.

    Matches (`item_id`, `match_confidence`, `match_method`) are NOT touched — they
    are expensive to compute and are keyed by dish name, so a re-import of the
    same menu keeps them.
    """
    create_site_tables(conn)
    stamp = imported_at or datetime.date.today().isoformat()
    shops, stats = read_rows(text)

    for shop in shops:
        prices = [i["price_max_yen"] or i["price_yen"] for i in shop["items"] if i["price_yen"]]
        lows = [i["price_yen"] for i in shop["items"] if i["price_yen"]]
        conn.execute(
            """INSERT INTO shops (menu_id, name, item_count, price_min, price_max, imported_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(menu_id) DO UPDATE SET
                   name = excluded.name, item_count = excluded.item_count,
                   price_min = excluded.price_min, price_max = excluded.price_max,
                   imported_at = excluded.imported_at""",
            (shop["menu_id"], shop["name"], len(shop["items"]),
             min(lows) if lows else None, max(prices) if prices else None, stamp))
        shop_id = conn.execute(
            "SELECT id FROM shops WHERE menu_id = ?", (shop["menu_id"],)).fetchone()[0]

        # Carry existing matches across a re-import, keyed the way the row is.
        matched = {
            (r[0], r[1]): (r[2], r[3], r[4])
            for r in conn.execute(
                """SELECT name, mealtime, item_id, match_confidence, match_method
                   FROM shop_menu_items WHERE shop_id = ? AND item_id IS NOT NULL""",
                (shop_id,))
        }
        conn.execute("DELETE FROM shop_menu_items WHERE shop_id = ?", (shop_id,))
        for item in shop["items"]:
            item_id, confidence, method = matched.get((item["name"], item["mealtime"]),
                                                      (None, None, None))
            conn.execute(
                """INSERT INTO shop_menu_items
                   (shop_id, source_item_id, name, price_yen, price_max_yen, tax_incl,
                    mealtime, position, item_id, match_confidence, match_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (shop_id, item["source_item_id"], item["name"], item["price_yen"],
                 item["price_max_yen"], item["tax_incl"], item["mealtime"], item["position"],
                 item_id, confidence, method))
    conn.commit()

    stats["shops"] = len(shops)
    stats["items"] = sum(len(s["items"]) for s in shops)
    stats["matches_kept"] = conn.execute(
        "SELECT COUNT(*) FROM shop_menu_items WHERE item_id IS NOT NULL").fetchone()[0]
    return stats
