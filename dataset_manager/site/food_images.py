"""Authentic food photography mapping for restaurant menu items.

Assigns appetizing, high-resolution food images to every dish across
chains and culinary categories.
"""
import re
import sqlite3
from functools import lru_cache
from typing import Dict, Any, Optional

UNSPLASH_BASE = "https://images.unsplash.com"

# Photographic catalog of authentic, appetizing food photography
# Thumbnails are scaled and center-cropped with WebP format support.
DISH_PHOTO_CATALOG = {
    # Burgers & Sandwiches
    "burger_cheese": {
        "id": "photo-1550547660-d9450f859349",
        "category": "チーズバーガー",
        "local": "/static/media/food/burger.webp",
    },
    "burger_chicken": {
        "id": "photo-1606755962773-d324e0a13086",
        "category": "チキンバーガー",
        "local": "/static/media/food/burger.webp",
    },
    "burger_fish_shrimp": {
        "id": "photo-1521305916504-4a1121188589",
        "category": "海老・フィッシュバーガー",
        "local": "/static/media/food/burger.webp",
    },
    "burger_classic": {
        "id": "photo-1568901346375-23c9450c58cd",
        "category": "ハンバーガー",
        "local": "/static/media/food/burger.webp",
    },
    "hotdog": {
        "id": "photo-1619740455993-9e612b1af08a",
        "category": "ホットドッグ",
        "local": "/static/media/food/hotdog.webp",
    },
    # Sushi & Seafood
    "sushi_salmon": {
        "id": "photo-1617196034796-73dfa7b1fd56",
        "category": "サーモン寿司",
        "local": "/static/media/food/sushi.webp",
    },
    "sushi_tuna": {
        "id": "photo-1579871494447-9811cf80d66c",
        "category": "まぐろ寿司",
        "local": "/static/media/food/sushi.webp",
    },
    "sushi_shrimp": {
        "id": "photo-1562436260-8c9216eeb703",
        "category": "えび寿司",
        "local": "/static/media/food/sushi.webp",
    },
    "sushi_eel": {
        "id": "photo-1584278858536-52532423b9ea",
        "category": "うなぎ・穴子",
        "local": "/static/media/food/sushi.webp",
    },
    "sushi_roll": {
        "id": "photo-1579584425555-c3ce17fd4351",
        "category": "巻き寿司・軍艦",
        "local": "/static/media/food/sushi.webp",
    },
    "sushi_platter": {
        "id": "photo-1553621042-f6e147245754",
        "category": "握り寿司・海鮮",
        "local": "/static/media/food/sushi.webp",
    },
    # Ramen & Noodles
    "ramen_miso": {
        "id": "photo-1552611052-33e04de081de",
        "category": "味噌ラーメン",
        "local": "/static/media/food/ramen.webp",
    },
    "ramen_tonkotsu": {
        "id": "photo-1591814468924-caf88d1232e1",
        "category": "豚骨ラーメン",
        "local": "/static/media/food/ramen.webp",
    },
    "ramen_shoyu": {
        "id": "photo-1569718212165-3a8278d5f624",
        "category": "醤油ラーメン",
        "local": "/static/media/food/ramen.webp",
    },
    "udon": {
        "id": "photo-1618841557871-b4664fbf0cb3",
        "category": "うどん",
        "local": "/static/media/food/udon.webp",
    },
    "soba": {
        "id": "photo-1519984388953-d2406bc725e1",
        "category": "そば",
        "local": "/static/media/food/soba.webp",
    },
    # Beef Bowls & Meats
    "gyudon_beef": {
        "id": "photo-1544025162-d76694265947",
        "category": "牛丼・肉料理",
        "local": "/static/media/food/gyudon.webp",
    },
    "yakiniku_steak": {
        "id": "photo-1558030006-450675393462",
        "category": "ステーキ・焼肉",
        "local": "/static/media/food/gyudon.webp",
    },
    # Pork & Fried Food
    "tonkatsu_pork": {
        "id": "photo-1603360946369-dc9bb6258143",
        "category": "とんかつ・カツ",
        "local": "/static/media/food/chicken.webp",
    },
    "karaage_chicken": {
        "id": "photo-1626082927389-6cd097cdc6ec",
        "category": "チキン・から揚げ",
        "local": "/static/media/food/chicken.webp",
    },
    # Curry & Rice
    "curry": {
        "id": "photo-1588166524941-3bf61a9c41db",
        "category": "カレー",
        "local": "/static/media/food/curry.webp",
    },
    "gyoza": {
        "id": "photo-1498654896293-37aacf113fd9",
        "category": "餃子・点心",
        "local": "/static/media/food/gyoza.webp",
    },
    "pizza": {
        "id": "photo-1513104890138-7c749659a591",
        "category": "ピザ",
        "local": "/static/media/food/pizza.webp",
    },
    "pasta": {
        "id": "photo-1551183053-bf91a1d81141",
        "category": "パスタ",
        "local": "/static/media/food/pasta.webp",
    },
    # Sides & Salads
    "french_fries": {
        "id": "photo-1630384060421-cb20d0e0649d",
        "category": "ポテト・フライ",
        "local": "/static/media/food/fries.webp",
    },
    "onion_rings": {
        "id": "photo-1630384060421-cb20d0e0649d",
        "category": "オニオンフライ",
        "local": "/static/media/food/fries.webp",
    },
    "salad_green": {
        "id": "photo-1512621776951-a57141f2eefd",
        "category": "サラダ",
        "local": "/static/media/food/salad.webp",
    },
    # Soups
    "soup_miso": {
        "id": "photo-1547592166-23ac45744acd",
        "category": "味噌汁・スープ",
        "local": "/static/media/food/soup.webp",
    },
    "soup_corn": {
        "id": "photo-1547592166-23ac45744acd",
        "category": "スープ・チャウダー",
        "local": "/static/media/food/soup.webp",
    },
    # Desserts & Bakery
    "icecream_parfait": {
        "id": "photo-1501443762994-82bd5dace89a",
        "category": "アイス・パフェ",
        "local": "/static/media/food/dessert.webp",
    },
    "pancakes": {
        "id": "photo-1528207776546-365bb710ee93",
        "category": "パンケーキ・スフレ",
        "local": "/static/media/food/pancake.webp",
    },
    "cake_dessert": {
        "id": "photo-1578985545062-69928b1d9587",
        "category": "ケーキ・デザート",
        "local": "/static/media/food/dessert.webp",
    },
    "donut": {
        "id": "photo-1551024709-8f23befc6f87",
        "category": "ドーナツ・パイ",
        "local": "/static/media/food/donut.webp",
    },
    "toast_breakfast": {
        "id": "photo-1525351484163-7529414344d8",
        "category": "トースト・朝食",
        "local": "/static/media/food/toast.webp",
    },
    # Drinks & Beverages
    "coffee": {
        "id": "photo-1509042239860-f550ce710b93",
        "category": "コーヒー",
        "local": "/static/media/food/coffee.webp",
    },
    "tea_matcha": {
        "id": "photo-1576092768241-dec231879fc3",
        "category": "お茶・抹茶",
        "local": "/static/media/food/default.webp",
    },
    "juice_beverage": {
        "id": "photo-1613478223719-2ab802602423",
        "category": "ジュース・ドリンク",
        "local": "/static/media/food/default.webp",
    },
    "beer_alcohol": {
        "id": "photo-1535958636474-b021ee887b13",
        "category": "ビール・酒類",
        "local": "/static/media/food/default.webp",
    },
    # Universal fallback culinary plate
    "culinary_default": {
        "id": "photo-1555396273-367ea4eb4db5",
        "category": "料理",
        "local": "/static/media/food/default.webp",
    },

}

