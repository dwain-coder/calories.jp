"""Photographs for dishes: what may be published, and what must never be.

Two things carry real risk here and both are tested against the cases that
actually occurred: a licence we are not allowed to republish under, and an
image of the wrong thing.
"""
import sqlite3
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.server import app
from dataset_manager.api.database import DB_PATH
from dataset_manager.images import wikimedia

client = TestClient(app)


class TestLicenceFilter(unittest.TestCase):
    def test_free_licences_are_accepted(self):
        for lic in ("CC0", "CC BY 4.0", "CC BY-SA 3.0", "Public domain",
                    "cc-by-sa-4.0", "PD-old"):
            self.assertTrue(wikimedia.is_free(lic), lic)

    def test_everything_else_is_refused(self):
        """Including anything unrecognised — a licence we cannot parse is not
        a licence we may publish under."""
        for lic in ("Fair use", "CC BY-NC 4.0", "CC BY-NC-SA 3.0", "CC BY-ND 4.0",
                    "All rights reserved", "", None, "Copyrighted free use?"):
            self.assertFalse(wikimedia.is_free(lic), lic)

    def test_non_commercial_is_refused_even_though_it_says_cc_by(self):
        """The substring 'cc by' appears in 'CC BY-NC', which is not free for a
        site that may one day carry advertising."""
        self.assertFalse(wikimedia.is_free("CC BY-NC 2.0"))


class TestNameGuard(unittest.TestCase):
    """A Commons text search for 「ジンギスカン」 returns a portrait of Genghis
    Khan third. A page with no photograph is fine; a page with the wrong
    photograph is not."""

    def _hit(self, title, description="", licence="CC BY 4.0"):
        return {"title": title, "imageinfo": [{
            "thumburl": "https://upload.wikimedia.org/x.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:x.jpg",
            "thumbwidth": 800, "thumbheight": 600,
            "extmetadata": {
                "LicenseShortName": {"value": licence},
                "ImageDescription": {"value": description},
                "Artist": {"value": "Someone"},
            }}]}

    def test_a_described_image_passes(self):
        hit = wikimedia._describe(self._hit("File:Keiran.jpg", "けいらん、青森の郷土料理"))
        self.assertIsNotNone(hit)
        self.assertIn("けいらん", hit["haystack"])

    def test_an_unrelated_image_has_nothing_to_match_on(self):
        hit = wikimedia._describe(
            self._hit("File:YuanEmperorAlbumGenghisPortrait.jpg", "Portrait of Genghis Khan"))
        self.assertNotIn("ジンギスカン", hit["haystack"])

    def test_a_non_free_image_is_dropped_before_the_guard_runs(self):
        self.assertIsNone(
            wikimedia._describe(self._hit("File:x.jpg", "けいらん", licence="Fair use")))


class TestStoredImages(unittest.TestCase):
    def _rows(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM item_images")]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def test_every_stored_image_is_free_and_credited(self):
        """CC BY and CC BY-SA both require naming the author, so an image we
        cannot credit is one we cannot show."""
        rows = self._rows()
        if not rows:
            self.skipTest("no images fetched in this database")
        for r in rows:
            self.assertTrue(wikimedia.is_free(r["licence"]), f"{r['item_id']}: {r['licence']}")
            self.assertTrue((r["credit"] or "").strip(), f"{r['item_id']} has no credit")
            self.assertTrue(r["url"].startswith("https://"), r["url"])

    def test_images_are_only_attached_to_dishes(self):
        rows = self._rows()
        if not rows:
            self.skipTest("no images fetched in this database")
        conn = sqlite3.connect(DB_PATH)
        try:
            types = {r[0] for r in conn.execute(
                "SELECT DISTINCT page_type FROM site_pages WHERE item_id IN "
                "(SELECT item_id FROM item_images)")}
        finally:
            conn.close()
        self.assertLessEqual(types, {"dish"}, types)

    def test_a_page_with_a_photo_shows_its_credit(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """SELECT sp.slug, im.licence FROM item_images im
                   JOIN site_pages sp ON sp.item_id = im.item_id AND sp.lang = 'ja'
                   LIMIT 1""").fetchone()
        except sqlite3.OperationalError:
            row = None
        finally:
            conn.close()
        if not row:
            self.skipTest("no images fetched in this database")
        html = client.get(f"/dish/{row['slug']}").text
        self.assertIn("dish-photo", html)
        self.assertIn(row["licence"], html)
        self.assertIn("Wikimedia Commons", html)


if __name__ == "__main__":
    unittest.main()
