"""Brand assets: authentic restaurant chain logo badges and culinary dish thumbnails."""
import re
import hashlib

CHAIN_BRANDS = [
    ("スシロー", {"bg": "#E60012", "fg": "#FFFFFF", "mark": "ス", "sub": "SUSHIRO"}),
    ("はま寿司", {"bg": "#002B49", "fg": "#FFFFFF", "mark": "はま", "sub": "HAMA"}),
    ("くら寿司", {"bg": "#1C1C1C", "fg": "#FFFFFF", "mark": "くら", "sub": "KURA"}),
    ("かっぱ寿司", {"bg": "#ED1C24", "fg": "#FFFFFF", "mark": "かっぱ", "sub": "KAPPA"}),
    ("元気寿司", {"bg": "#E60012", "fg": "#FFD700", "mark": "元気", "sub": "GENKI"}),
    ("銚子丸", {"bg": "#003366", "fg": "#FFFFFF", "mark": "銚子丸", "sub": "CHOSHI"}),
    ("吉野家", {"bg": "#EB6100", "fg": "#FFFFFF", "mark": "吉", "sub": "YOSHINOYA"}),
    ("すき家", {"bg": "#D62828", "fg": "#FFD166", "mark": "すき", "sub": "SUKIYA"}),
    ("松屋", {"bg": "#005BAC", "fg": "#FFDE00", "mark": "松", "sub": "MATSUYA"}),
    ("松のや", {"bg": "#005BAC", "fg": "#FFFFFF", "mark": "松のや", "sub": "MATSUNOYA"}),
    ("なか卯", {"bg": "#C8102E", "fg": "#FFFFFF", "mark": "なか卯", "sub": "NAKAU"}),
    ("マクドナルド", {"bg": "#DA291C", "fg": "#FFC72C", "mark": "M", "sub": "McD"}),
    ("モスバーガー", {"bg": "#008037", "fg": "#FFFFFF", "mark": "MOS", "sub": "BURGER"}),
    ("MOS BURGER", {"bg": "#008037", "fg": "#FFFFFF", "mark": "MOS", "sub": "BURGER"}),
    ("バーガーキング", {"bg": "#502314", "fg": "#F5EBDC", "mark": "BK", "sub": "BURGER"}),
    ("ケンタッキー", {"bg": "#A3080C", "fg": "#FFFFFF", "mark": "KFC", "sub": "CHICKEN"}),
    ("KFC", {"bg": "#A3080C", "fg": "#FFFFFF", "mark": "KFC", "sub": "CHICKEN"}),
    ("ガスト", {"bg": "#E60012", "fg": "#FFFFFF", "mark": "ガスト", "sub": "GUSTO"}),
    ("サイゼリヤ", {"bg": "#008837", "fg": "#FFFFFF", "mark": "サイ", "sub": "SAIZE"}),
    ("ジョナサン", {"bg": "#0072CE", "fg": "#FFFFFF", "mark": "ジョナ", "sub": "JONATHAN"}),
    ("バーミヤン", {"bg": "#D91B24", "fg": "#FFFFFF", "mark": "バーミ", "sub": "BAMIYAN"}),
    ("デニーズ", {"bg": "#FED100", "fg": "#C8102E", "mark": "Denny's", "sub": "DENNYS"}),
    ("ココス", {"bg": "#F58220", "fg": "#FFFFFF", "mark": "COCO'S", "sub": "COCOS"}),
    ("ロイヤルホスト", {"bg": "#E45F1B", "fg": "#FFFFFF", "mark": "ロイホ", "sub": "ROYAL"}),
    ("びっくりドンキー", {"bg": "#5C3A21", "fg": "#FFD700", "mark": "ドンキー", "sub": "DONKEY"}),
    ("幸楽苑", {"bg": "#E50012", "fg": "#FFFFFF", "mark": "幸", "sub": "KOURAKU"}),
    ("日高屋", {"bg": "#E60012", "fg": "#FFFFFF", "mark": "日高屋", "sub": "HIDAKAYA"}),
    ("丸亀製麺", {"bg": "#1D2A44", "fg": "#E5A93C", "mark": "丸亀", "sub": "MARUGAME"}),
    ("はなまるうどん", {"bg": "#F58220", "fg": "#FFFFFF", "mark": "はなまる", "sub": "HANAMARU"}),
    ("スターバックス", {"bg": "#00704A", "fg": "#FFFFFF", "mark": "★", "sub": "STARBUCKS"}),
    ("コメダ珈琲店", {"bg": "#6F361A", "fg": "#FFFFFF", "mark": "コメダ", "sub": "KOMEDA"}),
    ("ドトール", {"bg": "#1A1A1A", "fg": "#FFCC00", "mark": "DOUTOR", "sub": "DOUTOR"}),
    ("大戸屋", {"bg": "#002D62", "fg": "#FFFFFF", "mark": "大戸屋", "sub": "OOTOYA"}),
    ("やよい軒", {"bg": "#B7282E", "fg": "#FFFFFF", "mark": "やよい", "sub": "YAYOI"}),
    ("かつや", {"bg": "#C51118", "fg": "#FFFFFF", "mark": "かつや", "sub": "KATSUYA"}),
    ("餃子の王将", {"bg": "#D91B24", "fg": "#FFFFFF", "mark": "王将", "sub": "OHSHO"}),
    ("大阪王将", {"bg": "#E60012", "fg": "#FFD700", "mark": "王将", "sub": "OSAKA"}),
    ("CoCo壱番屋", {"bg": "#F39000", "fg": "#FFFFFF", "mark": "ココイチ", "sub": "COCOICHI"}),
    ("一蘭", {"bg": "#005A36", "fg": "#E50012", "mark": "一蘭", "sub": "ICHIRAN"}),
    ("一風堂", {"bg": "#1C1C1C", "fg": "#FFFFFF", "mark": "一風堂", "sub": "IPPUDO"}),
    ("リンガーハット", {"bg": "#E60012", "fg": "#FED100", "mark": "リンガー", "sub": "RINGER"}),
    ("鳥貴族", {"bg": "#FED100", "fg": "#000000", "mark": "鳥貴", "sub": "TORIKI"}),
    ("ミスタードーナツ", {"bg": "#E60012", "fg": "#FED100", "mark": "ミスド", "sub": "MISDO"}),
    ("サンマルクカフェ", {"bg": "#5C3A21", "fg": "#FFFFFF", "mark": "サンマルク", "sub": "SAINTMARC"}),
    ("富士そば", {"bg": "#003366", "fg": "#FFFFFF", "mark": "富士そば", "sub": "FUJISOBA"}),
    ("ゆで太郎", {"bg": "#008837", "fg": "#FFFFFF", "mark": "ゆで太郎", "sub": "YUDETARO"}),
    ("焼肉きんぐ", {"bg": "#1C1C1C", "fg": "#E60012", "mark": "きんぐ", "sub": "KING"}),
    ("牛角", {"bg": "#1C1C1C", "fg": "#FFFFFF", "mark": "牛角", "sub": "GYUKAKU"}),
    ("ピザーラ", {"bg": "#E60012", "fg": "#FFFFFF", "mark": "PIZZA", "sub": "PIZZA-LA"}),
    ("ドミノ・ピザ", {"bg": "#006491", "fg": "#FFFFFF", "mark": "DOMINO", "sub": "DOMINOS"}),
]

