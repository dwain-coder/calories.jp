import unittest

from dataset_manager.calc.quantities import (parse_quantity, parse_quantity_detail,
                                             parse_recipe_lines)


class TestParseQuantity(unittest.TestCase):
    def test_kg_with_parenthetical(self):
        self.assertEqual(parse_quantity("2kg（2本）"), 2000.0)

    def test_grams(self):
        self.assertEqual(parse_quantity("600g"), 600.0)
        self.assertEqual(parse_quantity("160g （小豆：砂糖=1：1、塩少々）"), 160.0)

    def test_fullwidth_digits(self):
        self.assertEqual(parse_quantity("２ｋｇ"), 2000.0)

    def test_decimal(self):
        self.assertEqual(parse_quantity("1.5kg"), 1500.0)

    def test_tablespoon_soy(self):
        self.assertEqual(parse_quantity("大さじ1", name="しょうゆ"), 18.0)

    def test_tablespoon_default(self):
        self.assertEqual(parse_quantity("大さじ2", name="だし汁"), 30.0)

    def test_teaspoon(self):
        self.assertEqual(parse_quantity("小さじ3", name="砂糖"), 9.0)

    def test_to_taste_none(self):
        self.assertIsNone(parse_quantity("適量"))
        self.assertIsNone(parse_quantity("少々"))
        self.assertIsNone(parse_quantity("お好みで"))

    def test_ml_liquid_allowlist(self):
        self.assertEqual(parse_quantity("150ml", name="ぬるま湯"), 150.0)
        self.assertEqual(parse_quantity("200cc", name="だし汁"), 200.0)

    def test_ml_non_liquid_none(self):
        self.assertIsNone(parse_quantity("100ml", name="サラダ油"))

    def test_counts_convert_only_for_known_foods(self):
        """This assertion used to be "counts are always None". Counts now
        convert where a reference weight exists for that food and counter —
        see TestCountedQuantities — and still refuse everywhere else, which
        is the part that matters."""
        self.assertEqual(parse_quantity("2本", name="大根"), 1600.0)
        self.assertEqual(parse_quantity("1個", name="玉ねぎ"), 200.0)
        self.assertIsNone(parse_quantity("2本", name="知らない野菜"))
        self.assertIsNone(parse_quantity("2粒", name="大根"))   # counter we have no weight for

    def test_empty_none(self):
        self.assertIsNone(parse_quantity(""))
        self.assertIsNone(parse_quantity(None))


class TestParseRecipeLines(unittest.TestCase):
    def test_tab_separated(self):
        blob = "もち米粉\t195g\nぬるま湯\t150ml\n三つ葉\t適量"
        rows = parse_recipe_lines(blob)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], (0, "もち米粉", "195g", 195.0, "measure"))
        self.assertEqual(rows[1][3], 150.0)  # 湯 on liquid allowlist
        self.assertIsNone(rows[2][3])

    def test_space_separated_fallback(self):
        rows = parse_recipe_lines("大根 600g")
        self.assertEqual(rows[0][1], "大根")
        self.assertEqual(rows[0][3], 600.0)

    def test_empty(self):
        self.assertEqual(parse_recipe_lines(None), [])
        self.assertEqual(parse_recipe_lines(""), [])


class TestCountedQuantities(unittest.TestCase):
    """4,386 recipe lines carry a count and no weight. Refusing all of them
    left hundreds of dishes with no figures; converting them silently would
    have been worse, so a converted weight is tagged 'unit'."""

    def test_known_food_and_counter_converts(self):
        self.assertEqual(parse_quantity_detail("2本", "にんじん"), (300.0, "unit"))
        self.assertEqual(parse_quantity_detail("1丁", "豆腐"), (300.0, "unit"))
        self.assertEqual(parse_quantity_detail("1個", "卵"), (50.0, "unit"))

    def test_unknown_food_still_refuses(self):
        self.assertEqual(parse_quantity_detail("2本", "見たことのない野菜"), (None, None))
        self.assertEqual(parse_quantity_detail("3枚", "謎の葉"), (None, None))

    def test_fractions_are_not_read_as_counts(self):
        """「1/2本」 is half a burdock root, not two of them. Matching a bare
        number in front of the counter read the denominator and quadrupled
        the quantity."""
        self.assertEqual(parse_quantity_detail("1/2本", "ごぼう"), (75.0, "unit"))
        self.assertEqual(parse_quantity_detail("中1/2本", "にんじん"), (75.0, "unit"))
        self.assertEqual(parse_quantity_detail("1と1/2本", "ねぎ"), (150.0, "unit"))
        self.assertEqual(parse_quantity_detail("1/4個", "たまねぎ"), (50.0, "unit"))

    def test_longest_food_name_wins(self):
        """ミニトマト is 15 g, and must not be read as トマト at 150."""
        self.assertEqual(parse_quantity_detail("2個", "ミニトマト"), (30.0, "unit"))

    def test_cups(self):
        self.assertEqual(parse_quantity_detail("1カップ", "米"), (170.0, "unit"))
        self.assertEqual(parse_quantity_detail("1/2カップ", "水"), (100.0, "unit"))
        self.assertEqual(parse_quantity_detail("1カップ", "ごま"), (None, None))

    def test_stated_weights_are_not_assumptions(self):
        self.assertEqual(parse_quantity_detail("600g", "大根"), (600.0, "measure"))
        self.assertEqual(parse_quantity_detail("大さじ2", "しょうゆ"), (36.0, "measure"))

    def test_to_taste_still_has_no_quantity(self):
        for text in ("適量", "少々", "適宜", "お好みで"):
            self.assertEqual(parse_quantity_detail(text, "塩"), (None, None), text)


if __name__ == "__main__":
    unittest.main()
