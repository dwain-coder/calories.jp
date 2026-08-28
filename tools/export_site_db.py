"""Write a deployable copy of the corpus holding only what the site serves.

    uv run python tools/export_site_db.py [--out data/metadata/site.db]

The working database is ~600 MB, and 99.6% of that is OpenFoodFacts: 2.07M
items with their nutrition, barcodes and ingredient strings. None of it is
reachable from the public site — public pages are joined through site_pages,
which is never populated for those rows — and it is ODbL, so it must not travel
with a deployment. Wikipedia goes for the same reason: CC BY-SA, no pages.

What is left is small enough to sit on a modest volume.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = os.environ.get("DATABASE_PATH", "data/metadata/dataset_manager.db")

# Quarantined at the licence level, not merely unused.
EXCLUDE_SOURCES = ("OpenFoodFacts", "Wikipedia (JA)")
# Only OpenFoodFacts ever populated these. Emptied rather than dropped: the
# legacy /items/{id} endpoint still selects from them, and a missing table is
# an error where an empty one is just an empty list.
EMPTY_TABLES = ("barcodes", "ingredients")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/metadata/site.db")
    args = ap.parse_args()

    src, out = Path(DB_PATH), Path(args.out)
    if not src.is_file():
        sys.exit(f"{src} not found")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    # VACUUM INTO gives a consistent copy without touching the original, even
    # while the server is reading it.
    print(f"copying {src} ({src.stat().st_size/1048576:.0f} MB)")
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as c:
        c.execute("VACUUM INTO ?", (str(out),))

    conn = sqlite3.connect(out)
    marks = ",".join("?" * len(EXCLUDE_SOURCES))
    before = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.execute(f"DELETE FROM items WHERE source IN ({marks})", EXCLUDE_SOURCES)
    kept = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    print(f"items {before} -> {kept}")

    for table in ("nutrition", "nutrients", "item_names", "site_pages",
                  "food_portions", "jdi8_scores", "shelf_life", "regional_dishes",
                  "item_ingredients", "ai_estimations", "ai_recipes"):
        try:
            n = conn.execute(
                f"DELETE FROM {table} WHERE item_id NOT IN (SELECT id FROM items)").rowcount
        except sqlite3.OperationalError as e:
            print(f"  skip {table}: {e}")
            continue
        if n:
            print(f"  {table}: dropped {n} orphaned rows")

    for table in EMPTY_TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()

    print("vacuuming")
    conn.isolation_level = None
    conn.execute("VACUUM")
    conn.close()
    print(f"-> {out} ({out.stat().st_size/1048576:.0f} MB)")


if __name__ == "__main__":
    main()
