"""What PageSpeed flagged on the home page (mobile, 2026-09-29): static files
with no cache lifetime, and hero photographs several times the size they show at.
"""
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from dataset_manager.api.server import app

client = TestClient(app)


class TestStaticCaching(unittest.TestCase):
    def test_a_versioned_asset_is_immutable(self):
        r = client.get("/static/site.css?v=anything")
        self.assertEqual(r.status_code, 200)
        self.assertIn("immutable", r.headers["cache-control"])

    def test_an_unversioned_file_is_cached_for_a_week(self):
        r = client.get("/static/media/home-hero.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "public, max-age=604800")

    def test_a_missing_file_is_not_cached(self):
        r = client.get("/static/no-such-file.css?v=1")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("immutable", r.headers.get("cache-control", ""))


class TestHeroPhotographs(unittest.TestCase):
    def test_no_still_is_larger_than_twice_its_largest_frame(self):
        for jpg in Path("static/media").glob("*.jpg"):
            self.assertLessEqual(min(Image.open(jpg).size), 720, jpg.name)


class TestFonts(unittest.TestCase):
    def test_the_font_stylesheet_does_not_block_first_paint(self):
        """The only blocking link is the <noscript> fallback."""
        html = client.get("/").text
        blocking = '<link rel="stylesheet" href="https://fonts.googleapis.com'
        self.assertEqual(html.count(blocking), 1)
        self.assertIn("<noscript>" + blocking, html)
        self.assertIn('rel="preload" as="style" href="https://fonts.googleapis.com', html)


if __name__ == "__main__":
    unittest.main()
