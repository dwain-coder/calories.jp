"""The weight-change table as a page of its own.

A recipe is written in raw weights and a composition table in cooked ones. The
rate between them is the bridge, and it was reachable only one food at a time.
"""
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.server import app
from dataset_manager.site import queries

client = TestClient(app)


class TestCookingYieldPage(unittest.TestCase):
    def test_page_lists_every_published_rate(self):
        r = client.get("/cooking-yield")
        self.assertEqual(r.status_code, 200)
        rows = queries.cooking_yields("ja")
        self.assertEqual(r.text.count('class="yield-row"'), len(rows))
        self.assertGreater(len(rows), 400)

    def test_known_rates_match_the_published_table(self):
        """Spot values against MEXT's own 重量変化率表. Dried hijiki takes up
        water dramatically — the published rate is 870% — and dried noodles
        roughly double, which is the whole reason the table exists."""
        rows = [r for r in queries.cooking_yields("ja")]
        hijiki = [r["rate_percent"] for r in rows if "ほしひじき" in r["name"]]
        self.assertTrue(hijiki, "dried hijiki missing from the yield table")
        self.assertTrue(all(v >= 800 for v in hijiki), hijiki)

        udon = [r["rate_percent"] for r in rows
                if "うどん" in r["name"] and "ゆで" in (r["method"] or "")]
        self.assertTrue(udon, "boiled udon missing")
        self.assertTrue(all(v >= 150 for v in udon), udon)

    def test_calories_from_raw_weight_follow_the_rate(self):
        for r in queries.cooking_yields("ja"):
            if r["energy_kcal"] and r["from_raw_100g"]:
                self.assertAlmostEqual(
                    r["from_raw_100g"],
                    round(r["energy_kcal"] * r["rate_percent"] / 100, 0), places=0)

    def test_it_is_in_the_sitemap(self):
        self.assertIn("/cooking-yield</loc>", client.get("/sitemap-pages-ja.xml").text)


if __name__ == "__main__":
    unittest.main()
