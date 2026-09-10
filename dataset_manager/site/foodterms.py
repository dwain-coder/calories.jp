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
    # --- cuts a model names and the tables spell differently. Every one of
    # these came back UNMATCHED from a real photograph while the food itself
    # was in the corpus under its kana headword: 牛→うし, 豚→ぶた, 明太子→めんたいこ.
    "牛かた肉": ["うし 乳用肥育牛肉 かた 脂身つき 生"],
    "牛かたロース": ["うし 乳用肥育牛肉 かたロース 脂身つき 生"],
    "牛ばら肉": ["うし 乳用肥育牛肉 ばら 脂身つき 生"],
    "牛ヒレ肉": ["うし 乳用肥育牛肉 ヒレ 赤肉 生"],
    "牛もも肉": ["うし 乳用肥育牛肉 もも 脂身つき 生"],
    "豚かた肉": ["ぶた 大型種肉 かた 脂身つき 生"],
    "豚ヒレ肉": ["ぶた 大型種肉 ヒレ 赤肉 生"],
    "豚ばら肉": ["ぶた 大型種肉 ばら 脂身つき 生"],
    "豚もも肉": ["ぶた 大型種肉 もも 脂身つき 生"],
    "合挽き肉": ["うし ひき肉 生"], "牛豚合挽き肉": ["うし ひき肉 生"],
    "合いびき": ["うし ひき肉 生"],
    "チャーシュー": ["ぶた その他 焼き豚"], "焼き豚": ["ぶた その他 焼き豚"],
    "焼豚": ["ぶた その他 焼き豚"],
    # --- everyday names for things the tables file under a parent food
    "明太子": ["すけとうだら からしめんたいこ"],
    "辛子明太子": ["すけとうだら からしめんたいこ"],
    "からし明太子": ["すけとうだら からしめんたいこ"],
    "たらこ": ["すけとうだら たらこ 生"],
    "卵焼き": ["鶏卵 たまご焼 厚焼きたまご"],
    "玉子焼き": ["鶏卵 たまご焼 厚焼きたまご"],
    "厚焼き卵": ["鶏卵 たまご焼 厚焼きたまご"],
    "だし巻き卵": ["鶏卵 たまご焼 だし巻きたまご"],
    "酢飯": ["こめ 水稲めし 精白米 うるち米"],
    "すし飯": ["こめ 水稲めし 精白米 うるち米"],
    "シャリ": ["こめ 水稲めし 精白米 うるち米"],
    "焼き麩": ["こむぎ 焼きふ 釜焼きふ"], "焼きふ": ["こむぎ 焼きふ 釜焼きふ"],
    "お麩": ["こむぎ 焼きふ 釜焼きふ"],
    "メンマ": ["たけのこ めんま 塩蔵 塩抜き"], "めんま": ["たけのこ めんま 塩蔵 塩抜き"],
    "いちごジャム": ["いちご ジャム 高糖度"],
    "オレンジジュース": ["オレンジ バレンシア 果実飲料 ストレートジュース"],
    "黒みつ": ["黒砂糖"], "黒蜜": ["黒砂糖"],
    "ねりからし": ["からし 練り"], "練りからし": ["からし 練り"],
    "銀だら": ["ぎんだら 生"], "銀ダラ": ["ぎんだら 生"],
    "大葉": ["しそ 葉 生"], "青じそ": ["しそ 葉 生"],
    "なると": ["なると"], "ナルト": ["なると"], "鳴門巻き": ["なると"],
    # --- found by widening the benchmark from eleven photographs to twenty-three.
    # Eleven was enough to see a bias and not enough to find these: a 150 g
    # sirloin and a 200 g steak both matched nothing, which is most of why two
    # rows read 80% low.
    "牛サーロイン": ["うし 乳用肥育牛肉 サーロイン 脂身つき 生"],
    "サーロイン": ["うし 乳用肥育牛肉 サーロイン 脂身つき 生"],
    "牛リブロース": ["うし 乳用肥育牛肉 リブロース 脂身つき 生"],
    "牛ランプ": ["うし 乳用肥育牛肉 ランプ 赤肉 生"],
    "鶏手羽先": ["にわとり 若どり 手羽さき 皮つき 生"],
    "手羽先": ["にわとり 若どり 手羽さき 皮つき 生"],
    "手羽元": ["にわとり 若どり 手羽もと 皮つき 生"],
    "ビンナガ": ["びんなが 生"], "びんちょうまぐろ": ["びんなが 生"],
    "びんとろ": ["びんなが 生"],
    "合い挽き肉": ["うし ひき肉 生"], "合い挽き": ["うし ひき肉 生"],
    "ピクルス": ["きゅうり 漬物 ピクルス サワー型"],
    # --- and again at sixty-four photographs. 肩 in kanji, ロース on its own,
    # a whole roast beef, an eel and a scallop: every one is a table row we
    # already hold, reached by a spelling the aliases had not met.
    "牛肩肉": ["うし 乳用肥育牛肉 かた 脂身つき 生"],
    "牛ロース": ["うし 乳用肥育牛肉 リブロース 脂身つき 生"],
    "牛リブ": ["うし 乳用肥育牛肉 リブロース 脂身つき 生"],
    "ローストビーフ": ["うし 加工品 ローストビーフ"],
    "みすじ": ["うし 乳用肥育牛肉 かた 脂身つき 生"],
    "豚ひれカツ": ["ぶた 大型種肉 ヒレ 赤肉 とんかつ"],
    "ひれカツ": ["ぶた 大型種肉 ヒレ 赤肉 とんかつ"],
    "ヒレカツ": ["ぶた 大型種肉 ヒレ 赤肉 とんかつ"],
    "鶏そぼろ": ["にわとり 二次品目 ひき肉 焼き"],
    "鶏ひき肉": ["にわとり 二次品目 ひき肉 生"],
    "うなぎ": ["うなぎ かば焼"], "鰻": ["うなぎ かば焼"],
    "蒲焼き": ["うなぎ かば焼"], "かば焼": ["うなぎ かば焼"],
    "ホタテ": ["ほたてがい 貝柱 焼き"], "ほたて": ["ほたてがい 貝柱 焼き"],
    "貝柱": ["ほたてがい 貝柱 焼き"],
    "バカガイ": ["ばかがい 生"], "赤貝": ["あかがい 生"],
    "鮭": ["しろさけ 生"], "サケ": ["しろさけ 生"], "サーモン": ["ぎんざけ 養殖 生"],
    "パプリカ": ["赤ピーマン 果実 生"], "赤パプリカ": ["赤ピーマン 果実 生"],
    "黄パプリカ": ["黄ピーマン 果実 生"],
    "ししとうがらし": ["ししとう 果実 生"],
    "わさび": ["わさび 根茎 生"], "本わさび": ["わさび 根茎 生"],
    "ピザクラスト": ["こむぎ その他 ピザ生地"], "ピザ生地": ["こむぎ その他 ピザ生地"],
    "たくあん漬け": ["だいこん 漬物 たくあん漬 干しだいこん漬"],
    "フライドガーリック": ["にんにく りん茎 油いため"],
    "温泉卵": ["鶏卵 全卵 生"], "半熟卵": ["鶏卵 全卵 ゆで"],
    "かきたま": ["鶏卵 全卵 生"], "溶き卵": ["鶏卵 全卵 生"],
    "鮭刺身": ["しろさけ 生"], "サーモン刺身": ["ぎんざけ 養殖 生"],
    "ドレッシング": ["乳化液状ドレッシング サウザンアイランドドレッシング"],
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
    "飯": ["こめ 水稲めし 精白米 うるち米"], "ライス": ["こめ 水稲めし 精白米 うるち米"],
    "丸麦": ["おおむぎ 押麦 乾"], "押麦": ["おおむぎ 押麦 乾"],
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
    "豚ロース": ["ぶた 大型種肉 ロース 脂身つき 生"],
    "豚ロース肉": ["ぶた 大型種肉 ロース 脂身つき 生"],
    "豚バラ肉": ["ぶた 大型種肉 ばら 脂身つき 生"], "豚ひき肉": ["ぶた ひき肉 生"],
    "豚こま": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "豚薄切り肉": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "豚肩ロース": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "角切り豚肉": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "カレー用豚肉": ["ぶた 大型種肉 かたロース 脂身つき 生"],
    "鶏肉": ["にわとり 若どり もも 皮つき 生"], "とり肉": ["にわとり 若どり もも 皮つき 生"],
    "鶏もも肉": ["にわとり 若どり もも 皮つき 生"], "鶏むね肉": ["にわとり 若どり むね 皮つき 生"],
    "蒸し鶏": ["にわとり 若どり むね 皮なし 焼き", "にわとり 若どり むね 皮なし 生"],
    "サラダチキン": ["にわとり 若どり むね 皮なし 焼き", "にわとり 若どり むね 皮なし 生"],
    "小エビ": ["バナメイえび 養殖 生"], "小えび": ["バナメイえび 養殖 生"],
    "ミートソース": ["ミートソース"], "ボロネーゼ": ["ミートソース"],
    "デミグラスソース": ["デミグラスソース"], "トマトソース": ["トマトソース"],
    "コーン": ["スイートコーン 缶詰 ホールカーネルスタイル"],
    "とうもろこし": ["スイートコーン 缶詰 ホールカーネルスタイル"],
    "コーンスープ": ["洋風料理 コーンクリームスープ コーンクリームスープ"],
    "コーンクリームスープ": ["洋風料理 コーンクリームスープ コーンクリームスープ"],
    "プリン": ["カスタードプリン"], "カスタードプリン": ["カスタードプリン"],
    "鶏ささみ": ["にわとり 若どり ささみ 生"], "ささみ": ["にわとり 若どり ささみ 生"],
    "鶏ひき肉": ["にわとり 二次品目 ひき肉 生"], "ひき肉": ["うし ひき肉 生"],
    "合いびき肉": ["うし ひき肉 生"], "ベーコン": ["ぶた ばらベーコン"],
    "ハム": ["ロースハム"], "ソーセージ": ["ウインナーソーセージ"],
    "卵": ["鶏卵 全卵 生"], "たまご": ["鶏卵 全卵 生"], "鶏卵": ["鶏卵 全卵 生"],
    "牛乳": ["普通牛乳"], "生クリーム": ["クリーム 乳脂肪"],
    "チーズ": ["プロセスチーズ"],
    "ヨーグルト": ["ヨーグルト 全脂無糖"],
    "豚カツ": ["ぶた 大型種肉 ヒレ 赤肉 とんかつ", "ぶた 大型種肉 ロース 赤肉 とんかつ"],
    "とんかつ": ["ぶた 大型種肉 ヒレ 赤肉 とんかつ", "ぶた 大型種肉 ロース 赤肉 とんかつ"],
    "トンカツ": ["ぶた 大型種肉 ヒレ 赤肉 とんかつ"],
    "チキン南蛮": ["にわとり 若どり もも 皮つき 焼き"],
    "しらす": ["しらす干し 微乾燥品"],
    "シラス": ["しらす干し 微乾燥品"],
    "麦ごはん": ["こめ 水稲めし 精白米 うるち米"],
    "麦飯": ["こめ 水稲めし 精白米 うるち米"],
    "玄米ご飯": ["こめ 水稲めし 玄米"],
    "玄米ごはん": ["こめ 水稲めし 玄米"],

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
    # Hijiki is sold dried and eaten rehydrated, and no recipe means the dry
    # weight: 「ひじきの煮物 20g」 is 20 g of the soaked food. The 乾 row is
    # 180 kcal/100 g against 13 for ゆで, which put 87.6 g of carbohydrate into
    # a chicken meatball. Beans and しらす keep their dried rows deliberately —
    # those a recipe really does weigh dry.
    "わかめ": ["わかめ 原藻 生"], "ひじき": ["ほしひじき ステンレス釜 ゆで"],
    "のり": ["あまのり 焼きのり"], "海苔": ["あまのり 焼きのり"],
    "かつお節": ["かつお節"], "煮干し": ["かたくちいわし 煮干し"],
    "花カツオ": ["かつお節"], "花かつお": ["かつお節"], "削り節": ["削り節"],
    "ちりめんじゃこ": ["しらす干し 微乾燥品"], "しらす干し": ["しらす干し 微乾燥品"],
    "でんぶ": ["たら 加工品 でんぶ"], "田麩": ["たら 加工品 でんぶ"],
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
    # Common restaurant ingredients & sushi toppings
    "まぐろ": ["くろまぐろ 天然 赤身 生"], "マグロ": ["くろまぐろ 天然 赤身 生"],
    "中とろ": ["くろまぐろ 天然 脂身 生"], "大とろ": ["くろまぐろ 天然 脂身 生"],
    "サーモン": ["ぎんざけ 養殖 生"],
    "いくら": ["しろさけ すじこ"], "イクラ": ["しろさけ すじこ"],
    "うなぎ": ["うなぎ かば焼"], "穴子": ["あなご 生"],
    "たこ": ["まだこ 皮つき 生"], "タコ": ["まだこ 皮つき 生"],
    "ビール": ["ビール 淡色"], "生ビール": ["ビール 淡色"],
    "ハンバーグ": ["洋風料理 合いびきハンバーグ"],
    "フライドポテト": ["じゃがいも 塊茎 皮つき フライドポテト （生を揚げたもの）"],
    "ポテト": ["じゃがいも 塊茎 皮つき フライドポテト （生を揚げたもの）"],
    "餃子": ["中国料理 ぎょうざ"], "ギョーザ": ["中国料理 ぎょうざ"],
    "から揚げ": ["にわとり 若どり もも 皮つき 生"], "唐揚げ": ["にわとり 若どり もも 皮つき 生"],
    "ショートケーキ": ["ショートケーキ 果実なし"],
    "アイスクリーム": ["アイスクリーム 高脂肪"],
    "枝豆": ["えだまめ ゆで"],
    "アボカド": ["アボカド 生"],
}

