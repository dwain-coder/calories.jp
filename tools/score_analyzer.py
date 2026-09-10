"""Score the analyzer's matching against the chains' own published calories.

    uv run python tools/score_analyzer.py
    uv run python tools/score_analyzer.py --misses

The model's reading of a photograph is expensive and non-deterministic; the
matching that turns its ingredient names into composition-table rows is neither.
So this replays the SAVED responses in `data/raw/analyzer_examples/` — the model
output is fixed input — through the live `_match_food`, recomputes the total,
and compares it with what the chain publishes for that same menu item.

That makes the matcher measurable on its own. A change to foodterms shows up
here as a number, and the twelve rows below are a regression set rather than a
spot check: 1,052 of the photographs on disk have a published figure beside
them, so it can be widened whenever it stops discriminating.

WHAT THE SCORE IS NOT. A perfect matcher would still not land on the published
figure every time — the chain weighs its own portions and we are reading a
photograph of a promotional plate. The target is the bias: a median that sits
near zero rather than 34% low, and no dish carrying a large unmatched component
in silence.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RAW = ROOT / "data/raw/analyzer_examples"
DB = ROOT / "data/metadata/dataset_manager.db"


def published(conn, item_id):
    row = conn.execute(
        """SELECT pp.chain, pp.dish, cn.energy_kcal
           FROM product_photos pp
           LEFT JOIN shop_menu_items smi ON smi.id = pp.shop_menu_item_id
           LEFT JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
           WHERE pp.shop_menu_item_id = ?""", (item_id,)).fetchone()
    return row


def rescore(response, lang="ja"):
    """Re-match every ingredient the model named, and re-total.

    Reads the model's output only — `identified` and `estimated_grams` — so the
    figure it produces is entirely the current matcher's doing.
    """
    from dataset_manager.api.analyzer import _match_food
    from dataset_manager.site import queries

    kcal = 0.0
    hits, misses = [], []
    named = ([(c["identified"], c["ai_estimate"].get("estimated_grams"))
              for c in response.get("components") or []]
             + [({"name_ja": u.get("name_ja"), "name_en": u.get("name_en")},
                 u.get("estimated_grams")) for u in response.get("unmatched") or []])

    for ident, grams in named:
        name_ja, name_en = ident.get("name_ja"), ident.get("name_en")
        match = _match_food(name_ja, name_en, lang)
        if not match:
            misses.append((name_ja, grams or 0))
            continue
        nut = queries.food_nutrition_json(match["item_id"])
        per100 = (nut or {}).get("per_100g") or {}
        energy = per100.get("energy_kcal")
        if energy is not None and grams:
            kcal += energy * grams / 100.0
        hits.append((name_ja, match.get("name") or match.get("title"), energy, grams))
    return kcal, hits, misses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--misses", action="store_true",
                    help="list every ingredient that still matches nothing")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows, all_misses = [], []
    for path in sorted(RAW.glob("*.json")):
        if not path.stem.isdigit():
            continue          # a home page example, not a scored chain photograph
        response = json.loads(path.read_text(encoding="utf-8"))
        info = published(conn, int(path.stem))
        if not info or info[2] is None:
            continue
        chain, dish, pub = info
        kcal, _hits, misses = rescore(response)
        was = (response.get("totals") or {}).get("energy_kcal") or 0
        all_misses += misses
        rows.append((chain, dish, pub, was, kcal, misses))
    conn.close()

    if not rows:
        sys.exit("no scored photographs — is data/raw/analyzer_examples/ populated?")

    print(f"{'chain':12s} {'dish':30s} {'published':>9s} {'saved':>7s} {'now':>7s} "
          f"{'err':>6s}  unmatched")
    for chain, dish, pub, was, now, misses in sorted(rows, key=lambda r: r[2]):
        err = (now - pub) / pub * 100
        print(f"{chain[:11]:12s} {dish[:28]:30s} {pub:9.0f} {was:7.0f} {now:7.0f} "
              f"{err:+5.0f}%  {len(misses)}")

    errs = sorted((now - pub) / pub * 100 for _c, _d, pub, _w, now, _m in rows)
    n = len(errs)
    median = errs[n // 2] if n % 2 else (errs[n // 2 - 1] + errs[n // 2]) / 2
    within = sum(1 for e in errs if abs(e) <= 25)
    print(f"\nn={n}  median {median:+.0f}%  mean {sum(errs)/n:+.0f}%  "
          f"within ±25%: {within}/{n}  unmatched ingredients: {len(all_misses)}")

    if args.misses and all_misses:
        print("\nstill matching nothing:")
        for name, grams in sorted(set(all_misses), key=lambda x: -x[1]):
            print(f"  {grams:6.0f} g  {name}")


if __name__ == "__main__":
    main()