# Ordered rules: more specific patterns come before broader patterns
CLASSIFICATION_RULES = [
    # Dish kinds added with the Wikimedia photograph set. Specific first:
    # the matcher takes the pattern ending last and breaks ties on this order,
    # so 定食 and セット sit at the bottom where a real dish name outranks them.
    (r"焼き鳥|やきとり|串焼き|つくね|ねぎま|手羽", "yakitori"),
    (r"枝豆|えだまめ", "edamame"),
    (r"冷奴|ひややっこ|湯豆腐", "hiyayakko"),
    (r"おでん|関東煮", "oden"),
    (r"刺身|お造り|舟盛り|盛り合わせ刺", "sashimi"),
    (r"天ぷら|天麩羅|かき揚げ", "tempura"),
    (r"だし巻き|出汁巻き|卵焼き|玉子焼き|厚焼き玉子", "tamagoyaki"),
    (r"コロッケ|クリームコロッケ", "korokke"),
    (r"たこ焼き|タコ焼き|たこやき", "takoyaki"),
    (r"お好み焼き|もんじゃ|チヂミ", "okonomiyaki"),
    (r"焼きそば|焼そば|ヤキソバ", "yakisoba"),
    (r"茶碗蒸し|ちゃわん蒸し", "chawanmushi"),
    (r"漬物|お新香|浅漬け|キムチ", "tsukemono"),
    (r"オムライス|オムハヤシ", "omurice"),
    (r"グラタン|ラザニア", "gratin"),
    (r"ドリア", "doria"),
    (r"リゾット", "risotto"),
    (r"サンドイッチ|サンドウィッチ|クラブハウス", "sandwich"),
    (r"ローストビーフ", "roast_beef"),
    (r"ステーキ|サーロイン|フィレ肉|リブロース", "steak_plate"),
    (r"ナポリタン", "napolitan"),
    (r"麻婆|マーボー|マーボ", "mapo_tofu"),
    (r"酢豚", "subuta"),
    (r"エビチリ|海老チリ|えびチリ", "ebi_chili"),
    (r"炒飯|チャーハン|焼き飯|ピラフ", "chahan"),
    (r"焼売|シュウマイ|シューマイ", "shumai"),
    (r"つけ麺|つけめん", "ramen_tsukemen"),
    (r"ビビンバ|ビビンパ|石焼ビビンバ", "bibimbap"),
    (r"サムギョプサル|サムギョプ", "samgyeopsal"),
    (r"フォー|フォ―", "pho"),
    (r"タコス|タコライス|ブリトー", "tacos"),
    (r"ケバブ|シュラスコ", "kebab"),
    (r"カレーライス|カレー丼|カツカレー|カレー", "curry_rice"),
    (r"ショートケーキ|イチゴケーキ", "shortcake"),
    (r"あんみつ|みつ豆|白玉", "anmitsu"),
    (r"どら焼き|たい焼き|大福|団子|まんじゅう", "dorayaki"),
    (r"ソフトクリーム", "soft_serve"),
    (r"スムージー|フラッペ|シェイク", "smoothie"),
    (r"カクテル|モヒート|カシス|ジントニック", "cocktail"),
    (r"日本酒|純米|大吟醸|冷酒|熱燗", "sake_drink"),
    (r"焼酎|芋焼酎|麦焼酎", "shochu"),
    (r"ワイン|グラスワイン|赤ワイン|白ワイン", "wine_drink"),

    # Specific burger variations
    (r"チーズバーガー|とびきりチーズ|チーズ.*バーガー|ダブル.*チーズ", "burger_cheese"),
    # Like the cheese rule above, these have to reach the end of the compound.
    # 「テリヤキチキンバーガー」 ends on バーガー, so a pattern stopping at チキン
    # loses to the generic burger rule under head-final matching.
    (r"(?:チキン|テリヤキチキン|チキンフィレ|タツタ).*バーガー"
     r"|チキンバーガー|テリヤキチキン|チキンフィレ|タツタ", "burger_chicken"),
    (r"(?:海老カツ|エビカツ|海老|エビ|フィッシュ|白身魚).*バーガー"
     r"|海老カツ|エビカツ|エビバーガー|フィッシュバーガー|白身魚", "burger_fish_shrimp"),
    (r"ホットドッグ|チリドッグ|ドッグ", "hotdog"),
    (r"バーガー|ワッパー|サンド|マフィン|バンズ", "burger_classic"),

    # Sushi & Seafood
    (r"サーモン|鮭|トラウト", "sushi_salmon"),
    (r"まぐろ|マグロ|鮪|中とろ|大とろ|赤身|ネギトロ|ねぎとろ", "sushi_tuna"),
    (r"えび|海老|エビ|甘えび", "sushi_shrimp"),
    (r"うなぎ|鰻|穴子|あなご", "sushi_eel"),
    (r"軍艦|巻き|手巻|納豆巻|鉄火巻|かっぱ巻", "sushi_roll"),
    (r"すし|寿司|スシ|にぎり|握り|ちらし|海鮮丼|刺身|貝|ほたて|ホタテ|赤貝|つぶ貝|いか|烏賊|たこ|タコ", "sushi_platter"),

    # Ramen & Noodles
    (r"味噌ラーメン|みそラーメン", "ramen_miso"),
    # The compound alternatives come first and reach to the end of the word, so
    # they tie with the generic ラーメン rule and win on order. Bare 豚骨 alone
    # would end four characters earlier and lose to it.
    (r"豚骨.*ラーメン|とんこつ.*ラーメン|博多ラーメン|家系|豚骨|とんこつ", "ramen_tonkotsu"),
    (r"ラーメン|らーめん|中華そば|つけ麺|油そば|担々麺", "ramen_shoyu"),
    (r"うどん|釜揚げ|きつねうどん|かき揚げうどん", "udon"),
    (r"そば|蕎麦|ざるそば|天ぷらそば", "soba"),
    (r"パスタ|スパゲッティ|カルボナーラ|ミートソース|ボロネーゼ|ペペロンチーノ|ナポリタン|たらこ|明太子", "pasta"),

    # Meats & Bowls
    (r"牛丼|牛皿|すき焼き丼|焼肉丼|豚丼|カルビ丼", "gyudon_beef"),
    (r"ステーキ|焼肉|カルビ|ハラミ|ロース|ハンバーグ", "yakiniku_steak"),
    (r"かつ|カツ|とんかつ|ロースカツ|ヒレカツ|カツ丼|生姜焼き|ポーク", "tonkatsu_pork"),
    (r"から揚げ|唐揚げ|チキン|ナゲット|ヤンニョム|手羽先|モスチキン", "karaage_chicken"),

    # Curry, Rice, Pizza, Gyoza
    (r"カレー|カツカレー", "curry"),
    (r"ピラフ", "chahan"),
    (r"ピザ|ピッツァ|マルゲリータ", "pizza"),
    (r"餃子|ギョーザ|点心|小籠包|春巻", "gyoza"),

    # Fries, Sides & Salads
    (r"オニオンフライ|オニオンリング", "onion_rings"),
    (r"ポテト|フレンチフライ|ハッシュポテト", "french_fries"),
    (r"サラダ|コールスロー|生野菜|アボカド|シーザー", "salad_green"),

    # Soups
    (r"コーンスープ|ポタージュ|チャウダー|クラムチャウダー", "soup_corn"),
    (r"味噌汁|みそ汁|とん汁|豚汁|スープ", "soup_miso"),

    # Sweets & Bakery
    (r"パンケーキ|スフレ|ワッフル|クレープ", "pancakes"),
    (r"ソフトクリーム|アイス|パフェ|サンデー|シャーベット", "icecream_parfait"),
    (r"ケーキ|ティラミス|チーズケーキ|タルト|プリン|シュークリーム", "cake_dessert"),
    (r"ドーナツ|パイ|チュロス", "donut"),
    (r"トースト|モーニング|朝モス|ブレッド|クロワッサン", "toast_breakfast"),

    # Beverages
    (r"コーヒー|珈琲|カフェラテ|エスプレッソ|カプチーノ|ラテ", "coffee"),
    (r"茶|ティー|紅茶|烏龍|緑茶|ほうじ茶|抹茶", "tea_matcha"),
    (r"ジュース|コーラ|ソーダ|フロート|シェイク|ジンジャーエール", "juice_beverage"),
    (r"ビール|ハイボール|サワー|酒|ワイン", "beer_alcohol"),

    # Formats, not dishes. Last, so 「牛丼」 keeps the beef-bowl
    # photograph and 「唐揚げ定食」 is not a generic tray.
    (r"天丼|海鮮丼|親子丼|中華丼|鉄火丼|うな丼|丼", "donburi_rice"),
    (r"弁当|べんとう|ベントー", "bento"),
    (r"定食|御膳|セット|ランチ", "teishoku"),
]