# Preparation states the tables analyse separately. A recipe that says
# 「大豆（水煮または蒸し）」 means the boiled tin at ~163 kcal/100g, not the dried
# bean at 372 — dropping the parenthesis doubled the dish. Distinct from NOISE,
# which the tables do not record at all.
# Longest first: 「から揚げ」 must not be read as 「揚げ」, and 「油いため」 not as
# 「いため」. A cook's word (炒め, フライ) sits here beside the table's own (油いため,
# とんかつ) because the model writes the first and the search needs the second —
# STATE_SYNONYMS below is the bridge.
STATES = ("水煮", "から揚げ", "唐揚げ", "素揚げ", "天ぷら", "油いため", "とんかつ",
          "ソテー", "フライ", "炒め", "いため", "ゆで", "茹で", "蒸し", "焼き",
          "揚げ", "生", "乾", "煮", "冷凍", "缶詰", "塩漬", "干し", "皮なし", "皮つき")

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

# Innermost bracketed span, of any of the four kinds MAFF recipes use. Applied
# repeatedly, so nesting comes out from the inside: a single non-greedy pattern
# stopped at the first closing character of any type, so
# 「【調味料A（合わせ酢）】塩」 normalised to 「】塩」 and 塩 — a word this module
# has a curated answer for — matched nothing at all.
_BRACKET = re.compile(r"[（(\[【［][^（(\[【［）)\]】］]*[）)\]】］]")
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
    while True:
        stripped = _BRACKET.sub(" ", s)
        if stripped == s:
            break
        s = stripped
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
        # The model writes 炒め and the table writes 油いため, so ask for the
        # table's word as well as the one we were given. Without this the query
        # was the bare noun and the search answered with the raw row.
        for target in STATE_SYNONYMS.get(state, ()):
            add(f"{compact} {target}")
        add(f"{compact} {state}")

    # Curated targets come first, deliberately. The raw word often matches
    # something technically containing it and wrong in practice: 砂糖 hits
    # パインアップル 砂糖漬, 米 hits そば米. The alias is the considered answer.
    def add_alias(target):
        """The curated row, and the same row in the state we were told about.

        A cut alias points at one row and that row names a state — 「ぶた 大型種肉
        ヒレ 赤肉 生」. Asked for a fried pork fillet, adding the bare target
        answers with the raw one, and 「豚ヒレ肉 とんかつ」 matches nothing because
        the tables write ぶた. Swapping the state on the ALIAS is what reaches
        「ぶた 大型種肉 ヒレ 赤肉 とんかつ」, which is 379 kcal against 118.
        """
        if state:
            stem = target
            for st in STATES:
                if stem.endswith(" " + st):
                    stem = stem[: -(len(st) + 1)]
                    break
            if stem != target or state not in target:
                for word in STATE_SYNONYMS.get(state, (state,)):
                    add(f"{stem} {word}")
        add(target)

    for key in (base, stripped, compact):
        for target in ALIASES.get(key, ()):
            add_alias(target)
    # then an alias for any word inside the name — 「牛ひき肉 500g」 and
    # 「合いびき肉（牛豚）」 both have to reach うし ひき肉. Longest word wins,
    # so 牛ひき肉 is not resolved as 牛肉.
    # The parenthesis normalise() drops sometimes holds the food itself rather
    # than a qualifier: 「魚肉ねり製品 (なると)」 is a naruto, and the tables have
    # exactly one row called なると. Look inside it for a curated word too.
    inside = unicodedata.normalize("NFKC", str(name or "")).replace(" ", "")
    for word in sorted(ALIASES, key=len, reverse=True):
        if len(word) >= 2 and (word in compact or word in inside):
            for target in ALIASES[word]:
                add_alias(target)
            break
    add(base)
    add(stripped)

    # last resort: the leading noun, since qualifiers trail in Japanese
    for part in _SEP.split(stripped):
        if len(part) >= 2:
            add(part)
    return terms



