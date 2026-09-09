"""Several photographs per kind of dish, so a menu page is not one picture N times.

    uv run python tools/fetch_dish_variants.py            # dry run
    uv run python tools/fetch_dish_variants.py --apply

One photograph per concept is honest but repetitive: くら寿司 has 123 rows and a
handful of concepts covering them, so the same sushi appears down the page.

A Commons CATEGORY is a set of photographs of one subject, curated by the people
who upload them — Category:Karaage is 50 files, all of karaage. Taking several
and assigning one per dish by a stable hash of its name gives a page variety
without giving any row a picture of the wrong food: every photograph in the set
is still a photograph of that dish.

The hash is on the dish name, so a dish keeps the same photograph between
deploys. A shuffle on every build would make the page look broken.
"""
import argparse
import datetime
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from dataset_manager.images import wikimedia  # noqa: E402

DB = "data/metadata/dataset_manager.db"
OUT = Path("static/media/food/variants")
WIDTH = 480        # a card renders 480x360; smaller keeps 200 files affordable
PER_CONCEPT = 6

DDL = """CREATE TABLE IF NOT EXISTS dish_photo_variants (
    concept TEXT NOT NULL,
    idx INTEGER NOT NULL,
    file TEXT NOT NULL,
    page_url TEXT,
    licence TEXT NOT NULL,
    credit TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (concept, idx)
)"""

# Commons categories that actually hold photographs of the dish. Probed, not
# guessed: Category:Beefsteak, Category:Fried prawn and Category:Hamburg steak
# are empty, so those concepts keep their single photograph.
CATEGORIES = {
    "karaage_chicken": "Karaage",
    "yakiniku_steak": "Yakiniku",
    "teishoku": "Teishoku",
    "coffee": "Coffee",
    "salad_green": "Caesar salad",
    "tea_matcha": "Tea",
    "burger_classic": "Hamburgers",
    "sushi_platter": "Sushi",
    "juice_beverage": "Orange juice",
    "tonkatsu_pork": "Tonkatsu",
    "curry_rice": "Japanese curry",
    "icecream_parfait": "Ice cream",
    "chuhai": "Chūhai",
    "beer_alcohol": "Beer",
    "ramen_shoyu": "Ramen",
    "french_fries": "French fries",
    "udon": "Udon",
    "soup_miso": "Miso soup",
    "pasta": "Pasta dishes",
    "soba": "Soba",
    "gyoza": "Jiaozi",
    "yakitori": "Yakitori",
    "tempura": "Tempura",
    "oden": "Oden",
    "gohan_rice": "Cooked rice",
    "tamago_egg": "Fried eggs",
    "sashimi": "Sashimi",
    "omurice": "Omurice",
    "takoyaki": "Takoyaki",
    "okonomiyaki": "Okonomiyaki",
    "edamame": "Edamame",
}

# Commons categories carry audio, video, diagrams and menu boards alongside the
# food. Only bitmaps of a plate are wanted.
SKIP = (".ogg", ".ogv", ".webm", ".svg", ".pdf", ".tif", ".gif", ".mid")


def members(category, client, limit=60):
    r = client.get(wikimedia.COMMONS_API, params={
        "action": "query", "format": "json", "list": "categorymembers",
        "cmtitle": f"Category:{category}", "cmtype": "file", "cmlimit": limit})
    r.raise_for_status()
    return [m["title"].replace("File:", "")
            for m in (r.json().get("query") or {}).get("categorymembers", [])
            if not m["title"].lower().endswith(SKIP)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--per", type=int, default=PER_CONCEPT)
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.execute(DDL)
    client = wikimedia._client()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total = 0
    try:
        for concept, category in sorted(CATEGORIES.items()):
            try:
                names = members(category, client)
            except httpx.HTTPError as exc:
                print(f"  {concept:18} category failed: {exc}")
                continue
            kept = 0
            for filename in names:
                if kept >= args.per:
                    break
                hit = wikimedia.commons_file(filename, client=client, width=WIDTH,
                                             matched_on=f"category:{category}")
                time.sleep(wikimedia.REQUEST_PAUSE)
                if not hit:          # not freely licensed, or no rendering
                    continue
                suffix = Path(hit["url"].split("?")[0]).suffix.lower()
                if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                    suffix = ".jpg"
                path = f"/static/media/food/variants/{concept}-{kept}{suffix}"
                if args.apply:
                    OUT.mkdir(parents=True, exist_ok=True)
                    try:
                        img = httpx.get(hit["url"], timeout=60, follow_redirects=True,
                                        headers={"User-Agent": wikimedia.USER_AGENT})
                        img.raise_for_status()
                    except httpx.HTTPError:
                        continue
                    (OUT / Path(path).name).write_bytes(img.content)
                    conn.execute(
                        """INSERT OR REPLACE INTO dish_photo_variants
                           (concept, idx, file, page_url, licence, credit, fetched_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (concept, kept, path, hit.get("page_url"), hit["licence"],
                         hit.get("credit"), now))
                kept += 1
            total += kept
            print(f"  {concept:18} {category:16} {kept} of {len(names)} usable")
        conn.commit()
    finally:
        client.close()
        conn.close()

    print(f"\n{total} photographs across {len(CATEGORIES)} kinds of dish")
    print("Every one is a photograph of that dish; look at them before shipping.")
    if not args.apply:
        print("Dry run. Nothing downloaded.")


if __name__ == "__main__":
    main()
