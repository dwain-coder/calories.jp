import unittest

from dataset_manager.calc.quantities import parse_quantity, parse_recipe_lines


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

    def test_counts_none(self):
        self.assertIsNone(parse_quantity("2本", name="大根"))
        self.assertIsNone(parse_quantity("1個", name="玉ねぎ"))

    def test_empty_none(self):
        self.assertIsNone(parse_quantity(""))
        self.assertIsNone(parse_quantity(None))


class TestParseRecipeLines(unittest.TestCase):
    def test_tab_separated(self):
        blob = "もち米粉\t195g\nぬるま湯\t150ml\n三つ葉\t適量"
        rows = parse_recipe_lines(blob)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], (0, "もち米粉", "195g", 195.0))
        self.assertEqual(rows[1][3], 150.0)  # 湯 on liquid allowlist
        self.assertIsNone(rows[2][3])

    def test_space_separated_fallback(self):
        rows = parse_recipe_lines("大根 600g")
        self.assertEqual(rows[0][1], "大根")
        self.assertEqual(rows[0][3], 600.0)

    def test_empty(self):
        self.assertEqual(parse_recipe_lines(None), [])
        self.assertEqual(parse_recipe_lines(""), [])


if __name__ == "__main__":
    unittest.main()
