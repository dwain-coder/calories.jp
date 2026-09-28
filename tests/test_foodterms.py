"""Everyday Japanese food words must reach the right row of the tables.

These are the words that actually appear in MAFF recipes and in what a vision
model calls the food on a plate. Every one of them failed before the term layer
existed — 醤油, 鶏肉, サラダ油 and 牛ひき肉 matched nothing at all, and 砂糖 and
米 matched the wrong thing, which is worse.
"""
import unittest

from dataset_manager.api.analyzer import _match_food
from dataset_manager.site import foodterms

# everyday word -> a fragment that must appear in the matched table name
EXPECTED = {
    "醤油": "こいくちしょうゆ",
    "しょうゆ": "こいくちしょうゆ",
    "砂糖": "上白糖",
    "塩": "食塩",
    "みそ": "米みそ",
    "酒": "清酒",
    "みりん": "本みりん",
    "だし汁": "かつお・昆布だし",
    "サラダ油": "調合油",
    "小麦粉": "薄力粉",
    "片栗粉": "でん粉",
    "米": "水稲穀粒 精白米 うるち米",
    "ご飯": "水稲めし 精白米 うるち米",
    "もち米": "精白米 もち米",
    "牛肉": "うし",
    "牛肉（加熱）": "うし",
    "牛ひき肉": "ひき肉",
    "豚バラ肉": "ぶた",
    "鶏肉": "にわとり",
    "鶏むね肉": "むね",
    "卵": "鶏卵 全卵 生",
    "牛乳": "普通牛乳",
    "木綿豆腐": "木綿豆腐",
    "油揚げ": "油揚げ",
    "こんにゃく": "こんにゃく",
    "玉ねぎ（みじん切り）": "たまねぎ",
    "にんじん": "にんじん",
    "じゃがいも": "じゃがいも",
    "大根": "だいこん",
    "干ししいたけ": "乾しいたけ",
    "昆布": "こんぶ",
    "トマト缶": "トマト 加工品 ホール",
    "ナチュラルチーズ": "ナチュラルチーズ ゴーダ",
}