DETERMINISTIC_PALETTES = [
    ("#D63031", "#FFFFFF"),
    ("#0984E3", "#FFFFFF"),
    ("#00B894", "#FFFFFF"),
    ("#E17055", "#FFFFFF"),
    ("#6C5CE7", "#FFFFFF"),
    ("#FD79A8", "#FFFFFF"),
    ("#2D3436", "#FFFFFF"),
    ("#E84393", "#FFFFFF"),
]


def get_chain_brand_badge(name: str) -> dict:
    """Return authentic brand styling (background color, text color, mark, subtitle)."""
    clean_name = (name or "").strip()
    for prefix, data in CHAIN_BRANDS:
        if prefix in clean_name:
            return data

    # Deterministic fallback
    h = int(hashlib.md5(clean_name.encode("utf-8")).hexdigest(), 16)
    bg, fg = DETERMINISTIC_PALETTES[h % len(DETERMINISTIC_PALETTES)]
    mark = clean_name[:2] if len(clean_name) >= 2 else clean_name
    return {"bg": bg, "fg": fg, "mark": mark, "sub": "SHOP"}


DISH_CATEGORIES = [
    (r"サーモン", "🍣", "linear-gradient(135deg, #FF793F, #EE5253)", "サーモン"),
    (r"まぐろ|マグロ|鮪|中とろ|大とろ|赤身", "🍣", "linear-gradient(135deg, #D63031, #B71540)", "まぐろ"),
    (r"えび|海老|エビ", "🦐", "linear-gradient(135deg, #FF9FF3, #F368E0)", "えび"),
    (r"うなぎ|鰻|穴子|あなご", "🍱", "linear-gradient(135deg, #6D214F, #3B3B98)", "うなぎ・穴子"),
    (r"いか|烏賊|たこ|蛸|タコ", "🦑", "linear-gradient(135deg, #48DBFB, #0ABDE3)", "いか・たこ"),
    (r"貝|ほたて|ホタテ|赤貝|つぶ貝", "🦪", "linear-gradient(135deg, #A4B0BE, #57606F)", "貝類"),
    (r"軍艦|巻き|巻|すし|寿司|スシ", "🍣", "linear-gradient(135deg, #EA2027, #EE5A24)", "寿司"),
    (r"ラーメン|らーめん|中華そば|つけ麺|麺", "🍜", "linear-gradient(135deg, #F39C12, #D35400)", "ラーメン"),
    (r"うどん|そば|蕎麦", "🥢", "linear-gradient(135deg, #E67E22, #A04000)", "うどん・そば"),
    (r"牛丼|牛皿|カルビ|ステーキ|焼肉|ロース|ハラミ|肉", "🥩", "linear-gradient(135deg, #C0392B, #78281F)", "牛丼・肉"),
    (r"チキン|から揚げ|唐揚げ|とり|鶏|ナゲット|ヤンニョム", "🍗", "linear-gradient(135deg, #F1C40F, #D68910)", "チキン"),
    (r"かつ|カツ|とんかつ|豚|ポーク", "🍱", "linear-gradient(135deg, #D35400, #A04000)", "かつ・豚肉"),
    (r"カレー", "🍛", "linear-gradient(135deg, #DC7633, #BA4A00)", "カレー"),
    (r"餃子|ギョーザ|点心|焼売|春巻", "🥟", "linear-gradient(135deg, #F5B041, #EB984E)", "餃子・点心"),
    (r"バーガー|サンド", "🍔", "linear-gradient(135deg, #D35400, #C0392B)", "バーガー"),
    (r"ピザ|ピッツァ", "🍕", "linear-gradient(135deg, #E74C3C, #C0392B)", "ピザ"),
    (r"サラダ|野菜|アボカド|オニオン|コールスロー", "🥗", "linear-gradient(135deg, #2ECC71, #27AE60)", "サラダ"),
    (r"味噌汁|みそ汁|スープ|とん汁|豚汁", "🥣", "linear-gradient(135deg, #58B19F, #2C3A47)", "汁物・スープ"),
    (r"ポテト|フライ|コロッケ|天ぷら|天麩羅", "🍟", "linear-gradient(135deg, #F7B731, #FA8231)", "揚げ物・サイド"),
    (r"たまご|玉子|卵|茶碗蒸し|オムレツ", "🥚", "linear-gradient(135deg, #F9E79F, #F39C12)", "卵料理"),
    (r"パフェ|アイス|ケーキ|デザート|プリン|甘味|ゼリー|クレープ", "🍨", "linear-gradient(135deg, #FD79A8, #E84393)", "デザート"),
    (r"ビール|酒|ハイボール|酎ハイ|サワー|ワイン", "🍺", "linear-gradient(135deg, #FED330, #F7B731)", "アルコール"),
    (r"コーヒー|珈琲|カフェラテ|エスプレッソ", "☕", "linear-gradient(135deg, #6F1E51, #3D144C)", "コーヒー"),
    (r"茶|ティー|マックシェイク|フロート|ジュース|コーラ|ソーダ|ドリンク", "🥤", "linear-gradient(135deg, #0ABDE3, #10AC84)", "ドリンク"),
    (r"ご飯|ライス|丼|定食|チャーハン|炒飯|おにぎり", "🍚", "linear-gradient(135deg, #A4B0BE, #747D8C)", "ご飯・セット"),
]


def classify_dish_visual(dish_name: str) -> dict:
    """Return culinary icon, gradient, and category label for a dish name."""
    name = dish_name or ""
    for pattern, icon, gradient, category in DISH_CATEGORIES:
        if re.search(pattern, name, re.IGNORECASE):
            return {"icon": icon, "gradient": gradient, "category": category}
    return {
        "icon": "🍽️",
        "gradient": "linear-gradient(135deg, #E67E22, #D35400)",
        "category": "料理",
    }
