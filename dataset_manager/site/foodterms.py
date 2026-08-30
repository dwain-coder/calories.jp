"""Everyday Japanese food words -> the vocabulary of the composition tables.

Two callers need the same translation and were each doing it badly:

* the meal analyzer, where a vision model says 「牛肉（加熱）」 and the search
  found nothing, so the beef in the photo was dropped from the totals;
* the recipe linker, where a MAFF recipe line says 「醤油 大さじ2」 and the
  tables only ever write こいくちしょうゆ.

The tables are written in a register nobody cooks in: 醤油 never appears (it is
こいくちしょうゆ), nor 鶏肉 (にわとり), nor 牛ひき肉 (うし ひき肉), nor サラダ油
(調合油). Matching without this layer fails on the most common words in Japanese
cooking, which is exactly the failure the site cannot afford.

Nothing here invents nutrition. It only decides which search terms to try, and
the answer still has to exist in the corpus.
"""
import re
import unicodedata

# Ingredients with no nutrition to contribute. Counting them as unmatched made
# recipe coverage look worse than it is — 320 recipe lines are just water.
IGNORE = frozenset({
    "水", "湯", "お湯", "熱湯", "ぬるま湯", "氷", "冷水", "水適量",
    # Soaking and cooking liquids. The tables have no row for them, and using
    # the food's own row would charge a dish for an ingredient nobody ate.
    "戻し汁", "しいたけの戻し汁", "ゆで汁", "煮汁", "打ち粉",
})

# Qualifiers a cook or a vision model adds and the tables do not carry as part
# of the name. Stripped only when the whole name would otherwise fail.
NOISE = (
    "加熱", "加熱済み", "調理済み", "市販品", "市販", "お好みで", "適量", "少々",
    "冷凍", "解凍", "細切り", "千切り", "みじん切り", "薄切り", "角切り", "乱切り",
    "すりおろし", "おろし", "刻み", "きざみ", "小口切り", "食べやすい大きさ",
)

