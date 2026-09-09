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

# Added after auditing all 193 chain pages rather than the corpus average. The
# frequent unmatched names were not exotic — rice, eggs, natto, milk, yakiniku
# cuts, izakaya sides — and each of them was showing a stock set-meal photo.
LATER = {
    "gohan_rice": "米飯",
    "tamago_egg": "目玉焼き",
    "natto": "納豆",
    "milk_drink": "牛乳",
    "cocoa_drink": "ココア",
    "yasai_itame": "野菜炒め",
    "fry_seafood": "フライ (料理)",
    "gyutan": "牛タン",
    "horumon": "ホルモン",
    "namul": "ナムル",
    "kimchi": "キムチ",
    "chashu": "チャーシュー",
    "tenshinhan": "天津飯",
    "hiyashi_chuka": "冷やし中華",
    "motsunabe": "もつ鍋",
    "shabu": "しゃぶしゃぶ",
    "sukiyaki": "すき焼き",
    "unagi": "鰻丼",
    "katsudon": "カツ丼",
    "onigiri": "おにぎり",
    "miso_dengaku": "田楽",
    "ajillo": "アヒージョ",
    "carpaccio": "カルパッチョ",
    "bruschetta": "ブルスケッタ",
    "prosciutto": "生ハム",
    "minestrone": "ミネストローネ",
    "risotto_it": "リゾット",
    "paella": "パエリア",
    "nachos": "ナチョス",
    "burrito": "ブリトー",
    "fish_and_chips": "フィッシュ・アンド・チップス",
    "sausage": "ソーセージ",
    "bacon_dish": "ベーコン",
    "cheese_plate": "チーズ",
    "olive": "オリーブ",
    "nuts_snack": "ナッツ",
    "popcorn": "ポップコーン",
    "pudding": "プリン",
    "crepe_sweet": "クレープ",
    "waffle": "ワッフル",
    "cookie": "クッキー",
    "chocolate": "チョコレート",
    "lemonade": "レモネード",
    "cola_drink": "コーラ",
    "oolong_tea": "ウーロン茶",
    "green_tea": "緑茶",
    "whisky": "ウイスキー",
    "chuhai": "チューハイ",
    "champagne": "シャンパン",
}

ALL = {**ALL, **LATER}

# Second pass, after looking at every photograph in the set. 抹茶's lead image
# is a spoonful of powder, which is not a drink and was serving 326 rows of
# 紅茶 and 烏龍茶. ホルモン's article is about the hormone. The rest are articles
# whose lead image was unusable, retried against a more specific title.
RETRY = {
    "tea_matcha": "紅茶",
    "salad_green": "シーザーサラダ",
    "sushi_shrimp": "握り寿司",
    "cheese_plate": "ナチュラルチーズ",
    "gohan_rice": "白米",
    "gyoza": "焼き餃子",
    "pancakes": "ホットケーキ",
    "horumon": "ホルモン焼き",
    "bacon_dish": "ベーコンエッグ",
    "oolong_tea": "烏龍茶",
    "pudding": "カスタードプディング",
    "burger_chicken": "チキンバーガー",
    "prosciutto": "ハム",
    "soup_corn": "コーンスープ",
    "waffle": "ベルギーワッフル",
    "ramen_tonkotsu": "博多ラーメン",
    "burger_fish_shrimp": "フィレオフィッシュ",
    "burrito": "ブリート",
    "popcorn": "ポップコーン",
    # A hamburg steak is a patty on a plate, not meat on a grill — it was
    # sharing the yakiniku photograph.
    "hamburg": "ハンバーグ",
}

ALL = {**ALL, **RETRY}

# Some dishes have no Japanese article whose lead image shows them. 白米's is a
# heap of dry grains, 茶碗's is an empty bowl. Where the article route cannot
# work, name the Commons file directly — chosen by looking at it, not by
# trusting a search rank, which returned a 1935 pancake-flour advert for
# 「cheese platter」.
FILES = {
    "gohan_rice": "Steamed rice in bowl 01.jpg",
    "popcorn": "Bowl of Popcorn (Unsplash).jpg",
    "oolong_tea": "Oolong tea being poured, Holiday Restaurant, Semarang, 2014-06-19.jpg",
    "burger_chicken": "Chicken-burger-combo (1).jpg",
}

# Third pass, from looking at all 130. Each of these had an article whose lead
# image is the ingredient, the plant or the festival rather than the dish:
# ココア gave a cacao pod, オリーブ an olive tree, 田楽 the 王子田楽 festival,
# 野菜炒め an Indian aubergine curry, 牛タン raw tongue on a butcher's board.
FILES = {**FILES,
    "cocoa_drink": "Cup of Hot Chocolate.jpg",
    "olive": "Fresh green olives and black olives served as appetizers.jpg",
    "miso_dengaku": "Dengaku (2384193986).jpg",
    "yasai_itame": "Plates of stir-fried vegetables in Din Tai Fung.jpg",
}

# Nothing freely licensed shows these as a dish. They keep the bundled
# photograph rather than carry a wrong one.
for _dead in ("gyutan", "prosciutto", "nuts_snack", "risotto_it", "olive"):
    ALL.pop(_dead, None)
