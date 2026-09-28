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


class TestReferenceValues(unittest.TestCase):
    """食品表示基準 別表第十, as revised by 令和7年内閣府令第26号.

    The %-of-reference figures used the pre-2025 table — protein 81 g, fat
    62 g, salt 7.5 g, vitamin D 5.5 µg — while the claims above already used the
    revised 別表第十二, so one page measured against two editions of the law.
    """
    STATUTE = {"energy_kcal": 2200, "protein_g": 85, "fat_g": 70,
               "carbohydrate_g": 320, "salt_g": 7.0,
               "PROT-": 85, "FAT-": 70, "CHOCDF-": 320, "FIB-": 20,
               "CA": 700, "FE": 6.5, "K": 2800, "MG": 320, "ZN": 8.5,
               "VITC": 100, "VITA_RAE": 770, "VITD": 9.0, "VITB12": 4.0,
               "THIA": 1.0, "RIBF": 1.4, "FOL": 240}

    def test_every_table_uses_the_revised_values(self):
        from dataset_manager.site.cards import FINGERPRINT
        from dataset_manager.site.i18n import MACRO_DV, MICRO_DV
        used = dict(MACRO_DV["ja"])
        used.update({code: dv for code, (_label, dv, _unit) in MICRO_DV["ja"].items()})
        used.update({code: dv for code, _name, dv in FINGERPRINT})
        wrong = {k: v for k, v in used.items() if self.STATUTE.get(k) != v}
        self.assertEqual(wrong, {})

    def test_no_page_cites_the_old_edition(self):
        from dataset_manager.site.i18n import STRINGS
        old = [k for lang in STRINGS.values() for k, v in lang.items()
               if "表示基準値" in v and "2020" in v]
        self.assertEqual(old, [])


if __name__ == "__main__":
    unittest.main()
