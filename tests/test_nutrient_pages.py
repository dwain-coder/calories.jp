"""Ranking pages: foods ordered by one measured component.

A ranking is a claim that THIS food holds more than THAT one, so what it may
be built from is narrower than what a food page may print.
"""
import re
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.server import app
from dataset_manager.site import nutrient_pages, queries

client = TestClient(app)


class TestRankingContent(unittest.TestCase):
    def test_index_lists_every_nutrient_that_has_a_page(self):
        html = client.get("/nutrients").text
        for _code, slug, _term, _blurb in nutrient_pages.NUTRIENTS:
            self.assertIn(f'/nutrient/{slug}"', html, slug)

    def test_a_ranking_page_renders_in_order(self):
        r = client.get("/nutrient/dha")
        self.assertEqual(r.status_code, 200)
        rows = queries.nutrient_ranking("ja", "F22D6N3", limit=20)
        self.assertGreater(len(rows), 10)
        amounts = [x["amount"] for x in rows]
        self.assertEqual(amounts, sorted(amounts, reverse=True))

    def test_an_unknown_nutrient_is_404(self):
        self.assertEqual(client.get("/nutrient/unobtainium").status_code, 404)

    def test_every_curated_code_actually_has_data(self):
        """A page that renders an empty table is worse than no page."""
        for code, slug, term, _blurb in nutrient_pages.NUTRIENTS:
            stats = queries.nutrient_corpus_stats("ja", code)
            self.assertTrue(stats and stats.get("n"), f"{slug} ({code}) has no measured values")
            self.assertGreaterEqual(stats["n"], 20, f"{slug} ranks over only {stats['n']} foods")


class TestOnlyMeasuredValuesAreRanked(unittest.TestCase):
    def test_estimates_and_traces_are_excluded(self):
        """MEXT prints its own estimates in parentheses and Tr for a trace.
        Neither can settle which of two foods holds more."""
        conn = queries.get_connection()
        try:
            ranked = {r["slug"] for r in queries.nutrient_ranking("ja", "VITC", limit=500)}
            estimated = {
                r[0] for r in conn.execute(
                    """SELECT sp.slug FROM nutrients n
                       JOIN site_pages sp ON sp.item_id = n.item_id AND sp.lang = 'ja'
                       WHERE n.code = 'VITC' AND n.quality != 'measured'""")
            }
        finally:
            conn.close()
        self.assertFalse(ranked & estimated)

    def test_the_scope_is_stated_on_the_page(self):
        """「2,504食品中」 is the difference between a fact and a listicle."""
        html = client.get("/nutrient/vitamin-c").text
        stats = queries.nutrient_corpus_stats("ja", "VITC")
        self.assertIn("{:,}".format(stats["n"]), html)


class TestDiscoverable(unittest.TestCase):
    def test_pages_are_in_the_sitemap(self):
        body = client.get("/sitemap-nutrients-ja.xml").text
        self.assertEqual(len(re.findall(r"<loc>", body)), len(nutrient_pages.SLUGS))
        self.assertIn("/nutrients</loc>", client.get("/sitemap-pages-ja.xml").text)

    def test_the_header_links_to_them(self):
        """A page reachable only from the sitemap is a page nobody reads."""
        self.assertIn('href="/nutrients"', client.get("/").text)

    def test_a_ranking_carries_its_list_markup(self):
        html = client.get("/nutrient/iron").text
        self.assertIn('"@type": "ItemList"', html)
        self.assertIn("ItemListOrderDescending", html)


if __name__ == "__main__":
    unittest.main()