def _build_photo_url(photo_id: str, width: int = 160, height: int = 160, quality: int = 85) -> str:
    return f"{UNSPLASH_BASE}/{photo_id}?auto=format&fit=crop&w={width}&h={height}&q={quality}"


REPRESENTATIONAL = "※写真はイメージです（料理ジャンル・具材構成に基づく参考写真）"


@lru_cache(maxsize=1)
def _photos():
    """{concept: row} for dish kinds that have a real, freely-licensed photo.

    Fetched by tools/fetch_menu_photos.py from the lead image of the Japanese
    Wikipedia article about that kind of dish. Read once — it is ~80 rows and
    does not change between deploys.
    """
    from .queries import get_connection
    try:
        conn = get_connection()
    except Exception:
        return {}
    try:
        return {r["concept"]: dict(r) for r in conn.execute("SELECT * FROM dish_photos")}
    except sqlite3.Error:
        # An older extract has no such table. Bundled photographs, not a 500.
        return {}
    finally:
        conn.close()


# A dish name stops being the dish at the first of these. What follows is the
# sides, the sauce, or the description: 「フレンチフライ サワークリーム&スイートチリ
# ソース」 is fries, and 「本日のメイン、サイドサラダ、本日のスープ付き」 is not a soup.
_HEAD_ENDS = re.compile(r"[、。，,（(【\[「｜|/／〜~\s]")


