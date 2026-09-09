"""Load images we have been given permission to use.

    uv run python tools/import_licensed_images.py granted.csv --dry-run
    uv run python tools/import_licensed_images.py granted.csv

For images that are NOT freely licensed on Wikimedia — a chain's own photography
sent over after a 画像利用許諾 request, a press kit with stated terms, anything
bought from a stock library. tools/fetch_dish_images.py handles the free ones.

The CSV wants one row per image:

    slug,image_url,credit,licence,permission_ref,page_url
    けの汁,https://…/keno-shiru.jpg,株式会社◯◯,許諾済（2026-09-12 メール）,inbox/2026-09-12-maruya.eml,

`slug` is the dish or food page slug — the last segment of /dish/… or /food/….

`licence` and `permission_ref` are both required and neither is decoration.
`licence` is what gets printed under the photograph. `permission_ref` is where
the permission itself is filed, so that in two years someone can answer "who
said we could use this" without relying on memory. Rows missing either are
refused, because an image whose permission cannot be produced on request is one
that should not be on the site.
"""
import argparse
import csv
import datetime
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset_manager.database.site_schema import create_site_tables   # noqa: E402

DB = "data/metadata/dataset_manager.db"
REQUIRED = ("slug", "image_url", "credit", "licence", "permission_ref")


def resolve(conn, slug):
    row = conn.execute(
        "SELECT item_id, page_type FROM site_pages WHERE slug = ? AND lang = 'ja'",
        (slug,)).fetchone()
    return (row["item_id"], row["page_type"]) if row else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    create_site_tables(conn)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    written = skipped = 0
    problems = []
    with open(args.csv_path, encoding="utf-8-sig", newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh), 2):
            missing = [c for c in REQUIRED if not (row.get(c) or "").strip()]
            if missing:
                problems.append(f"line {n}: missing {', '.join(missing)}")
                skipped += 1
                continue
            if not row["image_url"].strip().startswith("https://"):
                problems.append(f"line {n}: image_url is not https")
                skipped += 1
                continue
            item_id, page_type = resolve(conn, row["slug"].strip())
            if not item_id:
                problems.append(f"line {n}: no page with slug {row['slug']!r}")
                skipped += 1
                continue

            if not args.dry_run:
                conn.execute(
                    """INSERT OR REPLACE INTO item_images
                       (item_id, url, page_url, width, height, source, licence,
                        licence_url, credit, matched_on, fetched_at)
                       VALUES (?, ?, ?, NULL, NULL, ?, ?, NULL, ?, ?, ?)""",
                    (item_id, row["image_url"].strip(),
                     (row.get("page_url") or "").strip() or None,
                     row["credit"].strip(), row["licence"].strip(),
                     row["credit"].strip(),
                     f"granted:{row['permission_ref'].strip()}", now))
            written += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    for p in problems:
        print(f"  skipped — {p}")
    print(f"{'would import' if args.dry_run else 'imported'} {written} images, "
          f"skipped {skipped}")
    if written:
        print("remember to re-run tools/export_site_db.py before deploying")


if __name__ == "__main__":
    main()
