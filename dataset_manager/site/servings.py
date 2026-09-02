"""What one serving of a food actually is.

Every figure on the site is per 100 g, because that is how the composition
tables publish them. It is the wrong unit for a reader: nobody eats 100 g of
rice, and 「白米のカロリー」 is being asked about 茶碗一杯. Answering 156 kcal
is true and unhelpful; answering 「茶碗1杯（150g）で234kcal」 is the question
they asked.

A serving is a convention, not a measurement, so it is treated like the count
weights in calc/quantities.py: curated per food, labelled with what it is, and
absent rather than guessed. A food with no entry here keeps showing per 100 g
only — better than inventing a portion for 「うし 副生物 第一胃 ゆで」.

Weights are the ordinary Japanese kitchen references (目安量): a 茶碗 of rice
is 150 g, a 6枚切り slice of bread 60 g, an egg 50 g.
"""

# name fragment -> (label, grams). Longest fragment wins, so 「水稲めし」 is
# matched before 「こめ」.
SERVINGS = {
    # --- grains and staples
    "水稲めし 精白米": ("茶碗1杯", 150.0),
    "水稲めし 玄米": ("茶碗1杯", 150.0),
    "水稲めし": ("茶碗1杯", 150.0),
    "水稲全かゆ": ("1杯", 220.0),
    "角形食パン": ("6枚切り1枚", 60.0),
    "コッペパン": ("1個", 70.0),
    "ロールパン": ("1個", 30.0),
    "クロワッサン": ("1個", 40.0),
    "うどん ゆで": ("1玉", 230.0),
    "そば ゆで": ("1人前", 180.0),
    "そうめん・ひやむぎ ゆで": ("1人前", 180.0),
    "中華めん ゆで": ("1玉", 230.0),
    "マカロニ・スパゲッティ ゆで": ("1人前", 220.0),
    "もち": ("角もち1個", 50.0),
    "コーンフレーク": ("1食分", 40.0),

    # --- soy, eggs, dairy
    "鶏卵 全卵 生": ("Mサイズ1個", 50.0),
    "うずら卵": ("1個", 10.0),
    "木綿豆腐": ("1/2丁", 150.0),
    "絹ごし豆腐": ("1/2丁", 150.0),
    "糸引き納豆": ("1パック", 45.0),
    "油揚げ": ("1枚", 30.0),
    "生揚げ": ("1枚", 120.0),
    "普通牛乳": ("コップ1杯", 200.0),
    "加工乳": ("コップ1杯", 200.0),
    "ヨーグルト": ("1カップ", 100.0),
    "プロセスチーズ": ("1切れ", 18.0),
    "豆乳": ("コップ1杯", 200.0),

    # --- meat and fish, as sold in a portion
    "にわとり 若どり むね": ("1枚の1/2", 120.0),
    "にわとり 若どり もも": ("1枚の1/2", 120.0),
    "にわとり 若どり ささみ": ("1本", 40.0),
    "ぶた 大型種肉 ロース": ("1枚", 100.0),
    "ぶた 大型種肉 ばら": ("3枚", 60.0),
    "うし 乳用肥育牛肉": ("1人前", 100.0),
    "ロースハム": ("1枚", 20.0),
    "ばらベーコン": ("1枚", 17.0),
    "ウインナーソーセージ": ("1本", 20.0),
    "しろさけ": ("1切れ", 80.0),
    "まさば": ("1切れ", 80.0),
    "ぶり": ("1切れ", 80.0),
    "まあじ 皮つき 生": ("中1尾", 100.0),
    "まいわし": ("1尾", 60.0),
    "さんま": ("1尾", 100.0),
    "しらす干し": ("大さじ2", 10.0),
    "かつお節": ("1パック", 2.5),
    "蒸しかまぼこ": ("2切れ", 20.0),
    "焼き竹輪": ("1本", 30.0),

    # --- vegetables and fruit, per piece as eaten
    "にんじん 根 皮なし": ("1/2本", 75.0),
    "たまねぎ りん茎": ("1/2個", 100.0),
    "じゃがいも 塊茎 皮なし": ("1個", 135.0),
    "キャベツ 結球葉": ("葉2枚", 100.0),
    "はくさい 結球葉": ("葉1枚", 100.0),
    "ほうれんそう 葉": ("1/2束", 100.0),
    "こまつな 葉": ("1/2束", 100.0),
    "ブロッコリー 花序": ("小房5個", 80.0),
    "きゅうり 果実": ("1本", 100.0),
    "赤色トマト 果実": ("1個", 150.0),
    "赤色ミニトマト": ("3個", 45.0),
    "なす 果実": ("1個", 80.0),
    "だいこん 根 皮なし": ("輪切り3cm", 100.0),
    "根深ねぎ 葉 軟白": ("1/2本", 50.0),
    "バナナ": ("1本", 100.0),
    "りんご 皮なし": ("1/2個", 125.0),
    "うんしゅうみかん": ("1個", 80.0),
    "いちご": ("5粒", 75.0),
    "アボカド": ("1/2個", 70.0),
    "生しいたけ 菌床栽培": ("2個", 30.0),

    # --- seasonings, at the amount a dish uses
    "こいくちしょうゆ": ("大さじ1", 18.0),
    "うすくちしょうゆ": ("大さじ1", 18.0),
    "米みそ": ("大さじ1", 18.0),
    "調合油": ("大さじ1", 12.0),
    "ごま油": ("大さじ1", 12.0),
    "オリーブ油": ("大さじ1", 12.0),
    "有塩バター": ("1かけ", 10.0),
    "マヨネーズ": ("大さじ1", 12.0),
    "トマトケチャップ": ("大さじ1", 15.0),
    "車糖 上白糖": ("大さじ1", 9.0),
    "食塩": ("小さじ1", 6.0),

    # --- seaweed, nuts, drinks
    "あまのり 焼きのり": ("全形1枚", 3.0),
    "まこんぶ 素干し": ("10cm角1枚", 10.0),
    "ほしひじき": ("乾10g", 10.0),
    "わかめ 原藻": ("1食分", 20.0),
    "ごま いり": ("大さじ1", 9.0),
    "アーモンド": ("10粒", 15.0),
    "らっかせい": ("10粒", 10.0),
    "せん茶 浸出液": ("湯のみ1杯", 100.0),
    "コーヒー 浸出液": ("カップ1杯", 150.0),
    "ビール 淡色": ("中瓶1本", 500.0),
}

