"""A dish total computed from some of the ingredients is a lower bound.

738 dish pages show nutrition, and 660 of them compute it from an incomplete
ingredient set — MAFF recipes name things the composition tables do not match.
The page footnoted that, and then printed the numbers as though they were the
dish: 37 pages claimed exactly 0.0 g of fat on more than 300 kcal, every one a
simmered or preserved fish whose fish had not resolved.

0.0 g is a claim. An absence is not.
"""
import sqlite3
import unittest
import urllib.parse

from fastapi.testclient import TestClient

from dataset_manager.api.server import app
from dataset_manager.site import queries

client = TestClient(app)


def a_partial_dish():
    conn = sqlite3.connect("data/metadata/site.db")
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute(
                "SELECT * FROM site_pages WHERE lang='ja' AND page_type='dish'"):
            data = queries.get_dish_page_data(dict(row))
            if not data or not data.get("show_nutrition"):
                continue
            computed = data.get("computed") or {}
            if computed.get("n_resolved", 0) < computed.get("n_total", 0):
                return row["slug"], computed
    finally:
        conn.close()
    return None, None


class TestPartialTotalsAreMarked(unittest.TestCase):

    def test_a_partial_total_is_shown_as_a_lower_bound(self):
        slug, computed = a_partial_dish()
        if not slug:
            self.skipTest("no partial dish in this extract")
        html = client.get("/dish/" + urllib.parse.quote(slug)).text
        self.assertIn("≥", html,
                      "a total from some of the ingredients must carry ≥")

    def test_a_zero_under_partial_coverage_reads_as_absent(self):
        """0.0 g of fat asserts the dish has none. It did not resolve."""
        slug, computed = a_partial_dish()
        if not slug:
            self.skipTest("no partial dish in this extract")
        zero = [k for k, v in (computed.get("totals") or {}).items() if v == 0.0]
        if not zero:
            self.skipTest("this dish has no zeroed macro")
        html = client.get("/dish/" + urllib.parse.quote(slug)).text
        self.assertNotIn("<td>0.0 g</td>", html)

    def test_the_ratio_bar_is_withheld_when_the_recipe_is_incomplete(self):
        """96% carbohydrate and 0% fat is a picture of what matched, not of
        the dish, and would contradict the ≥ and — in the table."""
        slug, _ = a_partial_dish()
        if not slug:
            self.skipTest("no partial dish in this extract")
        html = client.get("/dish/" + urllib.parse.quote(slug)).text
        self.assertNotIn("pfc-bar", html)


if __name__ == "__main__":
    unittest.main()
