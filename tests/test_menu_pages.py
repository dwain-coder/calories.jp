"""Test for the new /menu and /menu/{slug} pages."""
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