# ------------------------------------------------------- preparation and cut

# A vision model names the state it can see — 「牛肉（薄切り、脂身つき、焼き）」,
# 「キャベツ（炒め）」 — and the tables publish exactly those rows: かた 脂身つき 焼き
# is 322 kcal against 175 for かた 赤肉 焼き, キャベツ 油いため is 78 against 23 for
# 生. The search returned whichever row the index liked, which was the plainest
# one, and a plate of stir-fried beef came out at half its published calories.
#
# Left is what a cook or a model writes, right is how the tables spell it.
STATE_SYNONYMS = {
    "炒め": ("油いため",), "いため": ("油いため",), "ソテー": ("油いため", "ソテー"),
    "焼き": ("焼き",), "グリル": ("焼き",),
    "ゆで": ("ゆで",), "茹で": ("ゆで",), "煮": ("水煮", "煮"),
    "蒸し": ("蒸し",), "生": ("生",),
    "揚げ": ("素揚げ", "揚げ"), "素揚げ": ("素揚げ",),
    "から揚げ": ("から揚げ",), "唐揚げ": ("から揚げ",),
    "フライ": ("フライ", "とんかつ"), "とんかつ": ("とんかつ",),
    "天ぷら": ("天ぷら",),
}

# Two ways of cutting the same animal, and the tables carry both. Naming one
# and being served the other is a factor-of-two error on the fattiest part of
# the plate, so a candidate from the wrong side is pushed DOWN rather than
# merely not promoted.
FAT_WORDS = (("脂身つき", "皮つき"), ("赤肉", "皮なし", "脂身なし"))


