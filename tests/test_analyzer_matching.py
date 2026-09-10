"""What the analyzer's ingredient matching must not go back to.

Twelve photographs of chain meals were run through the live endpoint and the
responses saved in `data/raw/analyzer_examples/`. Because the chains publish
calories for those same menu items, the matching has ground truth: replay the
model's ingredient names through the matcher, re-total, and compare.

At the point this was written the total ran a MEDIAN 34% BELOW the published
figure and sixteen ingredients matched nothing at all. Two causes, both here:

  * the tables spell meat and roe in kana — うし, ぶた, めんたいこ — and a model
    writes 牛かた肉, 豚ヒレ肉, 辛子明太子, so a 150 g steak matched nothing and
    contributed nothing;
  * the model names the state it can see, 「牛肉（薄切り、脂身つき、焼き）」, and the
    search returned the plainest row that contained the noun — 175 kcal of
    赤肉 for a 322 kcal 脂身つき cut, 23 kcal of raw cabbage for 78 of 油いため.
"""
import json
import unittest
from pathlib import Path

from dataset_manager.site import foodterms

RAW = Path("data/raw/analyzer_examples")


def match(name):
    from dataset_manager.api.analyzer import _match_food
    hit = _match_food(name, None, "ja")
    return (hit.get("name") or hit.get("title")) if hit else None


class TestTheStateTheModelNamed(unittest.TestCase):
    """The tables publish the cooked and the fatty rows. Use them."""

    def test_a_cut_with_its_fat_is_not_answered_with_the_lean_one(self):
        got = match("牛肉（薄切り、脂身つき、焼き）")
        self.assertIn("脂身つき", got)
        self.assertNotIn("赤肉", got)

    def test_stir_fried_is_not_answered_with_raw(self):
        self.assertIn("油いため", match("キャベツ（炒め）"))
        self.assertIn("油いため", match("もやし（炒め）"))

    def test_a_deep_fried_cut_reaches_the_deep_fried_row(self):
        self.assertIn("とんかつ", match("豚ヒレ肉 (赤肉、フライ)"))

    def test_scoring_prefers_the_row_that_answers_both_words(self):
        both = foodterms.state_score("牛肉（脂身つき、焼き）", "うし かた 脂身つき 焼き")
        one = foodterms.state_score("牛肉（脂身つき、焼き）", "うし かた 赤肉 焼き")
        self.assertGreater(both, one)

    def test_the_wrong_side_of_the_cut_is_pushed_down_not_merely_not_promoted(self):
        self.assertLess(foodterms.state_score("鶏もも肉（皮つき）", "にわとり もも 皮なし 生"), 0)

    def test_reordering_is_stable_where_nothing_distinguishes_the_rows(self):
        rows = ["あ 生", "い 生", "う 生"]
        self.assertEqual(foodterms.prefer_state("だいこん", rows), rows)


class TestTheNamesTheTablesUseInstead(unittest.TestCase):
    """Every one of these was unmatched while the food sat in the corpus."""

    CASES = (
        ("牛かた肉（ステーキ）", "うし"),
        ("豚ヒレ肉 (赤肉、フライ)", "ぶた"),
        ("辛子明太子", "めんたいこ"),
        ("卵焼き", "たまご焼"),
        ("酢飯", "水稲めし"),
        ("豚ばら肉（チャーシュー）", "ぶた"),
        ("焼き麩", "焼きふ"),
        ("オレンジジュース", "オレンジ"),
        ("いちごジャム", "いちご"),
        ("メンマ（味付け）", "めんま"),
        ("ねりからし", "からし"),
    )

    def test_each_one_now_reaches_a_composition_table_row(self):
        for asked, expect in self.CASES:
            with self.subTest(asked):
                got = match(asked)
                self.assertIsNotNone(got, f"{asked} still matches nothing")
                self.assertIn(expect, got)


class TestAnimals(unittest.TestCase):

    def test_a_name_that_says_two_animals_says_neither(self):
        """牛豚合挽き肉 read as pork made every beef row a conflict, and 100 g of
        mince fell out of a hamburger plate."""
        self.assertIsNone(foodterms.kind_of("牛豚合挽き肉"))
        self.assertFalse(foodterms.conflicts("牛豚合挽き肉", "うし ひき肉 生"))
        self.assertFalse(foodterms.conflicts("牛豚合挽き肉", "ぶた ひき肉 生"))

    def test_one_animal_still_refuses_the_other(self):
        self.assertEqual(foodterms.kind_of("豚ロース"), "pork")
        self.assertTrue(foodterms.conflicts("豚ロース", "うし かた 赤肉 生"))


class TestAgainstWhatTheChainsPublish(unittest.TestCase):
    """The regression set. `tools/score_analyzer.py` prints the same figures."""

    @classmethod
    def setUpClass(cls):
        import sqlite3
        from tools.score_analyzer import rescore

        conn = sqlite3.connect("data/metadata/dataset_manager.db")
        cls.rows, cls.misses = [], []
        for path in sorted(RAW.glob("*.json")):
            if not path.stem.isdigit():
                continue      # a home page example, not a scored chain photograph
            row = conn.execute(
                """SELECT cn.energy_kcal FROM product_photos pp
                   LEFT JOIN shop_menu_items smi ON smi.id = pp.shop_menu_item_id
                   LEFT JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
                   WHERE pp.shop_menu_item_id = ?""", (int(path.stem),)).fetchone()
            if not row or row[0] is None:
                continue
            kcal, _hits, misses = rescore(
                json.loads(path.read_text(encoding="utf-8")))
            cls.rows.append((path.stem, row[0], kcal))
            cls.misses += misses
        conn.close()

    def test_the_set_is_still_there(self):
        self.assertGreaterEqual(len(self.rows), 10)

    def test_the_total_is_no_longer_biased_low(self):
        errs = sorted((got - pub) / pub * 100 for _s, pub, got in self.rows)
        median = errs[len(errs) // 2]
        self.assertGreater(median, -20, f"back to under-reading: median {median:+.0f}%")
        self.assertLess(median, 25, f"now over-reading: median {median:+.0f}%")

    def test_almost_nothing_is_left_unmatched(self):
        """Sixteen ingredients matched nothing, 690 g of food. Anything that
        reappears here is a name the tables carry under another spelling."""
        heavy = [(n, g) for n, g in self.misses if g and g >= 5]
        self.assertFalse(heavy, f"unmatched again: {heavy}")


class TestTheTotalSaysWhenItIsPartial(unittest.TestCase):

    def test_the_api_declares_it(self):
        source = Path("dataset_manager/api/analyzer.py").read_text(encoding="utf-8")
        self.assertIn('"totals_partial": bool(unmatched)', source)
        self.assertIn('"unmatched_grams"', source)

    def test_the_widget_renders_a_lower_bound(self):
        js = Path("static/analyzer.js").read_text(encoding="utf-8")
        self.assertIn("d.totals_partial", js)
        self.assertIn("partialTotal", js)


if __name__ == "__main__":
    unittest.main()
