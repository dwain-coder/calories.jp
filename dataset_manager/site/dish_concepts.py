"""Which Japanese Wikipedia article illustrates each kind of menu dish.

The photo catalogue was written for fast food, and this corpus is 233 chains —
izakaya, cafés, family restaurants, teishoku counters. 44.8% of menu rows fell
through to one generic photograph, which is a stock image repeated eight
thousand times.

An ARTICLE's lead image, not a Commons search. The search results for 「定食」
include a Finnish supermarket shelf; an article's lead image was chosen by
someone to show that subject. This is the same decision, and for the same
reason, as dataset_manager/images/categories.py.

Keys extend DISH_PHOTO_CATALOG in food_images.py. Where a key already exists
there, the article named here replaces its Unsplash entry with a real,
freely-licensed photograph.
"""

# Ordered like CLASSIFICATION_RULES: specific before general, because the
# matcher takes the pattern that ends last and breaks ties on this order.
ARTICLES = {
    # Set meals and formats — the largest single gap
    "teishoku": "定食",
    "bento": "弁当",
    "donburi_rice": "丼物",

    # Izakaya
    "yakitori": "焼き鳥",
    "edamame": "枝豆",
    "hiyayakko": "冷奴",
    "oden": "おでん",
    "sashimi": "舟盛り",
    "tempura": "天ぷら",
    "tamagoyaki": "だし巻き卵",
    "korokke": "コロッケ",
    "takoyaki": "たこ焼き",
    "okonomiyaki": "お好み焼き",
    "yakisoba": "焼きそば",
    "chawanmushi": "茶碗蒸し",
    "tsukemono": "漬物",

    # Western and café plates
    "omurice": "オムライス",
    "gratin": "グラタン",
    "doria": "ドリア",
    "risotto": "リゾット",
    "sandwich": "サンドイッチ",
    "roast_beef": "ローストビーフ",
    "steak_plate": "ビーフステーキ",
    "napolitan": "ナポリタン",

    # Chinese
    "mapo_tofu": "麻婆豆腐",
    "subuta": "酢豚",
    "ebi_chili": "エビチリ",
    "chahan": "チャーハン",
    "shumai": "焼売",
    "ramen_tsukemen": "つけ麺",

    # Korean and other
    "bibimbap": "ビビンバ",
    "samgyeopsal": "サムギョプサル",
    "pho": "フォー",
    "tacos": "タコス",
    "kebab": "ケバブ",
    "curry_rice": "カレーライス",

    # Sweets
    "shortcake": "ショートケーキ",
    "anmitsu": "あんみつ",
    "dorayaki": "どら焼き",
    "soft_serve": "ソフトクリーム",

    # Drinks
    "smoothie": "スムージー",
    "cocktail": "カクテル",
    "sake_drink": "日本酒",
    "shochu": "焼酎",
    "wine_drink": "赤ワイン",
}

# Existing catalogue keys whose Unsplash entry should become a real photograph.
# Same key, so nothing about matching changes — only where the picture is from.
REPLACE = {
    "sushi_platter": "寿司",
    "sushi_salmon": "握り寿司",
    "sushi_tuna": "鉄火丼",
    "sushi_roll": "巻き寿司",
    "ramen_shoyu": "ラーメン",
    "ramen_miso": "味噌ラーメン",
    "ramen_tonkotsu": "豚骨ラーメン",
    "udon": "うどん",
    "soba": "蕎麦",
    "pasta": "パスタ",
    "gyudon_beef": "牛丼",
    "yakiniku_steak": "焼肉",
    "tonkatsu_pork": "とんかつ",
    "karaage_chicken": "唐揚げ",
    "curry": "カレーライス",
    "gyoza": "餃子",
    "pizza": "ピザ",
    "french_fries": "フライドポテト",
    "onion_rings": "オニオンリング",
    "salad_green": "サラダ",
    "soup_miso": "味噌汁",
    "soup_corn": "ポタージュ",
    "pancakes": "パンケーキ",
    "cake_dessert": "ケーキ",
    "donut": "ドーナツ",
    "icecream_parfait": "アイスクリーム",
    "toast_breakfast": "トースト",
    "coffee": "コーヒー",
    "tea_matcha": "抹茶",
    "juice_beverage": "ジュース",
    "beer_alcohol": "ビール",
    "burger_classic": "ハンバーガー",
    "burger_cheese": "チーズバーガー",
    "hotdog": "ホットドッグ",
    "culinary_default": "定食",
}

ALL = {**REPLACE, **ARTICLES}
