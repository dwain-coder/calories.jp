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

# Edible weight of one of a thing, per food and counter.
#
# These are conventional Japanese kitchen reference weights (可食部, medium
# size), not measurements: a carrot is not 150 g, carrots are about 150 g. So
# a quantity derived here is tagged 'unit' and the dish page says how many of
# its ingredients were weighed this way. That distinction is the whole reason
# this table is allowed to exist — 4,386 recipe lines carry a count and no
# weight, and refusing all of them left hundreds of dishes with no figures at
# all, while inventing them silently would have been worse.
#
# Only foods listed here convert. An unknown food with a count stays None,
# exactly as before.
UNIT_GRAMS = {
    # vegetables
    "にんじん": {"本": 150.0}, "人参": {"本": 150.0},
    "だいこん": {"本": 800.0}, "大根": {"本": 800.0},
    "たまねぎ": {"個": 200.0, "玉": 200.0}, "玉ねぎ": {"個": 200.0, "玉": 200.0},
    "玉葱": {"個": 200.0, "玉": 200.0},
    "じゃがいも": {"個": 150.0}, "馬鈴薯": {"個": 150.0},
    "さつまいも": {"本": 250.0}, "さといも": {"個": 50.0}, "里芋": {"個": 50.0},
    "きゅうり": {"本": 100.0}, "胡瓜": {"本": 100.0},
    "なす": {"個": 80.0, "本": 80.0}, "茄子": {"個": 80.0, "本": 80.0},
    "トマト": {"個": 150.0}, "ミニトマト": {"個": 15.0},
    "ピーマン": {"個": 35.0}, "キャベツ": {"個": 1000.0, "玉": 1000.0},
    "はくさい": {"株": 2000.0}, "白菜": {"株": 2000.0},
    "ねぎ": {"本": 100.0}, "長ねぎ": {"本": 100.0},
    "ほうれん草": {"束": 200.0}, "ほうれんそう": {"束": 200.0},
    "こまつな": {"束": 200.0}, "小松菜": {"束": 200.0},
    "にら": {"束": 100.0}, "しょうが": {"かけ": 15.0, "片": 15.0},
    "生姜": {"かけ": 15.0, "片": 15.0},
    "にんにく": {"かけ": 6.0, "片": 6.0, "個": 50.0},
    "ごぼう": {"本": 150.0}, "れんこん": {"節": 200.0},
    "たけのこ": {"本": 400.0}, "とうもろこし": {"本": 250.0},
    "かぼちゃ": {"個": 1200.0}, "しいたけ": {"個": 15.0, "枚": 15.0},
    "レモン": {"個": 100.0}, "りんご": {"個": 250.0}, "みかん": {"個": 100.0},
    "バナナ": {"本": 100.0}, "梅": {"個": 10.0},

    # soy, eggs, dairy
    "豆腐": {"丁": 300.0}, "厚揚げ": {"枚": 120.0}, "生揚げ": {"枚": 120.0},
    "油揚げ": {"枚": 30.0}, "納豆": {"パック": 50.0},
    "卵": {"個": 50.0}, "たまご": {"個": 50.0}, "鶏卵": {"個": 50.0},
    "うずら卵": {"個": 10.0},

    # fish, meat, and things sold by the piece
    "あじ": {"尾": 100.0}, "いわし": {"尾": 60.0}, "さんま": {"尾": 130.0},
    "さば": {"尾": 400.0}, "鮭": {"切れ": 80.0}, "さけ": {"切れ": 80.0},
    "ぶり": {"切れ": 80.0}, "たら": {"切れ": 80.0},
    "ちくわ": {"本": 30.0}, "かまぼこ": {"本": 150.0},
    "えび": {"尾": 15.0}, "干ししいたけ": {"枚": 3.0},

    # staples and wrappers
    "食パン": {"枚": 60.0}, "のり": {"枚": 3.0}, "海苔": {"枚": 3.0},
    "焼きのり": {"枚": 3.0}, "こんにゃく": {"枚": 250.0, "丁": 250.0},
    "うどん": {"玉": 200.0}, "そば": {"束": 100.0}, "そうめん": {"束": 50.0},
    "餅": {"個": 50.0}, "もち": {"個": 50.0},
}

# 1 カップ = 200 ml. Dry goods measured by cup have their own weights.
CUP_GRAMS = {"米": 170.0, "こめ": 170.0, "もち米": 175.0, "小麦粉": 110.0,
             "薄力粉": 110.0, "強力粉": 110.0, "砂糖": 130.0, "パン粉": 40.0}
CUP_ML = 200.0