class TestIngredientVocabulary(unittest.TestCase):
    def test_everyday_words_reach_the_right_row(self):
        misses = []
        for word, fragment in EXPECTED.items():
            match = _match_food(word, None, "ja")
            name = match["name"] if match else None
            if not name or fragment not in name:
                misses.append(f"{word} -> {name!r} (wanted {fragment!r})")
        self.assertEqual(misses, [], "\n" + "\n".join(misses))

    def test_water_is_ignored_not_matched(self):
        """Water is a real recipe line with nothing to contribute. Matching it
        to 水煮 anything would put invented calories into a dish."""
        for word in ("水", "お湯", "熱湯", "氷"):
            self.assertTrue(foodterms.is_ignorable(word), word)
            self.assertIsNone(_match_food(word, None, "ja"), word)

    def test_longest_alias_wins(self):
        """牛ひき肉 must not be resolved through the shorter 牛肉."""
        terms = foodterms.search_terms("牛ひき肉")
        self.assertEqual(terms[0], "うし ひき肉 生")

    def test_normalise_strips_recipe_furniture(self):
        self.assertEqual(foodterms.normalise("【調味料A】砂糖"), "砂糖")
        self.assertEqual(foodterms.normalise("牛肉（加熱）"), "牛肉")
        self.assertEqual(foodterms.normalise("ＡＢＣ"), "ABC")   # full-width

    def test_every_alias_target_exists_in_the_corpus(self):
        """A target that matches nothing is worse than no alias at all.

        When 大豆's target named a row that did not exist, the lookup fell
        through to the bare word, matched 大豆油, and costed 600 g of soybeans
        as 600 g of oil — 5,310 kcal in one dish.
        """
        import sqlite3
        from dataset_manager.api.database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        missing = []
        for word, targets in foodterms.ALIASES.items():
            hit = conn.execute(
                """SELECT 1 FROM item_names nm JOIN items i ON i.id = nm.item_id
                   WHERE i.source = 'MEXT Standard Tables' AND nm.lang = 'ja'
                     AND nm.is_primary = 1 AND nm.name LIKE ? LIMIT 1""",
                (f"%{targets[0]}%",)).fetchone()
            if not hit:
                missing.append(f"{word} -> {targets[0]}")
        conn.close()
        self.assertEqual(missing, [], "; ".join(missing))

    def test_unknown_food_stays_unmatched(self):
        """No alias may invent a match for something the tables lack."""
        self.assertIsNone(_match_food("ズィーグルンプフ", None, "ja"))

    def test_nested_brackets_come_off(self):
        """MAFF groups seasonings under labels that contain their own
        parentheses. A non-greedy strip stopped at the first closing character
        of any kind and left 「】塩」, so salt — a curated word — matched
        nothing, and the line went to the model to be declined."""
        self.assertEqual(foodterms.normalise("【調味料A（合わせ酢）】塩"), "塩")
        self.assertEqual(foodterms.alias_target("【調味料A（合わせ酢）】塩"), "食塩")
        self.assertEqual(foodterms.alias_target("【調味料A（合わせ酢）】酢"), "穀物酢")
        self.assertEqual(foodterms.normalise("しそ（塩づけ）（刻み）"), "しそ")

    def test_ingen_is_the_pod_not_the_dried_bean(self):
        """Caught by reviewing what the model picked: it read 「いんげん」 as
        the dried kidney bean, 280 kcal/100g, where a recipe means the green
        pod at 23. Both readings must be reachable, and the common one has to
        be the default."""
        self.assertIn("さやいんげん", foodterms.alias_target("いんげん"))
        self.assertIn("全粒", foodterms.alias_target("いんげん豆"))
        pod = _match_food("いんげん", None, "ja")
        self.assertLess(pod["energy_kcal"], 60)

    def test_alias_word_inside_another_foods_name_is_refused(self):
        """Measured 2026-09-28 over every table food whose name holds an alias
        word: すいか came back as squid, スライスハム as rice, 七面鳥ひき肉 as
        beef mince. Each is a food the tables carry under its own name."""
        misses = []
        for name in ("すいか", "スライスハム", "甘納豆", "ポテトチップス", "メロンパン",
                     "あんパン", "カレーパン", "ごまさば", "たけのこいも", "えごま油",
                     "とんぶり", "おかひじき", "なぎなたこうじゅ", "たらのめ",
                     "たらばがに", "七面鳥ひき肉", "そうめんかぼちゃ", "赤たまねぎ"):
            match = _match_food(name, None, "ja")
            got = match["name"] if match else None
            if not got or name not in got:
                misses.append(f"{name} -> {got!r}")
        self.assertEqual(misses, [], "\n" + "\n".join(misses))

    def test_alias_word_as_a_qualified_food_still_applies(self):
        """The substring rule exists for these, and must keep reaching them."""
        self.assertEqual(foodterms.search_terms("牛ひき肉 500g")[0], "うし ひき肉 生")
        self.assertEqual(foodterms.search_terms("合いびき肉（牛豚）")[0], "うし ひき肉 生")
        # ぶなしめじ holds しめじ, but it is the row the alias points at
        self.assertEqual(foodterms.search_terms("しめじ")[0], "ぶなしめじ 生")

    def test_a_group_label_cannot_veto_the_ingredient(self):
        """【辛子酢みそ】 is the name of a table food and holds みそ; the 米みそ
        written after it is still miso."""
        self.assertEqual(foodterms.search_terms("【辛子酢みそ】米みそ")[0], "米みそ 淡色辛みそ")

    def test_a_food_the_search_cannot_return_does_not_refuse(self):
        """FDC has a ポークソーセージ row with no page. Refusing the ソーセージ
        alias on its account left a grilled sausage matching nothing."""
        match = _match_food("ポークソーセージ (焼き)", None, "ja")
        self.assertIsNotNone(match)
        self.assertIn("ソーセージ", match["name"])

    def test_exact_only_words_still_skip_the_substring_rule(self):
        self.assertEqual(foodterms.search_terms("ソース")[0], "ウスターソース")
        self.assertNotIn("ウスターソース", foodterms.search_terms("チーズソース"))

    def test_a_longer_name_is_another_food(self):
        """The home page's own example read 「たけのこ（水煮・煮物）」 as
        たけのこいも — a taro, 86 kcal/100 g against 22 — because both have a 水煮
        row and the 缶詰 penalty pushed the bamboo shoot below it."""
        self.assertEqual(
            foodterms.prefer_state("たけのこ（水煮・煮物）",
                                   ["たけのこ 水煮缶詰", "たけのこいも 球茎 水煮"])[0],
            "たけのこ 水煮缶詰")
        self.assertEqual(_match_food("たけのこ（水煮・煮物）", None, "ja")["name"],
                         "たけのこ 水煮缶詰")

    def test_karashi_is_the_paste_not_the_leaf(self):
        """「からし」 on a plate is mustard paste; からしな is a leaf vegetable
        and からし明太子 is roe. The alias is exact-only so neither is caught."""
        self.assertEqual(_match_food("からし (ペースト)", None, "ja")["name"], "からし 練り")
        self.assertIn("からしな", _match_food("からしな", None, "ja")["name"])
        self.assertIn("めんたいこ", _match_food("からし明太子", None, "ja")["name"])


if __name__ == "__main__":
    unittest.main()
