import re
from typing import Dict, Any, List

def calculate_jdi8(
    name: str,
    main_ingredients: str = "",
    recipe_ingredients: str = "",
    recipe_steps: str = "",
    category: str = ""
) -> Dict[str, Any]:
    """
    Calculate the Japanese Diet Index (JDI8) score for a given item based on 8 components.
    Returns a dictionary with the score, individual boolean flags, and matched evidence/details.
    """
    # Combine texts for keyword searching, normalizing case
    search_text = " ".join([
        name or "",
        main_ingredients or "",
        recipe_ingredients or "",
        recipe_steps or "",
        category or ""
    ]).lower()

    # Define keyword dictionaries for matching
    # Using regex word borders or sub-string matching where appropriate for Japanese
    
    # 1. Rice (主食 - 米・ご飯)
    rice_keywords = ["米", "ごはん", "ご飯", "おにぎり", "ライス", "玄米", "麦飯", "もち米"]
    # 2. Miso Soup (味噌汁・味噌)
    miso_keywords = ["味噌", "みそ", "味噌汁", "みそ汁"]
    # 3. Seaweed (海藻類 - 昆布・わかめ・海苔)
    seaweed_keywords = ["昆布", "わかめ", "ワカメ", "こんぶ", "海苔", "のり", "ひじき", "もずく", "寒天", "てんぐさ", "テングサ", "海藻", "とさかのり", "めかぶ", "アオサ", "あおさ"]
    # 4. Pickles (漬物類)
    pickles_keywords = ["漬物", "漬け物", "つくだ煮", "佃煮", "梅干", "ぬか漬", "粕漬", "甘酢漬", "浅漬", "味噌漬", "しょうゆ漬", "塩漬", "柴漬", "しば漬", "たくあん", "沢庵", "福神漬"]
    # 5. Green & Yellow Vegetables (緑黄色野菜)
    green_yellow_keywords = [
        "人参", "にんじん", "ほうれん草", "ホウレンソウ", "小松菜", "コマツナ", "かぼちゃ", "カボチャ", "南瓜",
        "トマト", "とまと", "ピーマン", "ぴーまん", "ブロッコリー", "オクラ", "おくら", "ニラ", "にら", 
        "ねぎ", "ネギ", "葱", "春菊", "アスパラガス", "サヤインゲン", "いんげん", "インゲン", "豆苗", 
        "ケール", "モロヘイヤ", "チンゲンサイ", "青梗菜", "サラダ菜", "大根の葉", "かぶの葉", "パプリカ"
    ]
    # 6. Fish & Seafood (魚介類)
    fish_keywords = [
        "魚", "さかな", "鮭", "サケ", "さけ", "タイ", "たい", "鯛", "アジ", "あじ", "鯵", "鰯", "いわし", "イワシ",
        "マグロ", "まぐろ", "鮪", "鯖", "サバ", "さば", "鰹", "かつお", "カツオ", "サンマ", "さんま", "秋刀魚",
        "ぶり", "ブリ", "いか", "イカ", "たこ", "タコ", "えび", "エビ", "海老", "かに", "カニ", "蟹", "貝", 
        "アサリ", "あさり", "しじみ", "シジミ", "かき", "カキ", "牡蠣", "たらこ", "明太子", "タラ", "たら", 
        "ちりめん", "じゃこ", "しらす", "ツナ", "シーフード", "焼き干し", "カツオ節", "かつお節", "出汁昆布", 
        "ほたて", "ホタテ", "帆立", "サワラ", "鰆", "サヨリ", "キス", "アナゴ", "うなぎ", "ウナギ", "鰻"
    ]
    # 7. Green Tea (緑茶・日本茶)
    tea_keywords = ["緑茶", "煎茶", "抹茶", "ほうじ茶", "番茶", "玉露", "日本茶", "お茶"]
    # 8. Beef & Pork (牛肉・豚肉 - Low intake component)
    meat_keywords = [
        "牛肉", "ぎゅうにく", "豚肉", "ぶたにく", "豚バラ", "豚ロース", "牛バラ", "牛肩",
        "ベーコン", "ハム", "ソーセージ", "ポーク", "ビーフ", "チャーシュー", "焼豚", 
        "合挽", "挽き肉", "挽肉", "とんかつ", "トンカツ", "豚カツ"
    ]

    def check_presence(keywords: List[str]) -> List[str]:
        matched = []
        for kw in keywords:
            if kw in search_text:
                matched.append(kw)
        return matched

    matched_rice = check_presence(rice_keywords)
    matched_miso = check_presence(miso_keywords)
    matched_seaweed = check_presence(seaweed_keywords)
    matched_pickles = check_presence(pickles_keywords)
    matched_veg = check_presence(green_yellow_keywords)
    matched_fish = check_presence(fish_keywords)
    matched_tea = check_presence(tea_keywords)
    matched_meat = check_presence(meat_keywords)

    rice = len(matched_rice) > 0
    miso = len(matched_miso) > 0
    seaweed = len(matched_seaweed) > 0
    pickles = len(matched_pickles) > 0
    green_yellow_veg = len(matched_veg) > 0
    fish = len(matched_fish) > 0
    green_tea = len(matched_tea) > 0
    low_meat = len(matched_meat) == 0  # True if NOT present

    # Calculate JDI8 Score (out of 8)
    score = sum([
        int(rice),
        int(miso),
        int(seaweed),
        int(pickles),
        int(green_yellow_veg),
        int(fish),
        int(green_tea),
        int(low_meat)
    ])

    evidence = {
        "rice": matched_rice,
        "miso": matched_miso,
        "seaweed": matched_seaweed,
        "pickles": matched_pickles,
        "green_yellow_veg": matched_veg,
        "fish": matched_fish,
        "green_tea": matched_tea,
        "meat_present": matched_meat
    }

    return {
        "score": score,
        "rice": rice,
        "miso": miso,
        "seaweed": seaweed,
        "pickles": pickles,
        "green_yellow_veg": green_yellow_veg,
        "fish": fish,
        "green_tea": green_tea,
        "low_meat": low_meat,
        "evidence": evidence
    }
