"""Parser for MAFF recipe quantity strings -> grams.

Conservative by design: returns None rather than guessing. A None quantity
excludes the ingredient from computed dish nutrition (coverage is reported).
"""
import re
import unicodedata

# Standard Japanese measuring spoons: 大さじ = 15ml, 小さじ = 5ml.
# Gram weight per 大さじ for common seasonings (調理のための計量, standard tables).
TABLESPOON_GRAMS = {
    "しょうゆ": 18.0, "醤油": 18.0, "みそ": 18.0, "味噌": 18.0,
    "砂糖": 9.0, "塩": 18.0, "油": 12.0, "サラダ油": 12.0, "ごま油": 12.0,
    "みりん": 18.0, "酒": 15.0, "酢": 15.0, "水": 15.0, "だし": 15.0,
}
TABLESPOON_DEFAULT = 15.0  # water-density fallback for liquids

# ml -> g at density 1.0 allowed only for these (water-like) liquids.
ML_AS_G_ALLOWLIST = ("水", "だし", "出汁", "湯", "酒", "みりん", "酢", "しょうゆ", "醤油", "牛乳")

# "to taste" style — no quantity.
NO_QUANTITY = ("適量", "適宜", "少々", "少量", "お好み", "ひとつまみ")

_NUM = r"(\d+(?:\.\d+)?)"


def _spoon_grams(name, count, spoon_ml):
    for key, g in TABLESPOON_GRAMS.items():
        if key in name:
            return count * g * (spoon_ml / 15.0)
    return count * TABLESPOON_DEFAULT * (spoon_ml / 15.0)


def parse_quantity(text, name=""):
    """Parse a quantity string (e.g. '2kg（2本）', '600g', '大さじ1', '適量')
    to grams, or None when no grounded conversion exists."""
    if not text:
        return None
    t = unicodedata.normalize("NFKC", text).strip()
    # Drop parenthetical alternates: 2kg（2本） -> 2kg
    t = re.sub(r"[（(][^）)]*[）)]", "", t).strip()

    if any(k in t for k in NO_QUANTITY):
        return None

    m = re.search(_NUM + r"\s*kg", t, re.IGNORECASE)
    if m:
        return float(m.group(1)) * 1000.0
    m = re.search(_NUM + r"\s*(?:g|グラム)", t, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(_NUM + r"\s*(?:ml|cc|ミリリットル)", t, re.IGNORECASE)
    if m:
        if any(k in name for k in ML_AS_G_ALLOWLIST):
            return float(m.group(1))  # density 1.0 for water-like liquids only
        return None
    m = re.search(r"大さじ\s*" + _NUM, t)
    if m:
        return _spoon_grams(name, float(m.group(1)), 15.0)
    m = re.search(r"小さじ\s*" + _NUM, t)
    if m:
        return _spoon_grams(name, float(m.group(1)), 5.0)
    m = re.search(_NUM + r"\s*(?:L|リットル)", t)
    if m:
        if any(k in name for k in ML_AS_G_ALLOWLIST):
            return float(m.group(1)) * 1000.0
        return None
    # Counts (本/個/枚/束/尾/丁/カップ/合...) have no reliable per-food weight in
    # our data — refuse rather than invent. ponytail: add per-food weights when
    # FDC portions or a curated table cover them.
    return None


def parse_recipe_lines(recipe_ingredients):
    """Split a MAFF recipe_ingredients blob into (line_no, name, quantity_text, grams).

    Lines are usually 'name\\tquantity'; legacy lines may use spaces — then the
    last whitespace-separated run is treated as the quantity.
    """
    out = []
    if not recipe_ingredients:
        return out
    for i, line in enumerate(recipe_ingredients.splitlines()):
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            name, _, qty = line.partition("\t")
        else:
            parts = line.rsplit(None, 1)
            name, qty = (parts[0], parts[1]) if len(parts) == 2 else (line, "")
        name, qty = name.strip(), qty.strip()
        out.append((i, name, qty, parse_quantity(qty, name)))
    return out
