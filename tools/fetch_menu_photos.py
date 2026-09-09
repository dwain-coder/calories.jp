"""A real photograph for each kind of menu dish, from the article about it.

    uv run python tools/fetch_menu_photos.py            # dry run
    uv run python tools/fetch_menu_photos.py --apply

The menu pages carried 21 bundled stock images across 17,876 rows, and 44.8% of
those rows landed on one generic photograph. This fetches a freely-licensed
photograph per dish concept from the Japanese Wikipedia article about it — the
lead image, chosen by an editor to illustrate that subject, rather than a search
result that merely mentions the word.

Downloaded rather than hotlinked. A chain menu renders 200-340 rows; served from
Commons that is 340 third-party requests per page load and a record at Wikimedia
of who read which restaurant.

Idempotent: a concept that already has a file is skipped unless --refresh.
"""
import argparse
import datetime
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from dataset_manager.images import wikimedia            # noqa: E402
from dataset_manager.site import dish_concepts          # noqa: E402

DB = "data/metadata/dataset_manager.db"
OUT = Path("static/media/food")
WIDTH = 640          # rendered at 480x360 on a card; 640 covers a 2x display

DDL = """CREATE TABLE IF NOT EXISTS dish_photos (
    concept TEXT PRIMARY KEY,
    article TEXT NOT NULL,
    file TEXT NOT NULL,
    page_url TEXT,
    licence TEXT NOT NULL,
    credit TEXT,
    fetched_at TEXT NOT NULL
)"""


def download(url, concept, apply):
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".jpg"
    dest = OUT / f"{concept}{suffix}"
    if not apply:
        return f"/static/media/food/{dest.name}"
    OUT.mkdir(parents=True, exist_ok=True)
    r = httpx.get(url, follow_redirects=True, timeout=60,
                  headers={"User-Agent": wikimedia.USER_AGENT})
    r.raise_for_status()
    dest.write_bytes(r.content)
    return f"/static/media/food/{dest.name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(DDL)
    have = {r[0] for r in conn.execute("SELECT concept FROM dish_photos")}

    wanted = {k: a for k, a in dish_concepts.ALL.items()
              if args.refresh or k not in have}
    print(f"{len(dish_concepts.ALL)} concepts, {len(wanted)} to fetch")

    client = wikimedia._client()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    kept = missing = 0
    try:
        leads = wikimedia.wikipedia_lead_images(list(wanted.values()), client=client)
        # An explicit file wins: it was chosen by looking at it.
        for concept, filename in getattr(dish_concepts, 'FILES', {}).items():
            if concept in wanted:
                leads[wanted[concept]] = filename
        for concept, article in sorted(wanted.items()):
            filename = leads.get(article)
            hit = (wikimedia.commons_file(filename, client=client, width=WIDTH,
                                          matched_on=f"article:{article}")
                   if filename else None)
            time.sleep(wikimedia.REQUEST_PAUSE)
            if not hit:
                print(f"  {concept:18} --    nothing usable from 「{article}」")
                missing += 1
                continue
            path = download(hit["url"], concept, args.apply)
            if args.apply:
                conn.execute(
                    """INSERT OR REPLACE INTO dish_photos
                       (concept, article, file, page_url, licence, credit, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (concept, article, path, hit.get("page_url"), hit["licence"],
                     hit.get("credit"), now))
            print(f"  {concept:18} {article:10} {hit['licence'][:22]:24} "
                  f"{hit['title'][:36]}")
            kept += 1
        conn.commit()
    finally:
        client.close()
        conn.close()

    print(f"\n{kept} photographs, {missing} concepts left without one")
    if not args.apply:
        print("Dry run. Nothing written or downloaded.")
    else:
        print("Look at them. A wrong photograph here is wrong on hundreds of rows.")


if __name__ == "__main__":
    main()