# Everyday word -> what to search the tables for, best first.
#
# Where a word is ambiguous the choice is the one an ordinary Japanese kitchen
# means by it, not the first row in the table:
#   牛肉  -> 乳用肥育牛肉, the usual supermarket beef, not 和牛 (much fattier)
#   豚肉  -> 大型種肉, likewise
#   鶏肉  -> 若どり, the broiler sold everywhere, not 親 (spent hen)
#   醤油  -> こいくちしょうゆ, about 8 in 10 bottles sold in Japan
#   砂糖  -> 車糖 上白糖, the household sugar
#   みそ  -> 米みそ 淡色辛みそ, the national default
#
# The raw/cooked split is load-bearing: 米 is uncooked grain at ~342 kcal/100g
# and ご飯 is cooked at ~156. Treating them as one word would put a rice dish
# out by more than double.
ALIASES = {
    # --- seasonings and liquids
    "醤油": ["こいくちしょうゆ"], "しょうゆ": ["こいくちしょうゆ"],
    "濃口醤油": ["こいくちしょうゆ"], "薄口醤油": ["うすくちしょうゆ"],
    "うすくちしょうゆ": ["うすくちしょうゆ"], "白醤油": ["しろしょうゆ"],
    "砂糖": ["車糖 上白糖"], "上白糖": ["車糖 上白糖"],
    "きび砂糖": ["ざらめ糖 中ざら糖"], "黒砂糖": ["黒砂糖"], "三温糖": ["車糖 三温糖"],
    "塩": ["食塩"], "食塩": ["食塩"], "粗塩": ["並塩"], "自然塩": ["並塩"],
    "みそ": ["米みそ 淡色辛みそ"], "味噌": ["米みそ 淡色辛みそ"],
    "白みそ": ["米みそ 甘みそ"], "白味噌": ["米みそ 甘みそ"],
    "赤みそ": ["米みそ 赤色辛みそ"], "赤味噌": ["米みそ 赤色辛みそ"],
    "合わせみそ": ["米みそ 淡色辛みそ"], "麦みそ": ["麦みそ"],
    "酒": ["清酒 普通酒"], "日本酒": ["清酒 普通酒"], "料理酒": ["清酒 普通酒"],
    "みりん": ["みりん 本みりん"], "本みりん": ["みりん 本みりん"],
    "酢": ["穀物酢"], "米酢": ["米酢"], "食酢": ["穀物酢"],
    "だし汁": ["かつお・昆布だし 荒節・昆布だし"], "だし": ["かつお・昆布だし 荒節・昆布だし"],
    "出汁": ["かつお・昆布だし 荒節・昆布だし"], "かつおだし": ["かつおだし 荒節"],
    "昆布だし": ["昆布だし 水出し"], "煮干しだし": ["煮干しだし"],
    "サラダ油": ["調合油"], "油": ["調合油"], "植物油": ["調合油"], "揚げ油": ["調合油"],
    "ごま油": ["ごま油"], "オリーブオイル": ["オリーブ油"], "オリーブ油": ["オリーブ油"],
    "バター": ["有塩バター"], "マーガリン": ["マーガリン 家庭用 有塩"],
    "マヨネーズ": ["マヨネーズ 全卵型"], "ケチャップ": ["トマトケチャップ"],
    "ソース": ["ウスターソース"], "めんつゆ": ["めんつゆ ストレート"],
    "片栗粉": ["じゃがいもでん粉"], "小麦粉": ["薄力粉 1等"], "薄力粉": ["薄力粉 1等"],
    "強力粉": ["強力粉 1等"], "パン粉": ["パン粉 乾燥"], "上新粉": ["上新粉"],
    "もち米粉": ["白玉粉"], "白玉粉": ["白玉粉"],

    # --- staples, raw vs cooked kept apart
    "米": ["こめ 水稲穀粒 精白米 うるち米"], "白米": ["こめ 水稲穀粒 精白米 うるち米"],
    "うるち米": ["こめ 水稲穀粒 精白米 うるち米"], "玄米": ["こめ 水稲穀粒 玄米"],
    "もち米": ["こめ 水稲穀粒 精白米 もち米"],
    "ご飯": ["こめ 水稲めし 精白米 うるち米"], "ごはん": ["こめ 水稲めし 精白米 うるち米"],
    "白飯": ["こめ 水稲めし 精白米 うるち米"], "めし": ["こめ 水稲めし 精白米 うるち米"],
    "うどん": ["うどん ゆで"], "そば": ["そば ゆで"], "そうめん": ["そうめん・ひやむぎ ゆで"],
    "中華麺": ["中華めん ゆで"], "パスタ": ["マカロニ・スパゲッティ ゆで"],
    "スパゲッティ": ["マカロニ・スパゲッティ ゆで"], "食パン": ["角形食パン 食パン"],
    "パン": ["角形食パン 食パン"],

    # --- meat, fish, eggs, dairy
    # Cuts default to 脂身つき, with the fat left on. 赤肉 is the trimmed lean
    # analysis and it is much lighter — pork もも is 119 kcal/100g lean against
    # 171 with its fat — so using it as the default for an unqualified word
    # under-counts every photograph of meat, which visibly has fat on it.
    "牛肉": ["乳用肥育牛肉 かたロース 脂身つき 生"],
    "牛もも肉": ["乳用肥育牛肉 もも 脂身つき 生"],
    "牛赤身肉": ["乳用肥育牛肉 もも 赤肉 生"],
    "牛バラ肉": ["乳用肥育牛肉 ばら 脂身つき 生"], "牛ひき肉": ["うし ひき肉 生"],
    "豚肉": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "豚もも肉": ["ぶた 大型種肉 もも 脂身つき 生"],
    "豚赤身肉": ["ぶた 大型種肉 もも 赤肉 生"],
    "豚バラ肉": ["ぶた 大型種肉 ばら 脂身つき 生"], "豚ひき肉": ["ぶた ひき肉 生"],
    "豚こま": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "豚薄切り肉": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "豚肩ロース": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "角切り豚肉": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "カレー用豚肉": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "鶏肉": ["にわとり 若どり もも 皮つき 生"], "とり肉": ["にわとり 若どり もも 皮つき 生"],
    "鶏もも肉": ["にわとり 若どり もも 皮つき 生"], "鶏むね肉": ["にわとり 若どり むね 皮つき 生"],
    "鶏ささみ": ["にわとり 若どり ささみ 生"], "ささみ": ["にわとり 若どり ささみ 生"],
    "鶏ひき肉": ["にわとり 二次品目 ひき肉 生"], "ひき肉": ["うし ひき肉 生"],
    "合いびき肉": ["うし ひき肉 生"], "ベーコン": ["ぶた ばらベーコン"],
    "ハム": ["ロースハム"], "ソーセージ": ["ウインナーソーセージ"],
    "卵": ["鶏卵 全卵 生"], "たまご": ["鶏卵 全卵 生"], "鶏卵": ["鶏卵 全卵 生"],
    "牛乳": ["普通牛乳"], "生クリーム": ["クリーム 乳脂肪"],
    "チーズ": ["プロセスチーズ"],
    "ヨーグルト": ["ヨーグルト 全脂無糖"],

    # --- soy, vegetables, mushrooms, seaweed
    "豆腐": ["木綿豆腐"], "木綿豆腐": ["木綿豆腐"], "絹ごし豆腐": ["絹ごし豆腐"],
    "油揚げ": ["だいず 油揚げ 生"], "厚揚げ": ["だいず 生揚げ"], "生揚げ": ["だいず 生揚げ"],
    "納豆": ["糸引き納豆"], "大豆": ["全粒 黄大豆 国産 乾"], "小豆": ["あずき 全粒 乾"],
    "こしあん": ["あん こし練りあん"], "つぶあん": ["あん つぶし練りあん"],
    "こんにゃく": ["こんにゃく 板こんにゃく 精粉こんにゃく"],
    "しらたき": ["こんにゃく しらたき"], "糸こんにゃく": ["こんにゃく しらたき"],
    "大根": ["だいこん 根 皮なし 生"], "だいこん": ["だいこん 根 皮なし 生"],
    "人参": ["にんじん 根 皮なし 生"], "にんじん": ["にんじん 根 皮なし 生"],
    "玉ねぎ": ["たまねぎ りん茎 生"], "玉葱": ["たまねぎ りん茎 生"],
    "たまねぎ": ["たまねぎ りん茎 生"], "長ねぎ": ["根深ねぎ 葉 軟白 生"],
    "ねぎ": ["根深ねぎ 葉 軟白 生"], "青ねぎ": ["葉ねぎ 葉 生"],
    "じゃがいも": ["じゃがいも 塊茎 皮なし 生"], "馬鈴薯": ["じゃがいも 塊茎 皮なし 生"],
    "さつまいも": ["さつまいも 塊根 皮なし 生"], "里芋": ["さといも 球茎 生"],
    "さといも": ["さといも 球茎 生"], "ごぼう": ["ごぼう 根 生"],
    "れんこん": ["れんこん 根茎 生"], "白菜": ["はくさい 結球葉 生"],
    "はくさい": ["はくさい 結球葉 生"], "キャベツ": ["キャベツ 結球葉 生"],
    "ほうれん草": ["ほうれんそう 葉 通年平均 生"], "ほうれんそう": ["ほうれんそう 葉 通年平均 生"],
    "小松菜": ["こまつな 葉 生"], "きゅうり": ["きゅうり 果実 生"],
    "なす": ["なす 果実 生"], "茄子": ["なす 果実 生"], "トマト": ["赤色トマト 果実 生"],
    "トマト缶": ["トマト 加工品 ホール 食塩無添加"],
    "ホールトマト": ["トマト 加工品 ホール 食塩無添加"],
    "カットトマト": ["トマト 加工品 ホール 食塩無添加"],
    "トマトピューレ": ["トマトピューレー"], "トマトソース": ["トマトソース"], "かぼちゃ": ["西洋かぼちゃ 果実 生"],
    "ピーマン": ["青ピーマン 果実 生"], "もやし": ["りょくとうもやし 生"],
    "たけのこ": ["たけのこ 若茎 生"], "しょうが": ["しょうが 根茎 皮なし 生"],
    "生姜": ["しょうが 根茎 皮なし 生"], "にんにく": ["にんにく りん茎 生"],
    "しいたけ": ["しいたけ 生しいたけ 菌床栽培 生"],
    "干ししいたけ": ["しいたけ 乾しいたけ 乾"], "乾しいたけ": ["しいたけ 乾しいたけ 乾"],
    "しめじ": ["ぶなしめじ 生"], "えのき": ["えのきたけ 生"], "まいたけ": ["まいたけ 生"],
    "昆布": ["まこんぶ 素干し"], "こんぶ": ["まこんぶ 素干し"],
    "わかめ": ["わかめ 原藻 生"], "ひじき": ["ほしひじき ステンレス釜 乾"],
    "のり": ["あまのり 焼きのり"], "海苔": ["あまのり 焼きのり"],
    "かつお節": ["かつお節"], "煮干し": ["かたくちいわし 煮干し"],
    "ごま": ["ごま いり"], "白ごま": ["ごま いり"], "すりごま": ["ごま いり"],

    # --- caught by eyeballing the linker's long tail, where a substring match
    # found something that merely contains the word (エビ -> エビチリの素,
    # そば粉 -> 焼きそば粉末ソース, 干し大根 -> fresh daikon at a fifth the density)
    "えび": ["バナメイえび 養殖 生"], "エビ": ["バナメイえび 養殖 生"],
    "むきえび": ["バナメイえび 養殖 生"], "干しえび": ["干しえび"],
    "そば粉": ["そば そば粉 全層粉"],
    # 「いんげん」 in a recipe is the green pod, not the dried kidney bean the
    # tables list first: 23 kcal/100g against 280, a twelvefold error on any
    # dish that uses it. The dried bean has to be asked for by name.
    "いんげん": ["いんげんまめ さやいんげん 若ざや 生"],
    "さやいんげん": ["いんげんまめ さやいんげん 若ざや 生"],
    "いんげん豆": ["いんげんまめ 全粒 乾"], "金時豆": ["いんげんまめ 全粒 乾"],
    "干し大根": ["切干しだいこん 乾"], "切り干し大根": ["切干しだいこん 乾"],
    "切干し大根": ["切干しだいこん 乾"],
    "ミニトマト": ["赤色ミニトマト 果実 生"], "プチトマト": ["赤色ミニトマト 果実 生"],
    "紅しょうが": ["しょうが 漬物 酢漬"], "しょうがの甘酢漬": ["しょうが 漬物 甘酢漬"],
    "こしょう": ["こしょう 混合 粉"], "胡椒": ["こしょう 混合 粉"],
    "鶏がらスープ": ["鶏がらだし"], "鶏ガラスープ": ["鶏がらだし"],
    "いか": ["するめいか 生"], "あさり": ["あさり 生"], "さば": ["まさば 生"],
    "鮭": ["しろさけ 生"], "さけ": ["しろさけ 生"], "たら": ["まだら 生"],
    "ぶり": ["ぶり 成魚 生"], "あじ": ["まあじ 皮つき 生"], "いわし": ["まいわし 生"],
    "ちくわ": ["蒸しかまぼこ", "焼き竹輪"], "かまぼこ": ["蒸しかまぼこ"],
}