def classify_key(name: str) -> str:
    """Which photo this dish name asks for.

    First-rule-wins read 「ポテトサラダ」 as chips, because ポテト is listed above
    サラダ and the list is ordered by cuisine rather than by specificity. Japanese
    compounds are head-final — the last element is the thing, everything before
    it modifies — so the rule whose keyword ENDS last is the one that names the
    dish. 8.2% of the menu corpus was affected.

    Ties go to the earlier rule, which is what keeps 「味噌ラーメン」 off the generic
    ramen photo and 「アボカドチーズバーガー」 on the cheeseburger: both patterns end
    at the same character, and the specific one is listed first.

    Only the head segment is read. Past a comma or a space the name is listing
    what comes alongside, and matching there picks the side dish over the dish.
    """
    head = _HEAD_ENDS.split(name or "", 1)[0]
    # Menus prefix names with markers — 「V ゴボウとキノコの豆乳腸活スープ」, 「新
    # からあげ」 — and truncating at the space leaves a head of one letter. When
    # the head names nothing, read the whole string rather than give up.
    return _best_match(head) or _best_match(name or "") or "culinary_default"


def _best_match(text):
    # finditer, not search: search returns the LEFTMOST match, and a rule is a
    # list of alternatives. In 「ふんわりスフレパンケーキ」 the pancake rule matched
    # スフレ at position 4 and never looked at パンケーキ at 7, so it ended before
    # the dessert rule's ケーキ and lost a dish it had named correctly.
    best = None  # ((end position, -rule index), key)
    for index, (pattern, key) in enumerate(CLASSIFICATION_RULES):
        ends = [m.end() for m in re.finditer(pattern, text, re.IGNORECASE)]
        if not ends:
            continue
        rank = (max(ends), -index)
        if best is None or rank > best[0]:
            best = (rank, key)
    return best[1] if best else None