def _fat_side(text):
    for side, words in enumerate(FAT_WORDS):
        if any(w in text for w in words):
            return side
    return None


def state_score(asked, candidate):
    """How well a table row answers the state and cut the asker named."""
    # NFKC only: normalise() drops the parenthesis, and the parenthesis is
    # where the model puts the state — 「牛肉（薄切り、脂身つき、焼き）」.
    a = unicodedata.normalize("NFKC", str(asked or "")).replace(" ", "")
    b = unicodedata.normalize("NFKC", str(candidate or "")).replace(" ", "")
    score = 0
    for word, targets in STATE_SYNONYMS.items():
        if word in a and any(t in b for t in targets):
            score += 2
    # Do not volunteer a processing state nobody asked for. Told 「にんじん
    # （炒め）」 the reranker reached for 「にんじん 根 冷凍 油いため」 — it answers the
    # 炒め and adds a freezer the photograph said nothing about.
    for word in ("冷凍", "缶詰", "乾", "干し", "塩漬"):
        if word in b and word not in a:
            score -= 1
    side = _fat_side(a)
    if side is not None:
        other = _fat_side(b)
        if other == side:
            score += 2
        elif other is not None:
            score -= 2
    return score


def prefer_state(asked, candidates, name_of=lambda c: c):
    """Reorder candidates so the ones matching the named state come first.

    Stable: rows that score the same keep the order the search gave them, so
    this only ever moves a better-qualified row up past a worse-qualified one.
    """
    if not asked or len(candidates) < 2:
        return candidates
    scored = [(state_score(asked, name_of(c)), -i, c) for i, c in enumerate(candidates)]
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [c for _s, _i, c in scored]


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
    found = [kind for kind, words in KINDS.items() if any(w in n for w in words)]
    # 「牛豚合挽き肉」 names two animals, so it is about neither of them on its
    # own — reading it as pork made every beef row a conflict and left 100 g of
    # mince out of a hamburger plate entirely. A name that says two says none.
    return found[0] if len(found) == 1 else None


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