# Preparation states the tables analyse separately. A recipe that says
# 「大豆（水煮または蒸し）」 means the boiled tin at ~163 kcal/100g, not the dried
# bean at 372 — dropping the parenthesis doubled the dish. Distinct from NOISE,
# which the tables do not record at all.
STATES = ("水煮", "ゆで", "茹で", "蒸し", "焼き", "生", "乾", "油いため", "素揚げ",
          "揚げ", "煮", "冷凍", "缶詰", "塩漬", "干し", "皮なし", "皮つき")

# Raw analysis -> the cooked one, for callers looking at a plate of food.
#
# A recipe says 米 and means the dry grain; a photograph of fried rice shows
# the same food after it has absorbed its own weight in water. Charging the
# plate at the dry rate more than doubles it — 250 g of rice on a plate is 390
# kcal cooked and 855 raw. The analyzer asks for this swap, the recipe linker
# does not.
COOKED_FORM = {
    "こめ 水稲穀粒 精白米 うるち米": "こめ 水稲めし 精白米 うるち米",
    "こめ 水稲穀粒 玄米": "こめ 水稲めし 玄米",
    "こめ 水稲穀粒 精白米 もち米": "こめ 水稲めし 精白米 もち米",
}

# Words in a dish name that mean the food reached the plate cooked.
COOKED_DISH = ("炒め", "焼き", "煮", "揚げ", "蒸し", "茹で", "ゆで", "丼", "カレー",
               "チャーハン", "炒飯", "ピラフ", "リゾット", "おにぎり", "寿司", "すし",
               "雑炊", "おかゆ", "粥", "スープ", "汁", "鍋", "定食", "弁当", "ご飯", "ライス")

