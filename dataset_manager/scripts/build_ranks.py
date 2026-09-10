"""Where a food sits among its own kind, for one component.

「鉄は肉類の上位8%」 is a fact about the corpus: it names its population, it is
computed the same way every time, and it says nothing about whether the food is
good for anyone. That is the whole reason it is safe to publish where a dietary
claim would not be.

TWO RULES DECIDE WHETHER A RANK EXISTS AT ALL.

Measured against measured. MEXT marks a value it estimated rather than measured,
and 76,436 of the 257,235 values carry that mark. A percentile that silently
mixes the two inherits the estimate's uncertainty without showing it, so an
estimated value is neither ranked nor counted as a peer. The page says so.

Twenty peers or none. Below that a percentile says more than it knows: being
above three of four foods is not 「上位25%」 in any useful sense.

Precomputed because the alternative is one COUNT over the composition table per
nutrient per page view, and the food pages carry forty of them.
"""
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dataset_manager.site import nutrient_pages  # noqa: E402

MIN_PEERS = 20

# The four the food page draws bars for. They are not in the curated ranking-page
# set (nobody searches 「炭水化物が多い食品」 as a page) but the page ranked them
# separately with a live COUNT over a different population — measured AND
# estimated — so a reader saw two percentiles built two ways under one heading.
MACROS = ("ENERC_KCAL", "PROT-", "FAT-", "CHOCDF-")

DDL = """CREATE TABLE IF NOT EXISTS nutrient_ranks (
    item_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    category TEXT NOT NULL,
    percentile INTEGER NOT NULL,
    peers INTEGER NOT NULL,
    PRIMARY KEY (item_id, code)
)"""
INDEX = ("CREATE INDEX IF NOT EXISTS idx_nutrient_ranks_code "
         "ON nutrient_ranks(code, category, percentile)")


def build_nutrient_ranks(conn, codes=None, min_peers=MIN_PEERS):
    """Rebuild the table. Returns a stats dict."""
    if codes is None:
        codes = list(MACROS)
        codes += [c for c, *_ in nutrient_pages.NUTRIENTS if c not in MACROS]
    codes = tuple(codes)
    conn.execute(DDL)
    conn.execute(INDEX)
    conn.execute("DELETE FROM nutrient_ranks")

    marks = ",".join("?" * len(codes))
    groups = defaultdict(list)
    for item_id, code, category, amount in conn.execute(
            f"""SELECT n.item_id, n.code, i.category, n.amount
                FROM nutrients n JOIN items i ON i.id = n.item_id
                WHERE n.code IN ({marks})
                  AND n.amount IS NOT NULL
                  AND n.quality = 'measured'
                  AND i.category IS NOT NULL AND i.category != 'foundation'
                  AND i.source_url LIKE 'mext_%'""", codes):
        groups[(category, code)].append((amount, item_id))

    rows, skipped = [], 0
    for (category, code), members in groups.items():
        if len(members) < min_peers:
            skipped += len(members)
            continue
        members.sort()
        peers = len(members)
        # The share of the OTHER foods in the group this one stands above, so
        # the largest reads 100 and the smallest 0. Dividing by the whole group
        # instead would put the single richest food in a category of four at
        # 75, and 「上位25%」 is not what a reader would call the top of a list.
        # Ties share a percentile: two foods holding the same amount cannot be
        # 上位25% and 上位50%.
        below = 0
        index = 0
        while index < peers:
            same = index
            while same < peers and members[same][0] == members[index][0]:
                same += 1
            for _amount, item_id in members[index:same]:
                rows.append((item_id, code, category,
                             round(below / (peers - 1) * 100), peers))
            below = same
            index = same

    conn.executemany(
        "INSERT OR REPLACE INTO nutrient_ranks "
        "(item_id, code, category, percentile, peers) VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    return {"codes": len(codes), "groups": len(groups), "ranked": len(rows),
            "skipped_thin_groups": skipped}


def main():
    import os
    db = os.environ.get("DATABASE_PATH", "data/metadata/dataset_manager.db")
    conn = sqlite3.connect(db, timeout=60)
    try:
        stats = build_nutrient_ranks(conn)
    finally:
        conn.close()
    print(f"nutrient_ranks: {stats['ranked']:,} ranks over {stats['groups']} "
          f"category/nutrient groups ({stats['codes']} nutrients); "
          f"{stats['skipped_thin_groups']:,} values sat in groups under {MIN_PEERS} peers")


if __name__ == "__main__":
    main()
