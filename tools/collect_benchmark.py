"""Fill the analyzer benchmark from chain photographs that carry a published figure.

    uv run python tools/collect_benchmark.py --plan
    uv run python tools/collect_benchmark.py --run --limit 12

Eleven photographs was enough to find a 34% bias and not enough to tune against
— a change that helps four rows and hurts three cannot be told from noise at
that size. 1,052 of the photographs on disk have the chain's own calorie figure
beside them, so the set can be as wide as patience allows.

Selection is deliberate rather than random: spread across chains and across
calorie bands, because the failures were not evenly distributed — the single
worst row was a steak whose main ingredient matched nothing, and a set drawn
only from small items would never have contained it.

RATE LIMIT. The live endpoint allows 12 analyses an hour per IP, and each one
costs a model call against the site's own key. `--run` stops at that ceiling and
says what it did; run it again next hour, or raise ANALYZER_RATE_LIMIT in the
box's .env and restart the service if you want the whole set in one sitting.
Photographs already saved are skipped, so re-running is cheap and safe.
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RAW = ROOT / "data/raw/analyzer_examples"
DB = ROOT / "data/metadata/dataset_manager.db"
ENDPOINT = "https://calories.jp/api/meal-analyzer?lang=ja"
PAUSE = 3.0

# Calorie bands, so the set keeps its spread as it grows. A benchmark made of
# side dishes says nothing about a 1,342 kcal ramen set.
BANDS = ((0, 300), (300, 600), (600, 900), (900, 99999))


def candidates(conn):
    """Photographs with a published figure, one row per menu item."""
    return [dict(r) for r in conn.execute(
        """SELECT pp.shop_menu_item_id AS id, pp.chain, pp.dish, pp.file,
                  cn.energy_kcal AS published
           FROM product_photos pp
           JOIN shop_menu_items smi ON smi.id = pp.shop_menu_item_id
           JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
           WHERE cn.energy_kcal IS NOT NULL
           ORDER BY pp.shop_menu_item_id""")]


def pick(rows, have, want):
    """Spread the next `want` across bands and chains, avoiding what we hold.

    Round-robins the bands so the set stays balanced however far it gets, and
    within a band prefers a chain that is under-represented in what we already
    have — 193 chains and a benchmark of one of them is a benchmark of one.
    """
    seen_chain = {}
    for row in rows:
        if str(row["id"]) in have:
            seen_chain[row["chain"]] = seen_chain.get(row["chain"], 0) + 1

    pools = []
    for low, high in BANDS:
        pool = [r for r in rows
                if low <= r["published"] < high and str(r["id"]) not in have]
        pool.sort(key=lambda r: (seen_chain.get(r["chain"], 0), r["id"]))
        pools.append(pool)

    chosen, i = [], 0
    while len(chosen) < want and any(pools):
        pool = pools[i % len(pools)]
        i += 1
        if not pool:
            continue
        row = pool.pop(0)
        chosen.append(row)
        seen_chain[row["chain"]] = seen_chain.get(row["chain"], 0) + 1
        for other in pools:
            other.sort(key=lambda r: (seen_chain.get(r["chain"], 0), r["id"]))
    return chosen


def analyse(row):
    """POST one photograph. Returns (ok, note)."""
    import httpx

    path = ROOT / row["file"].lstrip("/")
    if not path.is_file():
        return False, "photo missing on disk"
    mime = "image/webp" if path.suffix == ".webp" else "image/jpeg"
    try:
        with httpx.Client(timeout=120) as client:
            reply = client.post(
                ENDPOINT, files={"image": (path.name, path.read_bytes(), mime)})
    except httpx.HTTPError as exc:
        return False, str(exc)
    if reply.status_code == 429:
        return False, "rate limited"
    if reply.status_code != 200:
        return False, f"HTTP {reply.status_code}"
    body = reply.json()
    if "totals" not in body:
        return False, str(body)[:80]
    (RAW / f"{row['id']}.json").write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return True, f"{len(body.get('components') or [])} matched, " \
                 f"{len(body.get('unmatched') or [])} unmatched"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="actually call the endpoint")
    ap.add_argument("--plan", action="store_true", help="print what would be fetched")
    ap.add_argument("--limit", type=int, default=12, help="how many to add (default 12)")
    args = ap.parse_args()
    if not (args.run or args.plan):
        ap.error("choose --plan or --run")

    RAW.mkdir(parents=True, exist_ok=True)
    have = {p.stem for p in RAW.glob("*.json") if p.stem.isdigit()}
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = candidates(conn)
    conn.close()

    print(f"{len(rows):,} photographs carry a published figure; "
          f"{len(have)} already in the set")
    chosen = pick(rows, have, args.limit)
    if not chosen:
        print("nothing left to add")
        return

    for row in chosen:
        line = f"  {row['published']:5.0f} kcal  {row['chain'][:10]:12s} {row['dish'][:34]}"
        if not args.run:
            print(line)
            continue
        ok, note = analyse(row)
        print(f"{'ok  ' if ok else 'skip'}{line}  — {note}")
        if not ok and note == "rate limited":
            print("\nrate limit reached. Run again next hour, or raise "
                  "ANALYZER_RATE_LIMIT on the box to finish in one sitting.")
            break
        time.sleep(PAUSE)

    if args.run:
        now = len([p for p in RAW.glob("*.json") if p.stem.isdigit()])
        print(f"\nbenchmark is now {now} photographs. "
              f"Score it with: uv run python tools/score_analyzer.py")


if __name__ == "__main__":
    main()