_PARENS = re.compile(r"[（(\[【].*?[）)\]】]")
_SEP = re.compile(r"[・,、/／]+")


def is_cooked_dish(name):
    """Does this dish name describe food that was cooked before serving?"""
    n = normalise(name)
    return any(word in n for word in COOKED_DISH)


def normalise(name):
    """Full-width to half-width, drop bracketed asides and stray punctuation.

    MAFF recipes prefix grouped seasonings with 【調味料A】, and vision models
    like to append a state in parentheses; neither belongs in a lookup.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip()
    s = _PARENS.sub(" ", s)
    return " ".join(s.split())


def is_ignorable(name):
    """Water and ice: real recipe lines, no nutrition, not a matching failure."""
    return normalise(name).replace(" ", "") in IGNORE


def _strip_noise(s):
    for word in NOISE:
        s = s.replace(word, " ")
    return " ".join(s.split())


def search_terms(name, cooked=False):
    """Search strings to try for one ingredient, most specific first.

    The caller runs them through the ordinary site search and takes the first
    hit, so a bad guess costs a query, never a wrong number.

    `cooked` says the food is being read off a plate rather than out of a
    recipe, which decides the raw/cooked reading of a staple: see COOKED_FORM.
    A vision model will happily call the rice in a bowl of fried rice
    「白米（生）」, because that is the ingredient it was made from.
    """
    base = normalise(name)
    if not base or is_ignorable(base):
        return []
    terms, seen = [], set()

    def add(t):
        t = t.strip()
        if cooked:
            t = COOKED_FORM.get(t, t)
        if t and t not in seen:
            seen.add(t)
            terms.append(t)

    def state_of(text):
        """The preparation state named anywhere in the line, including inside
        the parenthesis that normalise() removes."""
        for st in STATES:
            if st in text:
                return st
        return None

    stripped = _strip_noise(base)
    compact = stripped.replace(" ", "")
    # the state may live inside the parenthesis normalise() dropped, so read it
    # from the original line
    state = state_of(unicodedata.normalize("NFKC", str(name)))
    if state and state not in compact:
        add(f"{compact} {state}")

    # Curated targets come first, deliberately. The raw word often matches
    # something technically containing it and wrong in practice: 砂糖 hits
    # パインアップル 砂糖漬, 米 hits そば米. The alias is the considered answer.
    for key in (base, stripped, compact):
        for target in ALIASES.get(key, ()):
            add(target)
    # then an alias for any word inside the name — 「牛ひき肉 500g」 and
    # 「合いびき肉（牛豚）」 both have to reach うし ひき肉. Longest word wins,
    # so 牛ひき肉 is not resolved as 牛肉.
    for word in sorted(ALIASES, key=len, reverse=True):
        if len(word) >= 2 and word in compact:
            for target in ALIASES[word]:
                add(target)
            break
    add(base)
    add(stripped)

    # last resort: the leading noun, since qualifiers trail in Japanese
    for part in _SEP.split(stripped):
        if len(part) >= 2:
            add(part)
    return terms


# Foods that must never be substituted for one another. The tables write meat
# in kana (ぶた, うし, にわとり) and a cook writes it in kanji, so a name that
# loses its animal — 「もも肉 生」 — hits whichever row the index likes, and beef
# was served for pork with nothing to flag it. Different animal, different
# answer: refuse the match rather than quietly answer the wrong question.
KINDS = {
    "pork": ("ぶた", "豚", "ポーク", "とんかつ"),
    "beef": ("うし", "牛", "ビーフ", "和牛"),
    "chicken": ("にわとり", "鶏", "チキン", "とり肉", "ささみ"),
    "sheep": ("めんよう", "羊", "ラム", "マトン"),
    "horse": ("うま肉", "馬肉", "馬刺"),
    "duck": ("あひる", "かも", "鴨"),
}


def kind_of(name):
    """Which animal this name is about, or None when it does not say."""
    n = normalise(name).replace(" ", "")
    for kind, words in KINDS.items():
        if any(w in n for w in words):
            return kind
    return None


def conflicts(query, candidate):
    """True when the two names are about different animals."""
    a, b = kind_of(query), kind_of(candidate)
    return bool(a and b and a != b)


def alias_target(name):
    """The curated table name for this word, or None if it is not a word we
    have decided about. A hit here is trustworthy enough to link without asking
    a model."""
    base = normalise(name)
    compact = _strip_noise(base).replace(" ", "")
    for key in (base, compact):
        if key in ALIASES:
            return ALIASES[key][0]
    for word in sorted(ALIASES, key=len, reverse=True):
        if len(word) >= 2 and word in compact:
            return ALIASES[word][0]
    return None
