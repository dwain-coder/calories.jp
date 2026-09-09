"""One freely-licensed photograph per dish category, then one per dish.

    uv run python tools/fetch_category_images.py --categories-only
    uv run python tools/fetch_category_images.py

Dishes with a photograph of themselves keep it. Everything else gets a picture
of the right KIND of dish, stored with matched_on='category:煮物' so the page can
say so and so the whole layer can be dropped in one statement.

The 24 category images are few enough to look at, which is the point: a wrong
one here is wrong on a hundred pages at once.
"""
import argparse
import datetime
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset_manager.images import categories, wikimedia            # noqa: E402
from dataset_manager.database.site_schema import create_site_tables  # noqa: E402

DB = "data/metadata/dataset_manager.db"

DDL = """CREATE TABLE IF NOT EXISTS category_images (
    category TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    page_url TEXT,
    licence TEXT NOT NULL,
    licence_url TEXT,
    credit TEXT NOT NULL,
    fetched_at TEXT NOT NULL
)"""


def fetch_categories(conn, client, now, refresh=False):
    """One image per category, from that category's own Wikipedia article."""
    have = {r[0] for r in conn.execute("SELECT category FROM category_images")}
    wanted = {c: categories.ARTICLES[c] for c in categories.ALL
              if c not in have or refresh}
    leads = wikimedia.wikipedia_lead_images(list(wanted.values()), client=client)

    for category, article in wanted.items():
        filename = leads.get(article)
        hit = (wikimedia.commons_file(filename, client=client, matched_on="category")
               if filename else None)
        time.sleep(wikimedia.REQUEST_PAUSE)
        if not hit:
            print(f"  {category:8} no usable image from 「{article}」")
            continue
        conn.execute(
            """INSERT OR REPLACE INTO category_images
               (category, url, page_url, licence, licence_url, credit, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (category, hit["url"], hit.get("page_url"), hit["licence"],
             hit.get("licence_url"), hit["credit"], now))
        print(f"  {category:8} {hit['title'][:56]}")
    conn.commit()


def dominant_groups(conn):
    """{dish item id: MEXT group of its heaviest informative ingredient}."""
    rows = conn.execute(
        """SELECT l.dish_item_id AS dish, ing.category AS grp, SUM(l.grams) AS g
           FROM recipe_ingredient_links l
           JOIN items ing ON ing.id = l.mext_item_id
           WHERE l.mext_item_id IS NOT NULL AND l.grams IS NOT NULL
           GROUP BY l.dish_item_id, ing.category""").fetchall()
    best = {}
    for r in rows:
        if r["grp"] in categories.UNINFORMATIVE:
            continue
        if r["dish"] not in best or r["g"] > best[r["dish"]][1]:
            best[r["dish"]] = (r["grp"], r["g"])
    return {k: v[0] for k, v in best.items()}


def assign(conn, now):
    """Give every dish without a photograph one of its category."""
    images = {r["category"]: dict(r) for r in conn.execute("SELECT * FROM category_images")}
    if not images:
        sys.exit("no category images stored — run with --categories-only first")

    groups = dominant_groups(conn)
    dishes = conn.execute(
        """SELECT i.id, COALESCE(nm.name, sp.title) AS name
           FROM site_pages sp
           JOIN items i ON i.id = sp.item_id
           LEFT JOIN item_names nm ON nm.item_id = i.id
                AND nm.lang = 'ja' AND nm.is_primary = 1
           WHERE sp.lang = 'ja' AND sp.page_type = 'dish'
             AND i.id NOT IN (SELECT item_id FROM item_images)""").fetchall()

    written, missing = 0, 0
    tally = {}
    for d in dishes:
        category = categories.classify(d["name"], groups.get(d["id"]))
        image = images.get(category)
        if not image:
            # Five categories have no usable photograph. Falling back is fine;
            # keeping the original label is not — the page would read
            # 「卵のイメージ」 under a photograph of osechi.
            category = categories.FALLBACK
            image = images.get(category)
        if not image:
            missing += 1
            continue
        conn.execute(
            """INSERT OR REPLACE INTO item_images
               (item_id, url, page_url, width, height, source, licence, licence_url,
                credit, matched_on, fetched_at)
               VALUES (?, ?, ?, NULL, NULL, 'Wikimedia Commons', ?, ?, ?, ?, ?)""",
            (d["id"], image["url"], image.get("page_url"), image["licence"],
             image.get("licence_url"), image["credit"], f"category:{category}", now))
        tally[category] = tally.get(category, 0) + 1
        written += 1
    conn.commit()
    for cat, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4}  {cat}")
    print(f"\n{written} dishes illustrated by category, {missing} left without")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--categories-only", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    create_site_tables(conn)
    conn.execute(DDL)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    client = wikimedia._client()
    try:
        print(f"fetching a photograph for each of {len(categories.ALL)} categories…")
        fetch_categories(conn, client, now, args.refresh)
    finally:
        client.close()

    if not args.categories_only:
        print("\nassigning:")
        assign(conn, now)
    conn.close()


if __name__ == "__main__":
    main()