def get_dish_image(dish_name: str, category_hint: Optional[str] = None) -> Dict[str, Any]:
    """Resolve an authentic food photo for any dish name.

    Returns:
        dict with keys:
            'url': High resolution WebP/JPEG image URL
            'thumb_url': Optimized square thumbnail URL
            'local_fallback': Local bundled asset path
            'category': Categorical label
            'alt': Accessible image alt text
    """
    name = (dish_name or "").strip()
    matched_key = classify_key(name)

    item_data = DISH_PHOTO_CATALOG.get(matched_key)
    # A freely-licensed photograph of that kind of dish, fetched from the
    # Japanese Wikipedia article about it, beats a stock image of roughly the
    # right colour. Only 21 bundled files existed for 39 keys, so a chain menu
    # showed the same picture forty times.
    photo = _photos().get(matched_key)
    if photo:
        return {
            "url": photo["file"],
            "card_url": photo["file"],
            "thumb_url": photo["file"],
            "local_fallback": (item_data or {}).get(
                "local", "/static/media/food/default.webp"),
            "category": (item_data or {}).get("category", photo["article"]),
            "alt": f"{name}の参考料理写真（イメージ）",
            "representational_note": REPRESENTATIONAL,
            "credit": photo.get("credit"),
            "licence": photo.get("licence"),
            "page_url": photo.get("page_url"),
        }

    item_data = item_data or DISH_PHOTO_CATALOG["culinary_default"]
    local = item_data["local"]
    # The catalogue's Unsplash ids are deliberately not built into URLs here:
    # a chain menu renders 200-340 rows and would fetch that many third-party
    # images per page load. The bundled file is served instead.
    return {
        "url": local,
        "card_url": local,
        "thumb_url": local,
        "local_fallback": local,
        "category": item_data["category"],
        "alt": f"{name}の参考料理写真（イメージ）",
        "representational_note": REPRESENTATIONAL,
    }
