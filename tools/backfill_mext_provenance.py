"""Give the stored MEXT values back the qualifiers the source publishes.

    uv run python tools/backfill_mext_provenance.py --dry-run
    uv run python tools/backfill_mext_provenance.py

The tables mark a value MEXT estimated rather than analysed by putting it in
parentheses, and a trace amount as 'Tr'. Ingest dropped both, so 22,414
estimates were stored as measurements and 3,081 traces as hard zeros — on a
site whose entire claim is that its figures are measured and shown as
published. This writes the distinction back, and stores the 食品番号 that every
other MEXT publication is indexed by.

It updates rows in place rather than re-running the transformer, because
`_insert_item()` is a blind INSERT: a re-run would duplicate all 2,538 foods,
which is exactly how the FDC rows ended up tripled.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dataset_manager.transformers.mext import (  # noqa: E402
    CODE_ROW_LABEL, NAME_COL, NUMBER_COL, NUTRIENT_COLS, clean_value,
)

DB_PATH = os.environ.get("DATABASE_PATH", "data/metadata/dataset_manager.db")
XLSX = Path("data/raw/mext_food_composition_2023/mext_00001_011.xlsx")
SOURCE = "MEXT Standard Tables"


def read_source():
    """{food_name: (食品番号, {nutrient_code: (amount, quality)})}"""
    df = pd.read_excel(XLSX, header=None)
    code_row = next(
        (i for i in range(20) if any(str(v).strip() == CODE_ROW_LABEL for v in df.iloc[i])),
        None)
    if code_row is None:
        sys.exit(f"{CODE_ROW_LABEL} row not found in {XLSX}")
    out = {}
    for _, row in df.iloc[code_row + 1:].iterrows():
        name = row[NAME_COL]
        if pd.isna(name) or not str(name).strip():
            continue
        values = {}
        for col, code, _, _ in NUTRIENT_COLS:
            amount, quality = clean_value(row[col])
            if amount is not None:
                values[code] = (amount, quality)
        out[str(name).strip()] = (str(row[NUMBER_COL]).strip(), values)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not XLSX.is_file():
        sys.exit(f"{XLSX} not found — the source file is gitignored; re-download it first")
    source = read_source()
    print(f"source: {len(source)} foods")

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    from dataset_manager.database.site_schema import create_site_tables
    create_site_tables(conn)          # adds nutrients.quality if missing

    items = conn.execute(
        "SELECT id, name, source_url FROM items WHERE source = ? ORDER BY id",
        (SOURCE,)).fetchall()
    print(f"database: {len(items)} MEXT items")

    # Match on the stored name, which is the source name verbatim. Refuse to
    # write anything if the two sides do not line up exactly: a partial match
    # would quietly mark the wrong foods.
    missing = [r["name"] for r in items if r["name"] not in source]
    if missing:
        print(f"\n{len(missing)} stored foods are not in the source file, e.g.:")
        for name in missing[:5]:
            print("   ", name)
        sys.exit("aborting — every stored food must match the source before writing")

    codes = quals = 0
    for it in items:
        food_code, values = source[it["name"]]
        want_url = f"mext_{food_code}"
        if it["source_url"] != want_url:
            codes += 1
            if not args.dry_run:
                conn.execute("UPDATE items SET source_url = ? WHERE id = ?", (want_url, it["id"]))
        for r in conn.execute(
                "SELECT id, code, amount, quality FROM nutrients WHERE item_id = ?", (it["id"],)):
            got = values.get(r["code"])
            if not got:
                continue
            amount, quality = got
            if r["quality"] == quality:
                continue
            # The amount itself is not rewritten unless it drifted: this pass
            # is about what the number means, not what it is.
            if abs((r["amount"] or 0) - amount) > 1e-9:
                print(f"  value drift: item {it['id']} {r['code']} "
                      f"{r['amount']} -> {amount}")
            quals += 1
            if not args.dry_run:
                conn.execute("UPDATE nutrients SET quality = ?, amount = ? WHERE id = ?",
                             (quality, amount, r["id"]))
    if not args.dry_run:
        conn.commit()

    counts = dict(conn.execute(
        "SELECT quality, COUNT(*) FROM nutrients GROUP BY quality").fetchall()) \
        if not args.dry_run else {}
    conn.close()
    verb = "would update" if args.dry_run else "updated"
    print(f"\n{verb}: {codes} food codes, {quals} nutrient values")
    if counts:
        for q, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"   {str(q):>10}: {n:,}")


if __name__ == "__main__":
    main()