# A composition table's canonical entry for a preservable food is the DRIED
# one, because that is how it is sold. A recipe saying 「ひじき 20g」 means 20 g
# of rehydrated hijiki, and MEXT's 乾 row is 186 kcal/100 g against 13 for ゆで
# — fourteen times over. 乾しいたけ is ten times 生しいたけ. That is how a
# chicken meatball came to carry 87.6 g of carbohydrate.
# MEXT names a row as food, form, then preparation: 「ひじき ほしひじき 鉄釜 ゆで」.
# The PREPARATION decides, and it is last — ほしひじき is the product even when
# the row is the boiled one, so a plain substring test calls the boiled row
# dried. Rehydration is checked first for that reason. There is no word boundary
# between CJK characters either, so 乾 has to be matched bare.
DRIED = re.compile(r"乾|干し|ほし|素干し|煮干し|粉末|パウダー|フリーズドライ")
REHYDRATED = re.compile(r"ゆで|茹で|水煮|水戻し|もどし|戻し|生|蒸し|油いため|甘煮")


def says_dried(name):
    """Whether this name is the dried form.

    A composition table's canonical entry for a preservable food is the dried
    one, because that is how it is sold. 「ひじき」 resolves to 乾 at 186 kcal/100 g
    against 13 for ゆで — fourteen times over — and 乾しいたけ is ten times
    生しいたけ. A recipe saying 「ひじき 20g」 means 20 g of the rehydrated food,
    and reading it as the dried one is how a chicken meatball came to carry
    87.6 g of carbohydrate.
    """
    text = normalise(name or "")
    if REHYDRATED.search(text):
        return False
    return bool(DRIED.search(text))


def prefer_rehydrated(asked, candidates, name_of=lambda c: c):
    """Reorder so a rehydrated entry outranks a dried one.

    Only when the asked-for name does NOT say dried: 「乾しいたけ」 means the dried
    mushroom and must keep it. Candidates are otherwise left in their original
    order, so this can only move a dried row down, never invent a match.
    """
    if says_dried(asked):
        return candidates
    fresh = [c for c in candidates if not says_dried(name_of(c))]
    return fresh + [c for c in candidates if says_dried(name_of(c))] if fresh else candidates
