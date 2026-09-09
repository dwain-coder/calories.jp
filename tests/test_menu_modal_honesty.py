"""Rule one: nothing the page shows may be incorrect.

The dish modal took its calories from the row and its macros from the AI
analyzer, then labelled the pair 店舗公式公表値. A ¥3,256 roast beef steak came
out as 552 kcal with 3.9 g of protein and 49.5 g of carbohydrate — figures that
do not reconcile with each other, are not what the site stores, and were not
published by anyone. 6,252 of 9,594 menu rows carried that label without being
chain-published.

These assert the template, because the defect was in the template's JavaScript
and no server-side test could see it.
"""
import re
import unittest
from pathlib import Path

from dataset_manager.site import queries

MENU = Path("templates/menu.html").read_text(encoding="utf-8")


class TestTheLabelStatesWhatTheValueIs(unittest.TestCase):

    def test_official_is_claimed_only_for_chain_published_figures(self):
        """店舗公式公表値 means the chain published it. Nothing else does."""
        self.assertIn("SOURCE_LABEL", MENU)
        official = re.search(r'chain:\s*"店舗公式公表値"', MENU)
        self.assertTrue(official, "chain must map to 店舗公式公表値")

    def test_the_old_unconditional_label_is_gone(self):
        """`published ? "店舗公式公表値" : ...` was the whole bug."""
        self.assertNotRegex(
            MENU, r'published\s*\?\s*"店舗公式公表値"',
            "the modal must not call any stored figure officially published")

    def test_an_estimate_is_named_as_an_estimate(self):
        for source, label in (("mext_calc", "推計値"), ("table", "成分表")):
            with self.subTest(source=source):
                self.assertRegex(MENU, rf'{source}:\s*"{label}')


class TestFiguresComeFromOneSource(unittest.TestCase):

    def test_macros_are_read_from_the_row_not_the_analyzer(self):
        """Stored calories beside AI macros is what produced 3.9g of protein."""
        self.assertIn("storedMacros", MENU)
        self.assertIn("hasStoredMacros", MENU)

    def test_the_contradicting_breakdown_is_suppressed(self):
        """The analyzer reads the dish NAME and can miss the main ingredient.

        Beside a figure it did not produce, that is not a second opinion, it is
        a contradiction — so the block is hidden rather than captioned.
        """
        self.assertIn("modal-ingredients-block", MENU)
        self.assertRegex(MENU, r"if \(useStored\)")


class TestTheDataItselfIsConsistent(unittest.TestCase):

    def test_no_page_shows_macros_that_contradict_its_calories(self):
        """4/9/4 against the stated energy, on EVERY chain page.

        Checked across all 193 rather than the one page the defect was spotted
        on. A row whose macros imply a different total than the calories beside
        them contains a wrong number, and the reader can see it.
        """
        import sqlite3
        conn = sqlite3.connect("data/metadata/site.db")
        slugs = [r[0] for r in conn.execute(
            "SELECT slug FROM shop_pages WHERE lang = 'ja'")]
        conn.close()
        bad = []
        for slug in slugs:
            page = queries.get_shop_page("ja", slug)
            if not page:
                continue
            for row in queries.get_shop_page_data(page)["menu"]:
                kcal, p, f, c = (row.get("kcal"), row.get("protein_g"),
                                 row.get("fat_g"), row.get("carbs_g"))
                if not kcal or None in (p, f, c):
                    continue
                implied = p * 4 + f * 9 + c * 4
                if abs(implied - kcal) / kcal > 0.30:
                    bad.append((slug, row["name"], kcal, round(implied)))
        self.assertFalse(bad, f"{len(bad)} rows contradict themselves: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
