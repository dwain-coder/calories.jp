"""Turn saved analyzer responses into the worked examples the home page shows.

    uv run python tools/build_analyzer_examples.py

The home page claims things about what the analyzer does — how many ingredients
it picked out of one photograph, what each one was matched to, what it could not
match. Those are figures, so they are generated from the API's own responses
rather than typed by hand, and the responses themselves live in
`data/raw/analyzer_examples/` so anyone can check the page against them.

The responses were produced by POSTing a photograph to the live endpoint:

    curl -X POST 'https://calories.jp/api/meal-analyzer?lang=ja' \
         -F 'image=@static/media/products/9244.jpg;type=image/jpeg'

WHAT IS DELIBERATELY NOT CARRIED ACROSS: the meal total. `totals` sums the
components that matched and omits the ones that did not, so a photograph whose
main ingredient goes unmatched — a 150 g steak, a pork fillet — produces a
number that looks like the meal's calories and is not. Against the chains' own
published figures the totals for these twelve photographs run a median 34% low.
Identification and provenance are solid and are what the page shows; the total
is not, and is left out until it is.
"""
import json
import pprint
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/analyzer_examples"
OUT = ROOT / "dataset_manager/site/analyzer_examples.py"
DB = ROOT / "data/metadata/dataset_manager.db"

# The photographs the page shows, in the order it shows them. Chosen for what
# they demonstrate, not for how well they scored: a tray with many small dishes,
# a single-plate set, a ramen set.
SHOWN = ("9244", "5968", "7260")

HEADER = '''"""Worked examples of the analyzer, generated from its own responses.

DO NOT EDIT BY HAND — regenerate with `tools/build_analyzer_examples.py`, which
reads the saved API responses in `data/raw/analyzer_examples/`. Every figure on
the home page that describes what the analyzer did comes from here, so that a
claim about the product can be traced to the run that produced it.

`estimated_kcal` is the sum over MATCHED components only and is not the meal's
calories; `published_kcal` is what the chain discloses for the same menu item.
Neither is rendered as a total — see the generator for why.
"""

'''


def load(stem):
    return json.loads((RAW / f"{stem}.json").read_text(encoding="utf-8"))


def photo_for(conn, item_id):
    row = conn.execute(
        """SELECT pp.file, pp.chain, pp.dish, cn.energy_kcal
           FROM product_photos pp
           LEFT JOIN shop_menu_items smi ON smi.id = pp.shop_menu_item_id
           LEFT JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
           WHERE pp.shop_menu_item_id = ?""", (item_id,)).fetchone()
    return row


def example(conn, stem):
    data = load(stem)
    row = photo_for(conn, int(stem))
    if row is None:
        sys.exit(f"no product photo for {stem} — was the photo pruned?")
    file, chain, dish, published = row

    components = []
    for c in data.get("components") or []:
        match = c.get("db_match") or {}
        components.append({
            "name": c["identified"]["name_ja"],
            "confidence": c["identified"].get("confidence"),
            "grams": c["ai_estimate"].get("estimated_grams"),
            "match": match.get("title"),
            "url": match.get("url"),
            "per_100g_kcal": (match.get("per_100g") or {}).get("energy_kcal"),
            "dish_index": c.get("dish_index"),
        })
    unmatched = [{"name": u["name_ja"], "grams": u.get("estimated_grams"),
                  "dish_index": u.get("dish_index")}
                 for u in (data.get("unmatched") or [])]
    dishes = [{"name": d["name_ja"], "grams": d.get("grams"),
               "matched": d.get("n_matched"), "of": d.get("n_total")}
              for d in (data.get("dishes") or [])]

    return {
        "id": stem,
        "photo": file,
        "chain": chain,
        "menu_name": dish,
        "dishes": dishes,
        "components": components,
        "unmatched": unmatched,
        "n_identified": len(components) + len(unmatched),
        "n_matched": len(components),
        "estimated_kcal": round((data.get("totals") or {}).get("energy_kcal") or 0, 1),
        "published_kcal": published,
    }


def main():
    if not RAW.is_dir():
        sys.exit(f"{RAW} not found")
    conn = sqlite3.connect(DB)
    try:
        examples = [example(conn, stem) for stem in SHOWN]
    finally:
        conn.close()

    # pformat, not json.dumps: this file is imported, and JSON's null/true/false
    # are not Python. Python 3 repr leaves 鮭 as 鮭 rather than escaping it.
    body = pprint.pformat(examples, width=96, sort_dicts=False)
    OUT.write_text(HEADER + "EXAMPLES = " + body + "\n", encoding="utf-8")
    for e in examples:
        print(f"{e['menu_name'][:34]:36s} {e['n_matched']}/{e['n_identified']} matched, "
              f"{len(e['dishes'])} dishes")
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