_COUNTERS = ("本", "個", "枚", "丁", "束", "玉", "尾", "切れ", "株", "節",
             "かけ", "片", "パック")


def _unit_grams(name, count, counter):
    """Grams for `count` of a counted food, or None when we have no weight
    for that food and counter. Longest food name wins, so 「ミニトマト」 is not
    read as 「トマト」."""
    for food in sorted(UNIT_GRAMS, key=len, reverse=True):
        if food in name:
            per = UNIT_GRAMS[food].get(counter)
            return count * per if per else None
    return None

_NUM = r"(\d+(?:\.\d+)?)"

# Counts come with fractions far more often than weights do: 「1/2本」,
# 「1と1/2カップ」, 「中1/2個」. Reading the denominator as the count turns half
# a burdock root into two of them, so the number in front of a counter is
# parsed as an optional whole part, a numerator, and an optional denominator.
_COUNT_NUM = r"(?:(\d+)\s*と\s*)?(\d+(?:\.\d+)?)(?:\s*/\s*(\d+))?"


def _count_value(whole, num, den):
    value = float(num) / float(den) if den else float(num)
    return value + float(whole) if whole else value


def _spoon_grams(name, count, spoon_ml):
    for key, g in TABLESPOON_GRAMS.items():
        if key in name:
            return count * g * (spoon_ml / 15.0)
    return count * TABLESPOON_DEFAULT * (spoon_ml / 15.0)


def parse_quantity(text, name=""):
    """Grams for a quantity string, or None. See parse_quantity_detail."""
    return parse_quantity_detail(text, name)[0]


def parse_quantity_detail(text, name=""):
    """Parse a quantity string (e.g. '2kg（2本）', '600g', '大さじ1', '適量')
    into (grams, source), or (None, None) when no grounded conversion exists.

    source is 'measure' when the recipe stated a weight or a standard measure,
    and 'unit' when the weight came from a reference weight for one of a thing
    — a carrot, a slice of abura-age. The caller keeps them apart so a dish
    page can say which of its ingredients were assumed rather than stated.
    """
    if not text:
        return None, None
    t = unicodedata.normalize("NFKC", text).strip()
    # Drop parenthetical alternates: 2kg（2本） -> 2kg
    t = re.sub(r"[（(][^）)]*[）)]", "", t).strip()

    if any(k in t for k in NO_QUANTITY):
        return None, None

    m = re.search(_NUM + r"\s*kg", t, re.IGNORECASE)
    if m:
        return float(m.group(1)) * 1000.0, "measure"
    m = re.search(_NUM + r"\s*(?:g|グラム)", t, re.IGNORECASE)
    if m:
        return float(m.group(1)), "measure"
    m = re.search(_NUM + r"\s*(?:ml|cc|ミリリットル)", t, re.IGNORECASE)
    if m:
        if any(k in name for k in ML_AS_G_ALLOWLIST):
            return float(m.group(1)), "measure"  # density 1.0, water-like only
        return None, None
    m = re.search(r"大さじ\s*" + _NUM, t)
    if m:
        return _spoon_grams(name, float(m.group(1)), 15.0), "measure"
    m = re.search(r"小さじ\s*" + _NUM, t)
    if m:
        return _spoon_grams(name, float(m.group(1)), 5.0), "measure"
    m = re.search(_NUM + r"\s*(?:L|リットル)", t)
    if m:
        if any(k in name for k in ML_AS_G_ALLOWLIST):
            return float(m.group(1)) * 1000.0, "measure"
        return None, None
    # Cups: liquids by volume, dry goods by their own weight.
    m = re.search(_COUNT_NUM + r"\s*カップ", t)
    if m:
        count = _count_value(*m.groups())
        for food, g in CUP_GRAMS.items():
            if food in name:
                return count * g, "unit"
        if any(k in name for k in ML_AS_G_ALLOWLIST):
            return count * CUP_ML, "unit"
        return None, None

    # Counts: converted only for foods with a curated reference weight, and
    # flagged as an assumption. Everything else still refuses.
    m = re.search(_COUNT_NUM + r"\s*(" + "|".join(_COUNTERS) + ")", t)
    if m:
        grams = _unit_grams(name, _count_value(*m.groups()[:3]), m.group(4))
        return (grams, "unit") if grams is not None else (None, None)
    return None, None


def parse_recipe_lines(recipe_ingredients):
    """Split a MAFF recipe_ingredients blob into
    (line_no, name, quantity_text, grams, grams_source).

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
        grams, source = parse_quantity_detail(qty, name)
        out.append((i, name, qty, grams, source))
    return out
