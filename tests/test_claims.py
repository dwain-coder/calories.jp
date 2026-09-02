"""食品表示基準 別表第十二 — the law's thresholds, not ours."""
import unittest

from dataset_manager.site.claims import THRESHOLDS, claims_for, is_liquid


def rows(**kw):
    return [{"code": c, "amount": v, "quality": "measured"} for c, v in kw.items()]


class TestClaims(unittest.TestCase):
    def test_thresholds_match_the_statute(self):
        """Transcribed from the e-Gov XML of 食品表示基準, not from memory:
        protein is 17.0 g/100 g, and recollection offered 16.2."""
        self.assertEqual(THRESHOLDS["PROT-"][1], 17.0)
        self.assertEqual(THRESHOLDS["PROT-"][3], 8.5)
        self.assertEqual(THRESHOLDS["FIB-"][1], 6.0)
        self.assertEqual(THRESHOLDS["VITC"][1], 30.0)
        self.assertEqual(THRESHOLDS["CA"][1], 210.0)

    def test_high_and_source_levels(self):
        out = {c["code"]: c["level"] for c in claims_for(rows(**{"PROT-": 22.3, "FIB-": 3.5}))}
        self.assertEqual(out["PROT-"], "high")      # 22.3 >= 17.0
        self.assertEqual(out["FIB-"], "source")     # 3.5 is over 3.0, under 6.0

    def test_below_the_criterion_says_nothing(self):
        self.assertEqual(claims_for(rows(**{"PROT-": 8.0})), [])

    def test_drinks_use_the_liquid_column(self):
        """The statute sets a lower bar for 一般に飲用に供する液状 food, because
        nobody drinks 100 g of a beverage as a meal."""
        milk = rows(**{"PROT-": 9.0})
        self.assertEqual(claims_for(milk, "し好飲料類")[0]["level"], "high")   # >= 8.5
        self.assertEqual(claims_for(milk, "魚介類")[0]["level"], "source")     # < 17.0
        self.assertTrue(is_liquid("し好飲料類"))

    def test_estimated_values_make_no_claim(self):
        """A claim is about what the food contains, and MEXT's estimate for a
        food is not a measurement of it."""
        est = [{"code": "PROT-", "amount": 22.3, "quality": "estimated"}]
        self.assertEqual(claims_for(est), [])

    def test_strongest_first(self):
        out = claims_for(rows(**{"PROT-": 17.5, "VITC": 300.0}))
        self.assertEqual(out[0]["code"], "VITC")    # 10x its threshold


if __name__ == "__main__":
    unittest.main()
