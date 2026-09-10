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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))          # the matches are re-run from this checkout

RAW = ROOT / "data/raw/analyzer_examples"
OUT = ROOT / "dataset_manager/site/analyzer_examples.py"

# The photographs the page shows, in the order it shows them.
#
# Stock, not the chains'. The chain photographs are the only ones with a
# published calorie figure beside them, which is what makes them the benchmark
# in `tools/score_analyzer.py` — but they are also the chains' copyright, and
# the home page is the last place to lean on that. These are Pexels, whose
# licence permits commercial use and asks for no attribution, so the caption is
# a label rather than a credit.
#
# `fetch_stock.py` has an `example-*` slot per entry: with PEXELS_API_KEY set,
# `uv run python tools/fetch_stock.py --slot example-teishoku` refills one.
SHOWN = (
    {"id": "stock-analyzer", "photo": "/static/media/analyzer.jpg",
     "label": "幕の内弁当", "slot": "example-bento"},
    {"id": "stock-menu", "photo": "/static/media/menu.jpg",
     "label": "ラーメン・餃子・にぎりの一式", "slot": "example-ramen"},
)

HEADER = '''"""Worked examples of the analyzer, generated from its own responses.

DO NOT EDIT BY HAND — regenerate with `tools/build_analyzer_examples.py`, which
reads the saved API responses in `data/raw/analyzer_examples/`. Every figure on
the home page that describes what the analyzer did comes from here, so that a
claim about the product can be traced to the run that produced it.

No total is carried across: a sum over the components that matched, with the
ones that did not omitted, looks like the meal's calories and is not one.
"""

'''


def load(stem):
    return json.loads((RAW / f"{stem}.json").read_text(encoding="utf-8"))


def example(spec):
    """One worked example: the model's reading, matched by THIS repo's code.

    The saved response carries the matches the deployed site made when the
    photograph was analysed, which is a different thing from what the code in
    this checkout does — the first stock response listed 卵焼き and 酢飯 as
    unmatched, and both had been fixed in foodterms an hour earlier. The model's
    reading is the fixed input; the lookup is re-run, so the page always shows
    what the shipped matcher does rather than a snapshot of an older one.
    """
    from dataset_manager.api.analyzer import _match_food
    from dataset_manager.site import queries

    data = load(spec["id"])
    if not (ROOT / spec["photo"].lstrip("/")).is_file():
        sys.exit(f"{spec['photo']} is not on disk — run tools/fetch_stock.py")

    named = [(c["identified"], c["ai_estimate"].get("estimated_grams"),
              c.get("dish_index"))
             for c in data.get("components") or []]
    named += [({"name_ja": u.get("name_ja"), "name_en": u.get("name_en"),
                "confidence": u.get("confidence")},
               u.get("estimated_grams"), u.get("dish_index"))
              for u in data.get("unmatched") or []]

    components, unmatched, per_dish = [], [], {}
    for ident, grams, dish_index in named:
        seen = per_dish.setdefault(dish_index, [0, 0])
        seen[1] += 1
        hit = _match_food(ident.get("name_ja"), ident.get("name_en"), "ja")
        if not hit:
            unmatched.append({"name": ident.get("name_ja"), "grams": grams,
                              "dish_index": dish_index})
            continue
        seen[0] += 1
        nutrition = queries.food_nutrition_json(hit["item_id"]) or {}
        components.append({
            "name": ident.get("name_ja"),
            "confidence": ident.get("confidence"),
            "grams": grams,
            "match": hit.get("name") or hit.get("title"),
            "url": f"/food/{hit['slug']}",
            "per_100g_kcal": (nutrition.get("per_100g") or {}).get("energy_kcal"),
            "dish_index": dish_index,
        })

    dishes = []
    for i, d in enumerate(data.get("dishes") or []):
        matched, total = per_dish.get(i, [0, 0])
        dishes.append({"name": d["name_ja"], "grams": d.get("grams"),
                       "matched": matched, "of": total})

    return {
        "id": spec["id"],
        "photo": spec["photo"],
        "menu_name": spec["label"],
        "dishes": dishes,
        "components": components,
        "unmatched": unmatched,
        "n_identified": len(components) + len(unmatched),
        "n_matched": len(components),
        "unmatched_grams": round(sum(u.get("grams") or 0 for u in unmatched), 1) or None,
    }


def main():
    if not RAW.is_dir():
        sys.exit(f"{RAW} not found")
    examples = [example(spec) for spec in SHOWN]

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
