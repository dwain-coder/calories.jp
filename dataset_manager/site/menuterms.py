"""Reduce a restaurant menu name to the food underneath it.

A composition table lists 「まぐろ」. A menu lists 「炙りとろサーモンつつみ（2貫）」.
Both name the same fish, and the gap between them is the single reason most menu
dishes fail to resolve — 13,023 of 17,876 found no candidate at all on the first
pass, and a sample showed the misses were overwhelmingly decoration, not absence.

So this strips the decoration and hands the remainder to the existing matcher.
It is a vocabulary, not a parser: the same shape as site/foodterms, and wrong in
the same safe direction — an over-stripped name simply finds no candidate, and an
unresolved dish shows a dash rather than a guess.

Drinks are NOT special-cased here, and an earlier version that skipped them was
wrong: the tables carry a beverages section, so ビール is 39 kcal per 100 g and
清酒 is 107, and skipping them threw away real answers on a calorie site. Measured
cost of that mistake: 149 fewer dishes matched and 3 fewer shops indexable.
"""
import re

# Anything a menu writes to sell the dish, which the tables do not know about.
# Order matters only for readability; every pattern is removed.
DECORATIONS = (
    # bracketed asides: (ごま入り), （2貫）, 【新登場】, ＜期間限定＞
    re.compile(r"[（(\[【〔＜<《「『][^）)\]】〕＞>》」』]*[）)\]】〕＞>》」』]"),
    # counts and portions: 6個, 2貫, 3枚, 1本, 2ピース, 1人前, 300g, ハーフ
    re.compile(r"\d+\s*(個|貫|枚|本|串|杯|玉|切れ|ピース|人前|名様|g|ｇ|グラム|ml|ｍｌ)"),
    # size and volume markers, including bare trailing S/M/L
    re.compile(r"(大盛|中盛|小盛|特盛|並盛|メガ盛|山盛|増量|ハーフ|ミニ|レギュラー|ジャンボ)"),
    re.compile(r"\s+[SMLＳＭＬ]$"),
    # sales language
    re.compile(r"(特製|自家製|名物|厳選|特選|究極|極上|絶品|人気|新登場|数量限定|期間限定|"
               r"おすすめ|オススメ|お得|得々|selected|Special)"),
    # sushi and serving FORMS — the dish is the fish, not the shape it arrives in
    re.compile(r"(軍艦|握り|にぎり|巻き|巻|つつみ|包み|串|丼ぶり|セット|盛り合わせ|盛合わせ|"
               r"盛り|食べ比べ|詰め合わせ)"),
    # preparation and seasoning suffixes the table handles separately
    re.compile(r"(炙り|あぶり|炭火焼|直火焼|香ばし|濃厚|冷やし|温|生|活)"),
    re.compile(r"(ゆず塩|柚子塩|わさび|マヨ|マヨネーズ|ねぎ塩|塩だれ|甘だれ|タレ|たれ|"
               r"ポン酢|おろし|薬味)"),
    # provenance the table does not model: (カナダ産) is already bracketed, but
    # bare 「北海道産」「国産」 appear too
    re.compile(r"(国産|北海道産|九州産|三陸産|近海|天然|養殖)"),
)

# Left after stripping, these mean nothing on their own.
_EMPTY = re.compile(r"^[\s・、,／/&＆\-–—+＋の]*$")


def normalize(name):
    """A menu name reduced to searchable food words, or None if nothing is left.

    Returns None rather than a bare fragment when stripping consumed the name:
    「盛り合わせ」 with the form word removed is not a food, and searching for the
    empty string would match the whole table.
    """
    if not name:
        return None
    out = name
    for rule in DECORATIONS:
        out = rule.sub(" ", out)
    out = re.sub(r"[　\s]+", " ", out).strip(" ・、,／/&＆-–—+＋")
    if _EMPTY.match(out) or len(out) < 2:
        return None
    return out


def variants(name):
    """Search strings to try for one menu name, best first, without duplicates.

    The raw name first: when a menu happens to write 「まぐろ」 plainly, that is a
    better search than anything stripping could produce.
    """
    seen, out = set(), []
    for candidate in (name, normalize(name)):
        if candidate and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


# How much of the dish name the matched term has to account for.
#
# THE RULE THIS ENCODES: a dish is not its ingredients. The recipe matcher in
# build_site exists to resolve a line like 「醤油 大さじ2」 and is right to answer
# こいくちしょうゆ. Handed a whole dish name it answers the same way, and an audit
# of the first run showed what that produces: 「まぐろ醤油ラーメン」 costed as soy
# sauce, 「チキンカツサンド ～粒マスタード＆デミソース～」 as Worcestershire sauce,
# and a bottle of champagne as French bread at 289 kcal. Every one of those would
# have printed a confident, wrong number on a page whose only value is the number.
#
# So a deterministic match is accepted only when the term that matched accounts
# for most of the dish name — 「納豆」 for 納豆, not 「ソース」 for a cutlet sandwich.
# Anything less goes to the model as a dish-level question, or stays a dash.
COVERAGE_MIN = 0.7


