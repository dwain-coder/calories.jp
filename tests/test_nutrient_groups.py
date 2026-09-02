"""Filing 170 components into the sections a Japanese label reads in."""
import unittest

from dataset_manager.site.nutrient_groups import GROUPS, group_of, grouped


class TestGrouping(unittest.TestCase):
    def test_prefix_rules_do_not_swallow_their_neighbours(self):
        """The fatty acids are matched by an F prefix, and iron, folate and
        fibre all start with F too."""
        self.assertEqual(group_of("FE"), "minerals")       # iron
        self.assertEqual(group_of("FOL"), "vitamins")      # folate
        self.assertEqual(group_of("FIBSOL"), "fibre")
        self.assertEqual(group_of("F16D0"), "fats")
        self.assertEqual(group_of("FASAT"), "fats")

    def test_unknown_codes_are_shown_not_dropped(self):
        """A component MEXT adds in a later edition must still appear."""
        self.assertEqual(group_of("SOMETHING_NEW"), "basics")
        self.assertEqual(group_of(None), "basics")

    def test_every_component_lands_somewhere(self):
        rows = [{"code": c} for _k, _ja, _en, codes, _p in GROUPS for c in codes]
        out = grouped(rows)
        self.assertEqual(sum(len(r) for _k, _l, r in out), len(rows))

    def test_sections_come_back_in_reading_order(self):
        rows = [{"code": "ILE"}, {"code": "NA"}, {"code": "ENERC_KCAL"}]
        keys = [k for k, _l, _r in grouped(rows)]
        self.assertEqual(keys, ["basics", "minerals", "amino"])

    def test_empty_sections_are_omitted(self):
        self.assertEqual([k for k, _l, _r in grouped([{"code": "NA"}])], ["minerals"])


if __name__ == "__main__":
    unittest.main()
