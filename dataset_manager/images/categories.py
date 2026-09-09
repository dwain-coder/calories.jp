"""What kind of dish this is, when no photograph of the dish itself exists.

375 of the 1,364 regional dishes have a free photograph of that actual dish. The
rest had nothing, and a page with nothing on it is what a reader reads as broken.

The answer is not to loosen the search until every page has something — that is
how 「あずま」 ended up illustrated with a sweet potato. It is to show a picture of
the RIGHT KIND OF THING and say that is what it is: 「煮物のイメージ」 under a
photograph of a simmered dish is true, useful, and cannot be mistaken for a
photograph of this particular one.

Two signals, in order:

1. **The dish's form, from its name.** 「けんちん汁」 is a soup, 「笹ずし」 is rice.
   This is what a reader would guess from the name too, so it cannot surprise
   them.
2. **The heaviest real ingredient**, from the recipe links. Seasonings are
   excluded: the matcher resolved the pantry better than anything else, so soy
   sauce is the heaviest resolved ingredient in a hundred of these recipes and
   says nothing about what the dish looks like.
"""
import re

# Ordered: the first form word found wins, so the more specific patterns come
# first. 「そば粉のクレープ」 is a crêpe, not noodles, which is why 麺 is checked
# after 菓子.
FORMS = (
    ("菓子", r"菓子|カステラ|ようかん|羊羹|飴|あめ|かりんとう|せんべい|煎餅|クレープ"),
    ("餅・団子", r"餅|もち|団子|だんご|まんじゅう|饅頭|大福|団子"),
    ("汁物", r"汁|スープ|吸い物|すまし|雑炊|粥|かゆ"),
    ("麺", r"そば|うどん|ラーメン|らーめん|そうめん|素麺|冷麦|麺|めん"),
    ("ご飯", r"飯|めし|ごはん|ご飯|丼|寿司|ずし|すし|おにぎり|巻き|いなり"),
    ("漬物", r"漬|づけ|なれずし|ぬか"),
    ("揚げ物", r"揚げ|フライ|天ぷら|唐揚|からあげ|コロッケ"),
    ("焼き物", r"焼き|焼|グリル|ソテー"),
    ("煮物", r"煮|炊き|含め|しぐれ|甘露"),
    ("和え物", r"和え|あえ|なます|酢の物|サラダ|浸し|びたし"),
    ("鍋物", r"鍋|しゃぶ|すき焼"),
)

# MEXT food groups that describe a dish's appearance. The ones left out —
# seasonings, sugar, fats, drinks — are what the recipe matcher resolves best
# and what a photograph shows least.
INGREDIENT_GROUPS = {
    "魚介類": "魚介",
    "肉類": "肉",
    "野菜類": "野菜",
    "豆類": "豆",
    "穀類": "穀類",
    "いも及びでん粉類": "いも",
    "果実類": "果物",
    "きのこ類": "きのこ",
    "藻類": "海藻",
    "卵類": "卵",
    "乳類": "乳製品",
    "種実類": "木の実",
}
UNINFORMATIVE = {
    "調味料及び香辛料類", "砂糖及び甘味類", "油脂類", "し好飲料類", "調理済み流通食品類",
}

FALLBACK = "和食"

# The Japanese Wikipedia ARTICLE to take a lead image from, per category. Not a
# Commons search: the first search hit for 「穀類」 was a German hotel breakfast,
# for 「乳製品」 a photograph of casein precipitating in a lab, and for 「木の実」 the
# split husk of a horse chestnut. An article's lead image was chosen by someone
# to illustrate that subject.
#
# Five categories are deliberately absent — 魚介, 卵, きのこ, 海藻, 果物. Nothing
# usable came back for them (「魚料理」 returns a Finnish supermarket label,
# 「卵焼き」 a photograph of a yakitori bar), and the dishes that would have used
# them fall through to 和食 rather than carry something wrong.
ARTICLES = {
    "菓子": "和菓子",
    "餅・団子": "大福",
    "汁物": "味噌汁",
    "麺": "うどん",
    "ご飯": "丼物",
    "漬物": "漬物",
    "揚げ物": "天ぷら",
    "焼き物": "焼き魚",
    "煮物": "煮物",
    "和え物": "おひたし",
    "鍋物": "闇鍋",
    "肉": "焼肉",
    # Not the article 「野菜」 — its lead image is a market stall, and a crate of
    # cabbages is not what a vegetable DISH looks like.
    "野菜": "煮しめ",
    "豆": "煮豆",
    "穀類": "おにぎり",
    "いも": "芋煮",
    "乳製品": "牛乳",
    "木の実": "栗",
    "和食": "日本料理",
}

ALL = tuple(ARTICLES)


def form_of(name):
    """The dish's form from its name, or None."""
    for label, pattern in FORMS:
        if re.search(pattern, name or ""):
            return label
    return None


def from_ingredient(group):
    """A category from a MEXT food group, or None if the group says nothing."""
    if not group or group in UNINFORMATIVE:
        return None
    return INGREDIENT_GROUPS.get(group)


def classify(name, dominant_group=None):
    """The category to illustrate this dish with. Never None."""
    return form_of(name) or from_ingredient(dominant_group) or FALLBACK