def covers(dish_name, term):
    """Does `term` account for enough of `dish_name` to be that dish, not an
    ingredient of it? Compares against the decoration-stripped name, so
    「納豆 (Natto)」 still counts as fully covered by 「納豆」."""
    if not dish_name or not term:
        return False
    core = normalize(dish_name) or dish_name
    core = re.sub(r"[\s　・、,／/&＆\-–—+＋]", "", core)
    stripped_term = re.sub(r"[\s　]", "", term)
    if not core:
        return False
    return len(stripped_term) / len(core) >= COVERAGE_MIN


# --- rows that are not a dish ------------------------------------------------
# A menu lists what a kitchen will bring you, and some of that is not food a
# reader is counting: a bottomless glass of water, a side of mustard, 「追加チーズ」.
# They pad the calorie table without adding a fact to it.
#
# The rules below match the WHOLE name or its opening word, never a substring.
# 「豚骨醤油ラーメン」 contains 醤油 and 「濃厚渡り蟹のトマトクリームソース 生パスタ」
# contains ソース; both are dishes, and a substring rule would delete them.

# An add-on, priced separately and eaten as part of something else.
_EXTRA_PREFIX = re.compile(
    r"^(?:トッピング|追加|増量|大盛(?:り)?|替(?:え)?玉|おかわり|お代わり|セット割|"
    r"ライス大盛|麺大盛)[\s　:：]*")

# The whole name is a seasoning or a table condiment.
_CONDIMENT_ONLY = re.compile(
    r"^(?:ソース|各種ソース|ドレッシング|マヨネーズ|ケチャップ|マスタード|わさび|ワサビ|"
    r"生わさび|しょうゆ|醤油|お醤油|塩|藻塩|岩塩|タレ|たれ|specialタレ|ふりかけ|七味|"
    r"一味|山椒|粉山椒|辛子|からし|ラー油|食べるラー油|酢|お酢|ガリ|紅生姜|生姜|薬味|"
    r"のり|海苔|刻みのり|バター|ジャム|シロップ|ガムシロップ|ミルク|フレッシュ|氷|"
    r"お冷|水|お水|おしぼり|割り箸)$")

# Drinks get their own vocabulary rather than borrowing the display classifier
# in brand_assets: that one is ordered for icons, so it files 「アイスコーヒー」
# under デザート (「アイス」 matches first) and 「カフェオレ」 under 料理, and a page
# filtered on it kept the drinks it was supposed to drop.
_DRINK = re.compile(
    r"コーヒー|珈琲|カフェ(?:オレ|ラテ|モカ|イン)|エスプレッソ|カプチーノ|ラテ|"
    r"紅茶|ティー|ウーロン|烏龍|緑茶|麦茶|ほうじ茶|玄米茶|煎茶|ジャスミン茶|"
    r"ジュース|コーラ|ソーダ|サイダー|ドリンク|スムージー|シェイク|フロート|"
    r"レモネード|ラッシー|カルピス|牛乳|ミルク|ネクター|エード|ウォーター|"
    r"ビール|発泡酒|ハイボール|サワー|酎ハイ|チューハイ|ワイン|焼酎|日本酒|"
    r"カクテル|ウイスキー|ウィスキー|ジントニック|梅酒|マッコリ|紹興酒|泡盛")

# A drink word inside a dish is still a dish: 抹茶パフェ, コーヒーゼリー, ビール酵母
# パン, ミルクレープ. The form word wins.
_DRINK_FALSE_FRIEND = re.compile(
    r"パフェ|ケーキ|ゼリー|プリン|アイスクリーム|ソフトクリーム|パン|クレープ|"
    r"タルト|ムース|シェーク丼|丼|麺|そば|うどん|ラーメン|定食|セット|サンド|"
    r"カレー|ピザ|パスタ|グラタン|煮|焼き?豚|酵母|漬け?")

# Kept for callers that already have the display category to hand.
_DRINK_CATEGORIES = frozenset({"ドリンク", "アルコール", "コーヒー"})


def is_extra(name):
    """A topping, a refill or a side of sauce rather than a dish."""
    n = (name or "").strip()
    if not n:
        return False
    return bool(_EXTRA_PREFIX.match(n) or _CONDIMENT_ONLY.match(n))


def is_drink(name, category=None):
    """A beverage. `category`, when given, is classify_dish_visual's label."""
    n = (name or "").strip()
    if not n:
        return False
    if _DRINK.search(n) and not _DRINK_FALSE_FRIEND.search(n):
        return True
    return category in _DRINK_CATEGORIES and not _DRINK_FALSE_FRIEND.search(n)
