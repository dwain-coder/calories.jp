import unittest

from dataset_manager.calc.nutrition import (
    dish_nutrition, meal_insights, scale, sum_components, to_grams,
)


class TestMealInsights(unittest.TestCase):
    DV = {"energy_kcal": 2200, "salt_g": 7.5}

    def test_salty_heavy_meal(self):
        totals = {"energy_kcal": 1185, "protein_g": 38, "fat_g": 63, "carbohydrate_g": 108}
        keys = [k for _, k, _ in meal_insights(totals, salt_g=6.0, dv=self.DV)]
        self.assertIn("ins_salt_high", keys)
        self.assertIn("ins_kcal_high", keys)
        self.assertIn("ins_fat_high", keys)

    def test_lean_meal(self):
        totals = {"energy_kcal": 400, "protein_g": 40, "fat_g": 8, "carbohydrate_g": 40}
        results = meal_insights(totals, salt_g=1.0, fiber_g=7, dv=self.DV)
        keys = [k for _, k, _ in results]
        self.assertIn("ins_protein_good", keys)
        self.assertIn("ins_fiber_good", keys)
        self.assertNotIn("ins_salt_high", keys)
        self.assertTrue(all(level in ("good", "warn") for level, _, _ in results))

    def test_empty(self):
        self.assertEqual(meal_insights({}, dv=self.DV), [])


class TestToGrams(unittest.TestCase):
    def test_exact_factors(self):
        self.assertEqual(to_grams(1, "g"), 1.0)
        self.assertEqual(to_grams(2, "kg"), 2000.0)
        self.assertEqual(to_grams(500, "mg"), 0.5)
        self.assertEqual(to_grams(1, "oz"), 28.349523125)
        self.assertEqual(to_grams(1, "lb"), 453.59237)

    def test_lb_oz_relationship(self):
        self.assertAlmostEqual(to_grams(16, "oz"), to_grams(1, "lb"), places=9)

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            to_grams(1, "cup")

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            to_grams(-5, "g")


class TestScale(unittest.TestCase):
    PER100 = {"energy_kcal": 165.0, "protein_g": 31.0, "fat_g": 3.6, "carbohydrate_g": 0.0}

    def test_100_to_200(self):
        r = scale(self.PER100, 200)
        self.assertEqual(r["energy_kcal"], 330.0)
        self.assertEqual(r["protein_g"], 62.0)

    def test_100_to_150(self):
        r = scale(self.PER100, 150)
        self.assertAlmostEqual(r["energy_kcal"], 247.5)
        self.assertAlmostEqual(r["fat_g"], 5.4)

    def test_full_precision(self):
        r = scale({"energy_kcal": 123.4}, 33)
        self.assertAlmostEqual(r["energy_kcal"], 40.722, places=9)

    def test_none_passthrough(self):
        r = scale({"energy_kcal": 100.0, "protein_g": None}, 50)
        self.assertEqual(r["energy_kcal"], 50.0)
        self.assertIsNone(r["protein_g"])


class TestSumComponents(unittest.TestCase):
    def test_multiple_ingredients(self):
        totals, missing = sum_components([
            {"energy_kcal": 248.0, "protein_g": 46.5},
            {"energy_kcal": 312.0, "protein_g": 5.0},
            {"energy_kcal": 92.1, "protein_g": 0.0},
        ])
        self.assertAlmostEqual(totals["energy_kcal"], 652.1)
        self.assertAlmostEqual(totals["protein_g"], 51.5)
        self.assertEqual(missing, {})

    def test_missing_flagged_not_zeroed(self):
        totals, missing = sum_components([
            {"energy_kcal": 100.0, "fat_g": None},
            {"energy_kcal": 50.0, "fat_g": 2.0},
        ])
        self.assertEqual(totals["fat_g"], 2.0)
        self.assertEqual(missing["fat_g"], 1)


class TestDishNutrition(unittest.TestCase):
    NUT = {
        1: {"energy_kcal": 100.0, "protein_g": 10.0, "fat_g": 1.0, "carbohydrate_g": 5.0},
        2: {"energy_kcal": 200.0, "protein_g": 0.0, "fat_g": 20.0, "carbohydrate_g": 0.0},
    }

    def test_totals_and_coverage(self):
        links = [
            {"grams": 100, "mext_item_id": 1},
            {"grams": 50, "mext_item_id": 2},
            {"grams": None, "mext_item_id": 1},   # unquantified
            {"grams": 30, "mext_item_id": None},  # unresolved
        ]
        r = dish_nutrition(links, self.NUT)
        self.assertEqual(r["n_total"], 4)
        self.assertEqual(r["n_resolved"], 2)
        self.assertEqual(r["grams_resolved"], 150.0)
        self.assertAlmostEqual(r["totals"]["energy_kcal"], 200.0)  # 100 + 200*0.5
        self.assertAlmostEqual(r["totals"]["fat_g"], 11.0)

    def test_empty(self):
        r = dish_nutrition([], {})
        self.assertEqual(r["n_total"], 0)
        self.assertEqual(r["totals"], {})


if __name__ == "__main__":
    unittest.main()
