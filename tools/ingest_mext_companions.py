"""Load MEXT's amino acid, fatty acid and carbohydrate books.

    uv run python tools/ingest_mext_companions.py [--dry-run]

Idempotent: each file replaces the codes it owns, so re-running is a no-op.
Files are the ones downloaded into data/raw/mext_{amino,fatty,carb}_2023/.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dataset_manager.database.site_schema import create_site_tables  # noqa: E402
from dataset_manager.transformers.mext_companion import ingest, read_file  # noqa: E402

DB_PATH = os.environ.get("DATABASE_PATH", "data/metadata/dataset_manager.db")

# Only the tables that give per-100g figures for an edible portion, which is
# what every other figure on a food page is per. Each book also publishes the
# same components per gram of nitrogen, per 100 g of fatty acids, or per gram
# of fat — working figures for recalculating a recipe, and meaningless next to
# a per-100g table. Picking 第3表 for the fatty acids by mistake stored
# salmon's DHA as 112 "mg per gram of fat" where the page would have read it
# as mg per 100 g.
BOOKS = [
    ("data/raw/mext_amino_2023/04.xlsx", "amino acids, per 100 g"),
    ("data/raw/mext_fatty_2023/09.xlsx", "fatty acids, per 100 g"),
    ("data/raw/mext_carb_2023/13.xlsx", "sugars and starch, per 100 g"),
    ("data/raw/mext_carb_2023/14.xlsx", "dietary fibre fractions"),
    ("data/raw/mext_carb_2023/15.xlsx", "organic acids"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=120)
    create_site_tables(conn)
    total = 0
    for path, label in BOOKS:
        if not Path(path).is_file():
            print(f"  missing, skipped: {path}")
            continue
        if args.dry_run:
            n = sum(1 for _ in read_file(path))
            print(f"  {label:32} {n:>7,} values (dry run)")
            total += n
            continue
        r = ingest(conn, path)
        print(f"  {label:32} {r['values']:>7,} values, {r['codes']:>3} components"
              + (f", {r['unmatched_foods']} foods not in the corpus" if r["unmatched_foods"] else ""))
        total += r["values"]

    if not args.dry_run:
        n = conn.execute("SELECT COUNT(*) FROM nutrients").fetchone()[0]
        foods = conn.execute(
            "SELECT COUNT(DISTINCT item_id) FROM nutrients").fetchone()[0]
        print(f"\nnutrients table: {n:,} values across {foods:,} foods")
    conn.close()
    print(f"{'would add' if args.dry_run else 'added'}: {total:,} values")


if __name__ == "__main__":
    main()
