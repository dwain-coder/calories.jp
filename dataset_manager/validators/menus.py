"""Validation rules for the restaurant-menu snapshot.

The source is a CSV dropped by an extractor that no longer exists, and it has
four known defects. Every rule here REJECTS rather than repairs: a menu page
that quietly prints a repaired number is worse than one that prints nothing,
because the number is the only thing on the page a reader cannot check.

Pure functions, no database and no I/O, so the rules are testable on their own.
"""
import re

# Packaging and disposable utensils. They are line items on a bill, not dishes,
# and a menu page that lists 紙コップ next to a calorie column looks broken.
NON_FOOD = re.compile(
    r"袋|フォーク|スプーン|カトラリー|おしぼり|保冷剤|ドライアイス|使い捨て|容器代|紙皿|紙コップ"
)

# Some `restaurant_name` values are not restaurants — they are the section
# headings of a menu that the extractor mistook for the shop. Left in, each
# becomes a "shop" page with a handful of items and no identity, which is the
# largest single source of thin pages in the corpus.
SECTION_LABEL = re.compile(
    r"^(グランド|ランチ|ディナー|モーニング|ドリンク|フード|デザート|"
    r"サイド|セット|コース|テイクアウト|お品書き|メニュー)"
    r"(メニュー|表|一覧)?$"
)

# Best-effort meal-time tag; a keyword heuristic, not ground truth. First match
# wins, and the order matters: a 生ビールセット is a drink before it is a set.
MEALTIME_RULES = (
    ("breakfast", re.compile(r"朝食|モーニング|朝定食|朝ごはん|朝のセット")),
    ("dessert", re.compile(
        r"デザート|パフェ|ケーキ|アイス|スイーツ|プリン|ソフトクリーム|あんみつ|わらび餅|ぜんざい")),
    ("drinks", re.compile(
        r"ハイボール|ビール|日本酒|焼酎|サワー|カクテル|ワイン|飲み放題|ドリンク|生ビール|"
        r"ウイスキー|レモンサワー|梅酒|コーヒー|カフェオレ|カフェラテ|ラテ|紅茶|ソフトドリンク")),
    ("lunch", re.compile(r"ランチ|定食|昼|セット|御膳|膳|丼|カレー|ラーメン|うどん|そば|パスタ")),
)


def mealtime_of(text):
    """Which part of the day this dish belongs to, or None."""
    for name, rule in MEALTIME_RULES:
        if rule.search(text):
            return name
    return None


def is_non_food(name):
    return bool(NON_FOOD.search(name or ""))


def is_section_label(name):
    """Is this 'restaurant' actually a menu heading the extractor misread?"""
    return bool(SECTION_LABEL.match((name or "").strip()))


def _yen(raw):
    """A price in whole yen, or None.

    Keeps the decimal point on the way in. The cleaned CSV writes tax-included
    prices as floats ("1848.0"), and stripping every non-digit deletes the dot
    and silently multiplies the price by ten.
    """
    digits = re.sub(r"[^\d.]", "", str(raw or ""))
    if not digits:
        return None
    try:
        value = round(float(digits))
    except ValueError:
        return None
    return value if value > 0 else None


def price_of(listed_raw, tax_incl_raw):
    """(yen, tax_included) for one row — or (None, False) when neither is usable.

    `price_tax_incl` is unreliable: ~108 rows carry a garbage small number, e.g.
    3 against a ¥957 dish. A tax-included price is by definition never below the
    listed one, so a value that is below it is discarded rather than corrected,
    and the row falls back to the listed price with no 税込 claim attached.
    """
    listed = _yen(listed_raw)
    incl = _yen(tax_incl_raw)
    if listed is not None and incl is not None:
        return (incl, True) if incl >= listed else (listed, False)
    if listed is not None:
        return listed, False
    if incl is not None:
        return incl, True
    return None, False


def collapse_duplicates(rows):
    """Collapse repeated dishes; disagreeing prices become a span.

    101 of 253 stores repeat rows — 742 exact repeats, plus 663 where the same
    dish carries two different prices. Picking one of two prices invents a fact,
    so a disagreement is preserved as (min, max) and rendered as a range.

    `rows` are dicts with at least name/mealtime/price_yen/tax_incl. Order is
    preserved: the first appearance of a dish keeps its position on the menu.
    """
    prices = {}
    for row in rows:
        if row.get("price_yen"):
            prices.setdefault((row["name"], row.get("mealtime")), []).append(row["price_yen"])

    seen, out = set(), []
    for row in rows:
        key = (row["name"], row.get("mealtime"))
        if key in seen:
            continue
        seen.add(key)
        values = prices.get(key, [])
        merged = dict(row)
        if len(values) > 1 and min(values) != max(values):
            merged["price_yen"] = min(values)
            merged["price_max_yen"] = max(values)
        out.append(merged)
    return out
