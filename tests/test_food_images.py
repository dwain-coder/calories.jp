"""Tests for food images across restaurant menus and site favicon."""
import unittest
import sqlite3
from fastapi.testclient import TestClient

from dataset_manager.api.database import DB_PATH
from dataset_manager.api.server import app
from dataset_manager.site.food_images import get_dish_image, DISH_PHOTO_CATALOG
from dataset_manager.site import queries

client = TestClient(app)


class TestFoodImages(unittest.TestCase):
    def test_dish_image_resolution_categories(self):
        cases = [
            ("モスバーガー", "ハンバーガー"),
            ("モスチーズバーガー", "チーズバーガー"),
            ("テリヤキチキンバーガー", "チキンバーガー"),
            ("海老カツバーガー", "海老・フィッシュバーガー"),
            ("フレンチフライポテト", "ポテト・フライ"),
            ("オニオンフライ", "オニオンフライ"),
            ("ふんわりスフレパンケーキ", "パンケーキ・スフレ"),
            ("サーモン", "サーモン寿司"),
            ("まぐろ", "まぐろ寿司"),
            ("牛丼", "牛丼・肉料理"),
            ("豚骨ラーメン", "豚骨ラーメン"),
            ("ざるそば", "そば"),
            ("マルゲリータピザ", "ピザ"),
            ("カルボナーラ", "パスタ"),
            ("ブレンドコーヒー", "コーヒー"),
        ]
        for name, expected_cat in cases:
            img = get_dish_image(name)
            self.assertEqual(img["category"], expected_cat, f"Mismatch for {name}")
            # Served from here, not hotlinked: a chain menu is 200-340 rows.
            self.assertTrue(img["url"].startswith("/static/"))
            self.assertTrue(img["thumb_url"].startswith("/static/"))
            self.assertTrue(img["local_fallback"].startswith("/static/media/food/"))

    def test_default_fallback_dish(self):
        img = get_dish_image("未知の創作スペシャル料理")
        self.assertEqual(img["category"], "料理")
        self.assertTrue(img["url"].startswith("/static/"))

    def test_menu_page_renders_food_images(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            page = conn.execute("SELECT slug FROM shop_pages WHERE lang = 'ja' LIMIT 1").fetchone()
            slug = page["slug"] if page else None
        finally:
            conn.close()

        if not slug:
            raise unittest.SkipTest("No shop pages in DB")

        r = client.get(f"/menu/{slug}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn("dish-thumb-avatar", html)
        self.assertIn("dish-thumb-img", html)
        self.assertIn("modal-dish-photo-wrap", html)
        self.assertIn("modal-dish-img", html)

    def test_favicon_is_culinary_svg(self):
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn("rel=\"icon\"", html)
        self.assertIn("data:image/svg+xml", html)
        self.assertIn("%23B7282E", html)
        self.assertIn("%23FFD700", html)


if __name__ == "__main__":
    unittest.main()
