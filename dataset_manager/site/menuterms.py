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
