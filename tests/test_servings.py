"""Servings: a convention, matched carefully or not at all."""
import unittest

from dataset_manager.site.servings import SERVINGS, for_food, scale


class TestServings(unittest.TestCase):
    def test_known_staples(self):
        self.assertEqual(for_food("こめ 水稲めし 精白米 うるち米"),
                         {"label": "茶碗1杯", "grams": 150.0})
        self.assertEqual(for_food("鶏卵 全卵 生")["grams"], 50.0)

    def test_uncooked_grain_has_no_serving(self):
        """A bowl of rice is a serving; 150 g of dry grain is not a thing
        anyone eats, and the two rows are 342 and 156 kcal."""
        self.assertIsNone(for_food("こめ 水稲穀粒 精白米 うるち米"))

    def test_derived_forms_do_not_inherit_the_serving(self):
        """「いちご」 is five berries. Jam, dried and preserved forms are not,
        and matching on the substring alone claimed all of them."""
        self.assertIsNotNone(for_food("いちご 生"))
        for name in ("いちご ジャム 低糖度", "いちご 乾", "うし 乳用肥育牛肉 かた 脂身 生"):
            self.assertIsNone(for_food(name), name)
        # an ordinary cut still passes: 脂身つき is not 脂身
        self.assertIsNotNone(for_food("うし 乳用肥育牛肉 かた 脂身つき 生"))

    def test_single_word_keys_match_whole_tokens(self):
        """もち must not claim うぐいすもち, which is a confection."""
        self.assertIsNotNone(for_food("もち"))
        for name in ("うぐいすもち こしあん入り", "あわ あわもち"):
            self.assertIsNone(for_food(name), name)

    def test_unknown_food_gets_nothing(self):
        self.assertIsNone(for_food("うし 副生物 第一胃 ゆで"))
        self.assertIsNone(for_food(""))

    def test_scaling_is_the_same_arithmetic_as_everywhere_else(self):
        out = scale({"energy_kcal": 156.0, "protein_g": 2.5}, 150.0)
        self.assertAlmostEqual(out["energy_kcal"], 234.0)
        self.assertAlmostEqual(out["protein_g"], 3.75)
        self.assertIsNone(scale(None, 150))

    def test_every_serving_is_a_positive_weight_with_a_label(self):
        for key, (label, grams) in SERVINGS.items():
            self.assertTrue(label.strip(), key)
            self.assertGreater(grams, 0, key)
            self.assertLess(grams, 1000, key)


if __name__ == "__main__":
    unittest.main()
