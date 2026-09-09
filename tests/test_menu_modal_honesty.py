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

    def test_no_displayed_row_fails_the_reconciliation_rule(self):
        """Every row the site SHOWS must satisfy the rule the site applies.

        Checked across all 193 chain pages, using the production predicate
        rather than a second copy of the arithmetic — a test that reimplements
        the rule tests its own copy, and the first version of this one failed
        on 46 correct rows because it used naive 4/9/4 while production had
        moved on to counting fibre at 2 kcal and exempting ethanol.
        """
        import sqlite3
        conn = sqlite3.connect("data/metadata/site.db")
        conn.row_factory = sqlite3.Row
        fibre = {r["item_id"]: r["amount"] for r in conn.execute(
            "SELECT item_id, amount FROM nutrients WHERE code = 'FIB-'")}
        slugs = [r[0] for r in conn.execute(
            "SELECT slug FROM shop_pages WHERE lang = 'ja'")]
        conn.close()

        bad = []
        for slug in slugs:
            page = queries.get_shop_page("ja", slug)
            if not page:
                continue
            for row in queries.get_shop_page_data(page)["menu"]:
                if row.get("protein_g") is None:
                    continue          # suppressed or never stored; nothing shown
                if not queries._macros_reconcile(
                        row.get("kcal"), row["protein_g"], row["fat_g"],
                        row["carbs_g"], fibre.get(row.get("item_id")), row["name"]):
                    bad.append((slug, row["name"], row.get("kcal")))
        self.assertFalse(bad, f"{len(bad)} shown rows fail the rule: {bad[:5]}")

    def test_the_rule_counts_fibre_and_ethanol(self):
        """Naive 4/9/4 rejects 282 of 2,621 MEXT food pages, all of them
        correct: agar is 160 kcal against 330 implied because MEXT counts
        dietary fibre at about 2 kcal a gram. Spirits report no macros at all.
        """
        # agar-like: 80 g of carbohydrate that is nearly all fibre
        self.assertTrue(queries._macros_reconcile(160, 0.2, 0.1, 80.0, 74.0, "粉寒天"))
        # the same numbers without the fibre allowance do not reconcile
        self.assertFalse(queries._macros_reconcile(160, 0.2, 0.1, 80.0, 0.0, "粉寒天"))
        # a spirit: real calories, no macros to show for them
        self.assertTrue(queries._macros_reconcile(237, 0.0, 0.0, 0.0, 0.0, "ウオッカ"))

    def test_a_rounding_gap_on_a_tiny_serving_is_not_a_contradiction(self):
        """8 kcal of konnyaku against 14 implied is 75% and means nothing."""
        self.assertTrue(queries._macros_reconcile(8, 0.1, 0.0, 3.3, 2.2, "こんにゃく"))

    def test_a_real_contradiction_is_still_caught(self):
        """87.6 g of carbohydrate in a chicken meatball: the estimator matched
        ひじき and weighed it as the dried seaweed."""
        self.assertFalse(queries._macros_reconcile(
            270, 13.8, 4.8, 87.6, 0.0, "ひじき入り鶏つくね 2個"))


if __name__ == "__main__":
    unittest.main()
