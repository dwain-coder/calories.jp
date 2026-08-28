"""Route tests against the real repo DB (read-only). Run from the repo root.

Site-page assertions are skipped until `build-pages` has been run; the legacy
endpoint regressions always run.
"""
import sqlite3
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.database import DB_PATH
from dataset_manager.api.server import app

client = TestClient(app)


def _one(sql, *params):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def _has_pages():
    try:
        return _one("SELECT COUNT(*) c FROM site_pages")["c"] > 0
    except sqlite3.OperationalError:
        return False


class TestLegacyEndpointsUnchanged(unittest.TestCase):
    def test_root_still_json_stats(self):
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("total_items", r.json())

    def test_items_list(self):
        r = client.get("/items?source=MEXT Standard Tables&size=2")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("items", data)
        self.assertGreater(data["total"], 0)

    def test_item_detail_shape(self):
        row = _one("SELECT id FROM items WHERE source='MEXT Standard Tables' LIMIT 1")
        r = client.get(f"/items/{row['id']}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ("nutrition", "nutrients", "license"):
            self.assertIn(key, body)


class TestSitePages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _has_pages():
            raise unittest.SkipTest("site_pages not built yet (run build-pages)")

    def test_home_renders(self):
        r = client.get("/ja/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])

    def test_english_is_gone(self):
        """Single-language site: /en/ must not resolve, and no page should
        offer a language switch."""
        for url in ("/en/", "/en/foods", "/en/goals"):
            self.assertEqual(client.get(url).status_code, 404, url)
        self.assertNotIn("lang-switch", client.get("/ja/").text)

    def test_bad_lang_404(self):
        self.assertEqual(client.get("/fr/").status_code, 404)

    def test_unknown_slug_404(self):
        self.assertEqual(client.get("/ja/food/definitely-not-a-real-slug-xyz").status_code, 404)

    def test_food_page_seo(self):
        row = _one(
            "SELECT slug FROM site_pages WHERE lang='ja' AND page_type='food' LIMIT 1")
        r = client.get(f"/ja/food/{row['slug']}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn('rel="canonical"', html)
        self.assertIn("application/ld+json", html)
        self.assertIn("nutrition-data", html)  # calculator payload present

    def test_ja_food_page(self):
        row = _one(
            "SELECT slug FROM site_pages WHERE lang='ja' AND page_type='food' LIMIT 1")
        r = client.get(f"/ja/food/{row['slug']}")
        self.assertEqual(r.status_code, 200)
        self.assertIn('lang="ja"', r.text)

    def test_search_html(self):
        r = client.get("/ja/search?q=みそ")
        self.assertEqual(r.status_code, 200)

    def test_api_search(self):
        r = client.get("/api/search?q=にわとり&lang=ja")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_api_nutrition_gate(self):
        # An OpenFoodFacts item id must 404 (no site page -> structurally excluded).
        row = _one("SELECT id FROM items WHERE source='OpenFoodFacts' LIMIT 1")
        if row:
            self.assertEqual(client.get(f"/api/foods/{row['id']}/nutrition").status_code, 404)

    def test_category_page_ja(self):
        r = client.get("/ja/category/肉類")
        self.assertEqual(r.status_code, 200)
        self.assertIn("sortable", r.text)

    def test_category_page_unknown_404(self):
        self.assertEqual(client.get("/ja/category/not-a-category").status_code, 404)

    def test_goals_page(self):
        r = client.get("/ja/goals")
        self.assertEqual(r.status_code, 200)
        self.assertIn("g-target", r.text)

    def test_browse_page_paginates(self):
        r = client.get("/ja/foods")
        self.assertEqual(r.status_code, 200)
        r2 = client.get("/ja/foods?page=2&sort=kcal_desc")
        self.assertEqual(r2.status_code, 200)
        self.assertIn("noindex", r2.text)  # paginated pages are not indexed
        self.assertNotEqual(r.text, r2.text)

    def test_food_page_has_faq_and_dv(self):
        row = _one(
            """SELECT sp.slug FROM site_pages sp JOIN nutrition n ON n.item_id = sp.item_id
               WHERE sp.lang='ja' AND sp.page_type='food' AND n.energy_kcal IS NOT NULL LIMIT 1""")
        html = client.get(f"/ja/food/{row['slug']}").text
        self.assertIn("FAQPage", html)
        self.assertIn('data-dv="protein_g"', html)

    def test_prep_variants_render(self):
        # うどん has 生 / ゆで rows in MEXT; the page must link its siblings.
        row = _one(
            """SELECT sp.slug FROM site_pages sp JOIN item_names nm
                 ON nm.item_id = sp.item_id AND nm.lang='ja' AND nm.is_primary=1
               WHERE sp.lang='ja' AND nm.name LIKE '%うどん ゆで' LIMIT 1""")
        if row:
            html = client.get(f"/ja/food/{row['slug']}").text
            self.assertIn("調理法によるカロリーの違い", html)

    def test_stock_imagery_never_on_data_pages(self):
        """Photographs belong on landing pages, not beside measurements."""
        food = _one("SELECT slug FROM site_pages WHERE lang='ja' AND page_type='food' LIMIT 1")
        dish = _one("SELECT slug FROM site_pages WHERE lang='ja' AND page_type='dish' LIMIT 1")
        for url in (f"/ja/food/{food['slug']}", f"/ja/dish/{dish['slug']}",
                    "/ja/foods", "/ja/category/肉類"):
            self.assertNotIn("framed-media", client.get(url).text, url)

    def test_media_absent_renders_nothing(self):
        """A missing image degrades to nothing, never a broken box."""
        from dataset_manager.site import media
        slots = {"/ja/": "home-hero", "/ja/meal-calculator": "meal-calculator",
                 "/ja/goals": "goals", "/ja/sources": "sources"}
        for url, slot in slots.items():
            r = client.get(url)
            self.assertEqual(r.status_code, 200)
            present = media.get(slot, "ja") is not None
            self.assertEqual("framed-media" in r.text, present, f"{url} ({slot})")

    def test_video_renders_and_never_on_data_pages(self):
        from dataset_manager.site import media
        # A configured, present video renders in place of the still.
        for slot, url in (("analyzer", "/ja/analyzer"), ("goals", "/ja/goals")):
            v = media.video(slot, "ja")
            html = client.get(url).text
            if v and v["kind"] == "file":
                self.assertIn("<video", html, slot)
                self.assertNotIn("autoplay", html)   # ambient.js honours reduced motion
            elif v and v["kind"] == "embed":
                self.assertIn("<iframe", html, slot)
            else:
                self.assertNotIn("<video", html, slot)
        food = _one("SELECT slug FROM site_pages WHERE lang='ja' AND page_type='food' LIMIT 1")
        self.assertNotIn("<video", client.get(f"/ja/food/{food['slug']}").text)

    def test_video_missing_file_is_silent(self):
        from dataset_manager.site import media
        media.VIDEO["__probe__"] = {"file": "does-not-exist.mp4"}
        try:
            self.assertIsNone(media.video("__probe__", "ja"))
        finally:
            media.VIDEO.pop("__probe__", None)

    def test_media_get_matches_file_presence(self):
        from dataset_manager.site import media
        for slot, m in media.MEDIA.items():
            self.assertEqual(media.get(slot, "ja") is not None, media._exists(m["file"]), slot)

    def test_atlas_plots_corpus(self):
        from dataset_manager.site import queries
        ja = queries.atlas_points("ja")
        self.assertGreater(len(ja["p"]), 2000)
        self.assertTrue(all(s.startswith("ja/") for s in ja["slugs"]))

    def test_atlas_groups_localised(self):
        ja = client.get("/api/atlas?lang=ja").json()
        self.assertIn("肉類", ja["groups"])

    def test_atlas_rejects_dropped_language(self):
        self.assertEqual(client.get("/api/atlas?lang=en").status_code, 400)

    def test_guide_cooking(self):
        r = client.get("/ja/guides/cooking-and-calories")
        self.assertEqual(r.status_code, 200)
        self.assertIn("guide-ratio", r.text)

    def test_food_page_has_generated_imagery(self):
        row = _one(
            """SELECT sp.slug FROM site_pages sp
               JOIN items i ON i.id = sp.item_id AND i.source='MEXT Standard Tables'
               WHERE sp.lang='ja' AND sp.page_type='food' LIMIT 1""")
        html = client.get(f"/ja/food/{row['slug']}").text
        self.assertIn('class="fingerprint"', html)   # per-food nutrient portrait
        self.assertIn('class="pfc-donut"', html)

    def test_analyzer_rate_limit_headers(self):
        from dataset_manager.api import analyzer
        analyzer._hits.clear()
        try:
            for _ in range(analyzer.RATE_LIMIT):
                analyzer._rate_limit("1.2.3.4")
            with self.assertRaises(Exception) as cm:
                analyzer._rate_limit("1.2.3.4")
            self.assertEqual(getattr(cm.exception, "status_code", None), 429)
            analyzer._rate_limit("5.6.7.8")          # a different caller is unaffected
        finally:
            analyzer._hits.clear()

    def test_robots_and_sitemap_index(self):
        r = client.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Sitemap:", r.text)
        self.assertEqual(client.get("/sitemap.xml").status_code, 200)


if __name__ == "__main__":
    unittest.main()
