"""Authentic food photography mapping for restaurant menu items.

Assigns appetizing, high-resolution food images to every dish across
chains and culinary categories.
"""
import re
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
    # Specific burger variations
    (r"チーズバーガー|とびきりチーズ|チーズ.*バーガー|ダブル.*チーズ", "burger_cheese"),
    (r"チキンバーガー|テリヤキチキン|チキンフィレ|タツタ", "burger_chicken"),
    (r"海老カツ|エビカツ|エビバーガー|フィッシュバーガー|白身魚", "burger_fish_shrimp"),
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
    (r"豚骨|とんこつ|博多ラーメン|家系", "ramen_tonkotsu"),
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
    (r"炒飯|チャーハン|ピラフ|オムライス|天丼|海鮮丼|親子丼", "gyudon_beef"),
    (r"ピザ|ピッツァ|マルゲリータ", "pizza"),
    (r"餃子|ギョーザ|点心|焼売|春巻|小籠包", "gyoza"),

    # Fries, Sides & Salads
    (r"オニオンフライ|オニオンリング", "onion_rings"),
    (r"ポテト|フレンチフライ|ハッシュポテト|コロッケ", "french_fries"),
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
]


def _build_photo_url(photo_id: str, width: int = 160, height: int = 160, quality: int = 85) -> str:
    return f"{UNSPLASH_BASE}/{photo_id}?auto=format&fit=crop&w={width}&h={height}&q={quality}"


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

    # Rule-based pattern matching
    matched_key = None
    for pattern, key in CLASSIFICATION_RULES:
        if re.search(pattern, name, re.IGNORECASE):
            matched_key = key
            break

    if not matched_key:
        matched_key = "culinary_default"

    item_data = DISH_PHOTO_CATALOG.get(matched_key, DISH_PHOTO_CATALOG["culinary_default"])
    photo_id = item_data["id"]

    return {
        "url": _build_photo_url(photo_id, width=720, height=720, quality=88),
        "card_url": _build_photo_url(photo_id, width=480, height=360, quality=85),
        "thumb_url": _build_photo_url(photo_id, width=240, height=240, quality=85),
        "local_fallback": item_data["local"],
        "category": item_data["category"],
        "alt": f"{name}の参考料理写真（イメージ）",
        "representational_note": "※写真はイメージです（料理ジャンル・具材構成に基づく参考写真）",
    }
