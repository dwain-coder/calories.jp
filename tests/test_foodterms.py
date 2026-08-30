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


if __name__ == "__main__":
    unittest.main()