_KEYS = sorted(SERVINGS, key=len, reverse=True)

# A form the serving was not decided for. 「いちご」 is five berries; 「いちご
# ジャム」 is not, and 「いちご 乾」 is not either. Matched as whole tokens, so
# 「脂身」 blocks the pure fat trim while 「脂身つき」 — an ordinary cut — passes.
EXCLUDE_TOKENS = frozenset({
    "ジャム", "乾", "缶詰", "粉", "ペースト", "ピューレー", "ピューレ", "濃縮",
    "シロップ漬", "砂糖漬", "塩漬", "漬物", "酢漬", "甘酢漬", "つくだ煮", "塩辛",
    "脂身", "冷凍", "フリーズドライ", "粉末", "チップス", "菓子", "アイスクリーム",
})


def for_food(name):
    """{'label', 'grams'} for a food, or None when we have not decided.

    Matched on the display name, longest key first. A key with a space is a
    path through the taxonomy and matches anywhere in the name; a single-word
    key has to match a whole token, or 「もち」 would claim 「うぐいすもち」 and
    「あわ あわもち」, which are confections and not a 50 g piece of mochi.
    """
    if not name:
        return None
    tokens = set(name.split())
    if tokens & EXCLUDE_TOKENS:
        return None
    for key in _KEYS:
        hit = key in name if " " in key else key in tokens
        if hit:
            label, grams = SERVINGS[key]
            return {"label": label, "grams": grams}
    return None


def scale(nutrition, grams):
    """Per-100g values at the serving weight. Same arithmetic as everywhere
    else on the site: value x grams / 100, nothing rounded away."""
    if not nutrition or not grams:
        return None
    return {k: (v * grams / 100 if isinstance(v, (int, float)) else v)
            for k, v in nutrition.items()}
