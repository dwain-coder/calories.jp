"""Test for the new /menu and /menu/{slug} pages."""
import re
import sqlite3
import unittest
from fastapi.testclient import TestClient

from dataset_manager.api.database import DB_PATH
from dataset_manager.api.server import app

client = TestClient(app)


def _get_sample_shop():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT slug FROM shop_pages WHERE lang = 'ja' LIMIT 1").fetchone()
        return row["slug"] if row else None
    except Exception:
        return None
    finally:
        conn.close()


class TestMenuPages(unittest.TestCase):
    def test_menu_index_renders(self):
        r = client.get("/menu")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn("チェーン店メニュー", html)
        self.assertIn("AI TOOL", html)
        self.assertIn("chain-filter-input", html)
        self.assertIn("compliance-card", html)
        self.assertIn("chain-brand-badge", html)
        self.assertIn('"@type": "ItemList"', html)

    def test_menu_detail_renders(self):
        slug = _get_sample_shop()
        if not slug:
            raise unittest.SkipTest("No shop_pages in DB")
        r = client.get(f"/menu/{slug}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn("dish-filter-input", html)
        self.assertIn("order-tray", html)
        self.assertIn("order-tray-drawer", html)
        self.assertIn("compliance-card", html)
        self.assertIn("chain-header-badge", html)
        self.assertIn("dish-thumb-avatar", html)
        self.assertIn("tray-add-btn", html)
        self.assertIn("inline-analyzer-container", html)
        self.assertIn('"@type": "Restaurant"', html)

    def test_romaji_alias_sushiro(self):
        r = client.get("/menu/sushiro")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn("スシロー", html)
        self.assertIn("dish-filter-input", html)
        self.assertIn("order-tray", html)
        self.assertIn("order-tray-drawer", html)
        self.assertIn("compliance-card", html)

    def test_favicon_silenced(self):
        r = client.get("/favicon.ico")
        self.assertEqual(r.status_code, 204)

    def test_analyze_dish_endpoint(self):
        r = client.get("/api/analyze-dish?dish=中華そば&shop=幸楽苑")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("totals", data)
        self.assertGreater(data["totals"]["energy_kcal"], 200)
        self.assertIn("components", data)
        self.assertGreater(len(data["components"]), 0)

    def test_analyze_dish_set_meal(self):
        r = client.get("/api/analyze-dish?dish=%E5%91%B3%E3%82%88%E3%81%97%E4%B8%AD%E8%8F%AF%E3%81%9d%E3%81%B0%26%E5%8D%8A%E3%83%A9%E3%82%A4%E3%82%B9%E3%82%BB%E3%83%83%E3%83%88")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreater(data["totals"]["energy_kcal"], 400)




class TestOneUrlPerPage(unittest.TestCase):
    """/shops served the same 251 chains as /menu — same rows, same prices, a
    second address for one page."""

    def test_shops_index_redirects_permanently(self):
        r = client.get("/shops", follow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.headers["location"], "/menu")

    def test_shop_page_redirects_to_its_menu_page(self):
        r = client.get("/shops/くら寿司", follow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertIn("/menu/", r.headers["location"])

    def test_sitemap_lists_the_url_the_site_serves(self):
        """It listed /shops/... while /menu was in no sitemap at all."""
        body = client.get("/sitemap-shops-ja.xml").text
        self.assertIn("/menu/", body)
        self.assertNotIn("/shops/", body)
        self.assertIn("<loc>https://calories.jp/menu</loc>",
                      client.get("/sitemap-pages-ja.xml").text)


class TestWhatCountsAsARestaurant(unittest.TestCase):
    """`shops` is one row per MENU, so a restaurant that publishes lunch and
    dinner separately arrives twice, and some rows carry only a section name."""

    def test_a_section_name_is_not_a_shop(self):
        from dataset_manager.scripts.build_shops import is_a_restaurant
        for name in ("Lunch", "Restaurant", "本日のおすすめ", "ラーメン", "GRAND",
                     "キッズ", "季節限定 うどん", "台湾料理"):
            self.assertFalse(is_a_restaurant(name), name)

    def test_a_shop_with_a_section_in_its_name_keeps_its_page(self):
        """Guessing which half of 「萬作 おしながき」 is the restaurant is how you
        delete a real one."""
        from dataset_manager.scripts.build_shops import is_a_restaurant
        for name in ("萬作 おしながき", "大衆酒場 八銭 名物料理", "山頭火",
                     "美千味 春のおすすめ", "恵比寿 土鍋炊ごはん なかいよ 定食"):
            self.assertTrue(is_a_restaurant(name), name)

    def test_one_page_per_business(self):
        from dataset_manager.scripts.build_shops import pick_canonical
        rows = [{"id": 1, "name": "AZABUDAI HILLS CAFE", "item_count": 32},
                {"id": 2, "name": "AZABUDAI HILLS CAFE", "item_count": 26},
                {"id": 3, "name": "azabudai hills cafe", "item_count": 6},
                {"id": 4, "name": "Lunch", "item_count": 5},
                {"id": 5, "name": "一蘭", "item_count": 22}]
        keep = pick_canonical(rows)
        self.assertEqual(set(keep), {1, 5})          # biggest menu wins, section dropped

    def test_the_fuller_page_wins_not_the_longer_menu(self):
        """MOS BURGER lists 116 dishes with one sourced figure behind them;
        モスバーガー lists 106 with 81. Ranking on length published the emptier
        page and dropped the chain out of the index entirely."""
        from dataset_manager.scripts.build_shops import pick_canonical
        rows = [{"id": 1, "name": "MOS BURGER", "item_count": 116},
                {"id": 2, "name": "モスバーガー", "item_count": 106}]
        self.assertEqual(pick_canonical(rows, {1: 1, 2: 81}), {2: "モスバーガー"})

    def test_a_japanese_only_site_does_not_title_a_page_in_english(self):
        from dataset_manager.scripts.build_shops import pick_canonical
        rows = [{"id": 1, "name": "MOS BURGER", "item_count": 116},
                {"id": 2, "name": "モスバーガー", "item_count": 106}]
        self.assertEqual(list(pick_canonical(rows, {1: 90, 2: 10}).values()),
                         ["モスバーガー"])


class TestIndexGate(unittest.TestCase):
    """The gate counts calories the chain published or a composition table
    supplied. It does NOT count the tier-3 recipe estimates that fill most of
    the calorie column: those are chosen on one keyword from the dish name, so
    a 145g burger, a 110g burger and a 220g double all come out at 432.5 kcal.
    Counting them lifted the indexable pages from 3 to 96 and was reverted."""

    def test_a_recipe_estimate_is_not_a_sourced_figure(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            from dataset_manager.scripts import build_shops
            shop = conn.execute(
                """SELECT smi.shop_id FROM shop_menu_items smi
                   JOIN menu_item_nutrition min ON min.shop_menu_item_id = smi.id
                   WHERE min.provenance = 'mext_calc'
                   GROUP BY smi.shop_id
                   HAVING COUNT(*) > 20 LIMIT 1""").fetchone()
            if not shop:
                self.skipTest("no precomputed estimates in this database")
            stats = build_shops._shop_stats(
                conn, shop["shop_id"], build_shops._nutrition_items(conn))
            self.assertGreater(stats["shown"], stats["resolved"])
        finally:
            conn.close()

    def test_gate_wants_a_menu_with_prices_and_sourced_calories(self):
        from dataset_manager.scripts.build_shops import gate
        self.assertFalse(gate({"items": 10, "resolved": 10, "priced": 5})[0])   # too few
        self.assertFalse(gate({"items": 40, "resolved": 8, "priced": 5})[0])    # 20%
        self.assertFalse(gate({"items": 40, "resolved": 40, "priced": 0})[0])   # no price
        self.assertTrue(gate({"items": 40, "resolved": 20, "priced": 5})[0])    # 50%


class TestAssetCacheBusting(unittest.TestCase):
    """Cloudflare caches /static/site.css for four hours and the URL never
    changed, so the deployed mobile layout reached nobody: the live site kept
    serving a stylesheet 26 minutes older than the fix."""

    def test_every_stylesheet_and_script_carries_a_version(self):
        for path in ("/", "/menu", "/analyzer", "/meal-calculator"):
            html = client.get(path).text
            self.assertTrue(re.search(r"/static/site\.css\?v=[0-9a-f]{10}", html), path)
            self.assertNotIn('"/static/site.css"', html)
            self.assertFalse(re.search(r'"/static/[a-z_]+\.js"', html), path)

    def test_the_version_follows_the_file(self):
        from dataset_manager.site.router import asset
        self.assertNotEqual(asset("/static/site.css"), asset("/static/suggest.js"))
        self.assertRegex(asset("/static/site.css"), r"^/static/site\.css\?v=[0-9a-f]{10}$")

    def test_a_versioned_url_still_serves_the_file(self):
        r = client.get("/static/site.css?v=deadbeef12")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.content), 1000)
