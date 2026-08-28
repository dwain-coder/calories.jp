import unittest

from dataset_manager.site import groups
from dataset_manager.site.i18n import MEXT_GROUPS_EN
from dataset_manager.site.queries import pfc_energy_split


class TestGroupPalette(unittest.TestCase):
    def test_every_mext_group_has_colour_and_glyph(self):
        for ja in MEXT_GROUPS_EN:
            self.assertIn(ja, groups.GROUPS, f"{ja} missing from palette")
            hexv, emoji = groups.GROUPS[ja]
            self.assertRegex(hexv, r"^#[0-9A-Fa-f]{6}$")
            self.assertTrue(emoji)

    def test_colours_are_distinct(self):
        colours = [v[0] for v in groups.GROUPS.values()]
        self.assertEqual(len(set(colours)), len(colours))

    def test_unknown_group_falls_back(self):
        self.assertEqual(groups.color("not-a-group"), groups.DEFAULT_COLOR)
        self.assertEqual(groups.emoji("not-a-group"), "")


class TestPfcSplit(unittest.TestCase):
    """The atlas position is this split — pure fat, pure carb and pure protein
    foods must land exactly on the triangle's corners."""

    def test_pure_fat(self):
        s = pfc_energy_split({"protein_g": 0, "fat_g": 100, "carbohydrate_g": 0})
        self.assertEqual((s["p"], s["f"], s["c"]), (0, 100, 0))

    def test_pure_carb(self):
        s = pfc_energy_split({"protein_g": 0, "fat_g": 0, "carbohydrate_g": 100})
        self.assertEqual((s["p"], s["f"], s["c"]), (0, 0, 100))

    def test_atwater_weighting(self):
        # 10 g each -> 40/90/40 kcal. Fat carries 9 kcal/g against 4 for the
        # others, so it takes the majority share. Protein and carbohydrate are
        # equal before rounding; largest-remainder gives one of them the spare
        # unit, so they may differ by 1.
        s = pfc_energy_split({"protein_g": 10, "fat_g": 10, "carbohydrate_g": 10})
        self.assertEqual(s["f"], 53)
        self.assertLessEqual(abs(s["p"] - s["c"]), 1)
        self.assertEqual(s["p"] + s["f"] + s["c"], 100)

    def test_shares_sum_to_100(self):
        for macros in (
            {"protein_g": 23.3, "fat_g": 1.9, "carbohydrate_g": 0.1},
            {"protein_g": 2.6, "fat_g": 0.4, "carbohydrate_g": 21.6},
            {"protein_g": 6.1, "fat_g": 0.6, "carbohydrate_g": 56.8},
        ):
            s = pfc_energy_split(macros)
            self.assertEqual(s["p"] + s["f"] + s["c"], 100)

    def test_zero_energy_has_no_position(self):
        self.assertIsNone(pfc_energy_split({"protein_g": 0, "fat_g": 0, "carbohydrate_g": 0}))
        self.assertIsNone(pfc_energy_split(None))


if __name__ == "__main__":
    unittest.main()
