"""Find a freely-licensed photograph for each regional dish.

    uv run python tools/fetch_dish_images.py --dry-run
    uv run python tools/fetch_dish_images.py --limit 50
    uv run python tools/fetch_dish_images.py

Wikidata P18 first, then a name-guarded Commons search. Both sources and the
reasons for the ordering are in dataset_manager/images/wikimedia.py.

Idempotent: a dish that already has an image is skipped unless --refresh, so an
interrupted run resumes and a finished one is cheap to repeat.
"""
import argparse
import datetime
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset_manager.images import wikimedia          # noqa: E402
from dataset_manager.database.site_schema import create_site_tables   # noqa: E402

DB = "data/metadata/dataset_manager.db"


def dishes(conn, refresh=False):
    """(item_id, name) for every dish page, newest-needed first."""
    skip = "" if refresh else " AND i.id NOT IN (SELECT item_id FROM item_images)"
    return conn.execute(f"""
        SELECT i.id, COALESCE(nm.name, sp.title) AS name
        FROM site_pages sp
        JOIN items i ON i.id = sp.item_id
        LEFT JOIN item_names nm ON nm.item_id = i.id
             AND nm.lang = 'ja' AND nm.is_primary = 1
        WHERE sp.lang = 'ja' AND sp.page_type = 'dish'{skip}
        ORDER BY sp.title""").fetchall()


def store(conn, item_id, hit, now):
    conn.execute(
        """INSERT OR REPLACE INTO item_images
           (item_id, url, page_url, width, height, source, licence, licence_url,
            credit, matched_on, fetched_at)
           VALUES (?, ?, ?, ?, ?, 'Wikimedia Commons', ?, ?, ?, ?, ?)""",
        (item_id, hit["url"], hit.get("page_url"), hit.get("width"), hit.get("height"),
         hit["licence"], hit.get("licence_url"), hit["credit"], hit["matched_on"], now))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh", action="store_true",
                    help="re-check dishes that already have an image")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    create_site_tables(conn)

    rows = dishes(conn, args.refresh)
    if args.limit:
        rows = rows[:args.limit]
    print(f"{len(rows)} dishes without an image")
    if not rows:
        return

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    client = wikimedia._client()
    try:
        names = [r["name"] for r in rows]
        # Both batch sources first, so the per-dish loop makes at most one
        # request each instead of three.
        print("asking Japanese Wikipedia for article lead images…")
        lead = wikimedia.wikipedia_lead_images(names, client=client)
        print(f"  {len(lead)} articles with a lead image")
        print("asking Wikidata which dishes declare an image…")
        p18 = wikimedia.wikidata_images(names, client=client)
        print(f"  {len(p18)} declared")

        found = {"wikipedia-lead": 0, "wikidata-p18": 0, "commons-name": 0}
        missing = 0
        for n, row in enumerate(rows, 1):
            name = row["name"]
            hit = None
            if name in lead:
                hit = wikimedia.commons_file(lead[name], client=client,
                                             matched_on="wikipedia-lead")
                time.sleep(wikimedia.REQUEST_PAUSE)
            if hit is None and name in p18:
                hit = wikimedia.commons_file(p18[name], client=client)
                time.sleep(wikimedia.REQUEST_PAUSE)
            if hit is None:
                hits = wikimedia.search_commons(name, client=client)
                hit = hits[0] if hits else None
                time.sleep(wikimedia.REQUEST_PAUSE)

            if hit is None:
                missing += 1
            else:
                found[hit["matched_on"]] += 1
                if not args.dry_run:
                    store(conn, row["id"], hit, now)
            if n % 25 == 0:
                conn.commit()
                got = sum(found.values())
                print(f"  {n}/{len(rows)}  found {got}  missing {missing}", flush=True)
        conn.commit()
    finally:
        client.close()
        conn.close()

    total = sum(found.values())
    print(f"\n{'would store' if args.dry_run else 'stored'} {total} images "
          f"({found['wikipedia-lead']} Wikipedia lead, {found['wikidata-p18']} Wikidata P18, "
          f"{found['commons-name']} name-matched); "
          f"{missing} dishes have no free photograph")


if __name__ == "__main__":
    main()
