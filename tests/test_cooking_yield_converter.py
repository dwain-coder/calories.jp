"""The raw↔cooked converter, and the one row it must not get wrong.

MEXT's 重量変化率 is a percentage of the 調理前 food. That is the raw or dried
entry for 496 of its 497 rows — and the BOILED pasta for
マカロニ・スパゲッティ ソテー, whose rate is therefore 100%. A converter that read
every rate as against the raw food would offer 100 g of dry spaghetti becoming
100 g of sautéed spaghetti, which is out by a factor of 2.2.
"""
import re
import unittest
from pathlib import Path

from dataset_manager.site import queries

PAGE = Path("templates/cooking_yield.html").read_text(encoding="utf-8")


class TestTheRatesThemselves(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = queries.cooking_yields("ja")
        cls.by_name = {r["name"]: r for r in cls.rows}

    def test_every_published_rate_is_present(self):
        self.assertEqual(len(self.rows), 497)

    def test_the_one_row_measured_against_a_cooked_weight_says_so(self):
        row = self.by_name["こむぎ マカロニ・スパゲッティ ソテー"]
        self.assertEqual(row["base"], "ゆで")
        self.assertIsNone(row["before"],
                          "a rate against the boiled weight must name no raw food")

    def test_no_other_row_claims_a_cooked_base(self):
        flagged = [r["name"] for r in self.rows if r["base"]]
        self.assertEqual(flagged, ["こむぎ マカロニ・スパゲッティ ソテー"])

    def test_the_food_before_cooking_is_named_only_when_it_is_unambiguous(self):
        """まいたけ publishes both 生 and 乾 and the name does not say which one
        油いため started from, so that row names nothing."""
        self.assertIsNone(self.by_name["まいたけ 油いため"]["before"])
        chicken = self.by_name["にわとり 若どり もも 皮つき 焼き"]
        self.assertEqual(chicken["before"]["name"], "にわとり 若どり もも 皮つき 生")

    def test_a_named_raw_food_is_a_real_page(self):
        named = [r for r in self.rows if r["before"]]
        self.assertGreater(len(named), 300)
        self.assertTrue(all(r["before"]["slug"] for r in named))

    def test_known_pairs_come_out_as_MEXT_prints_them(self):
        """Anchors, checked against the published table by hand. A rate joined
        to the wrong food is the failure this guards, and no arithmetic
        invariant can catch it: frying adds batter and oil, boiling a dried
        food leaches starch, so energy is not conserved across a rate and a
        round-trip check rejects 40 correct rows.
        """
        for cooked, raw, rate in (
                ("こむぎ うどん ゆで", "こむぎ うどん 生", 180),
                ("にわとり 若どり もも 皮つき 焼き", "にわとり 若どり もも 皮つき 生", 61),
                ("ひじき ほしひじき ステンレス釜 油いため",
                 "ひじき ほしひじき ステンレス釜 乾", 870)):
            with self.subTest(cooked):
                row = self.by_name[cooked]
                self.assertEqual(row["rate_percent"], rate)
                self.assertEqual(row["before"]["name"], raw)

    def test_a_named_food_differs_from_the_cooked_one_only_by_its_state(self):
        for r in self.rows:
            if not r["before"]:
                continue
            stem = " ".join(r["name"].split()[:-1])
            self.assertIn(r["before"]["name"], (stem + " 生", stem + " 乾"),
                          f"{r['name']} was paired with {r['before']['name']}")

class TestTheConverter(unittest.TestCase):

    def test_both_directions_are_offered(self):
        self.assertIn('name="yield-dir" value="forward"', PAGE)
        self.assertIn('name="yield-dir" value="back"', PAGE)

    def test_the_reverse_is_the_same_rate_inverted(self):
        self.assertIn('var raw = dir === "forward" ? g : g * 100 / rate;', PAGE)
        self.assertIn('var cooked = dir === "forward" ? g * rate / 100 : g;', PAGE)

    def test_energy_before_cooking_is_shown_only_when_it_is_published(self):
        """No raw sibling means no data-before-kcal, and the line is skipped
        rather than filled from the cooked figure."""
        self.assertIn("data-before-kcal", PAGE)
        self.assertIn("if (!isNaN(beforeKcal))", PAGE)


if __name__ == "__main__":
    unittest.main()
