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


class TestNamesTheDish(unittest.TestCase):
    """Japanese has no word boundaries, so a substring match is not a word
    match. Every case here was found on a live page or in a live search."""

    def test_a_longer_word_that_merely_starts_with_the_name_is_refused(self):
        """「あずまや」 is a garden gazebo. It was on the 「あずま」 page."""
        self.assertFalse(wikimedia.names_the_dish("あずま", "File:あずまや_(20675474).jpg"))
        self.assertFalse(wikimedia.names_the_dish("もち", "File:うぐいすもち.jpg"))

    def test_a_qualifier_in_front_still_names_the_dish(self):
        """A Japanese compound is headed by its last element, so 「醤油ラーメン」
        is ramen — only what follows the name can change what it refers to."""
        self.assertTrue(wikimedia.names_the_dish("ラーメン", "File:醤油ラーメン.jpg"))
        self.assertTrue(wikimedia.names_the_dish("えび天", "File:Bukkake_Udon_with_えび天.jpg"))

    def test_punctuation_and_digits_end_the_word(self):
        self.assertTrue(wikimedia.names_the_dish("いももち", "File:20240307いももち.jpg"))
        self.assertTrue(wikimedia.names_the_dish("けの汁", "File:家庭で作った、けの汁.jpg"))
        self.assertTrue(
            wikimedia.names_the_dish("ジンギスカン", "File:プレート（ジンギスカン・千葉）.jpg"))

    def test_a_short_name_inside_a_longer_compound_is_refused(self):
        """Three characters of kana land inside unrelated words often enough to
        matter. All three were live: 「あずま」 showed a sweet-potato cultivar,
        「ならえ」 showed military equipment from 「右へならえ」, 「豆腐飯」 a Chinese
        set meal."""
        self.assertFalse(wikimedia.names_the_dish("あずま", "File:紅あずま_(51045191038).jpg"))
        self.assertFalse(wikimedia.names_the_dish("ならえ", "File:「右へならえ」装備.jpg"))
        self.assertFalse(wikimedia.names_the_dish("豆腐飯", "File:燒汁鯖魚定食_雜菌豆腐飯.jpg"))

    def test_a_short_name_standing_on_its_own_is_kept(self):
        self.assertTrue(wikimedia.names_the_dish("納豆餅", "File:納豆餅.jpg"))
        self.assertTrue(wikimedia.names_the_dish("お雑煮", "File:Ozoni_お雑煮_(31176080104).jpg"))
        self.assertTrue(wikimedia.names_the_dish("えび天", "File:Bukkake_Udon_with_えび天.jpg"))

    def test_a_long_name_may_still_follow_japanese(self):
        """The left-boundary rule is only for short names; it would cost a long
        one real matches."""
        self.assertTrue(wikimedia.names_the_dish("ラーメン", "File:醤油ラーメン.jpg"))

    def test_short_names_are_not_searched_at_all(self):
        """A two-character name appears inside half of Commons."""
        self.assertFalse(wikimedia.names_the_dish("そば", "File:そば.jpg"))

    def test_an_unrelated_title_is_refused(self):
        """A bento box was on the 「いもたこ」 page, matched through its
        description — which is why only the title is checked now."""
        self.assertFalse(wikimedia.names_the_dish("いもたこ", "File:あをによし弁当.jpeg"))


if __name__ == "__main__":
    unittest.main()


class TestEveryDishIsIllustrated(unittest.TestCase):
    """375 dishes have a photograph of themselves. The rest show the right KIND
    of dish, labelled as that — a page with nothing on it reads as broken, and a
    page with the wrong photograph says something false."""

    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def test_no_dish_page_is_left_without_an_image(self):
        conn = self._conn()
        try:
            missing = conn.execute(
                """SELECT COUNT(*) FROM site_pages sp
                   WHERE sp.page_type = 'dish' AND sp.lang = 'ja'
                     AND sp.item_id NOT IN (SELECT item_id FROM item_images)""").fetchone()[0]
        except sqlite3.OperationalError:
            self.skipTest("no images in this database")
        finally:
            conn.close()
        self.assertEqual(missing, 0)

    def test_a_category_image_says_it_is_one(self):
        """It must never be mistaken for a photograph of that dish."""
        conn = self._conn()
        try:
            row = conn.execute(
                """SELECT sp.slug, im.matched_on FROM item_images im
                   JOIN site_pages sp ON sp.item_id = im.item_id AND sp.lang = 'ja'
                   WHERE im.matched_on LIKE 'category:%' LIMIT 1""").fetchone()
        finally:
            conn.close()
        if not row:
            self.skipTest("no category images assigned")
        html = client.get(f"/dish/{row['slug']}").text
        category = row["matched_on"].split(":", 1)[1]
        self.assertIn("photo-kind", html)
        self.assertIn(f"{category}のイメージ写真", html)

    def test_a_real_photograph_is_not_labelled_as_a_category(self):
        conn = self._conn()
        try:
            row = conn.execute(
                """SELECT sp.slug FROM item_images im
                   JOIN site_pages sp ON sp.item_id = im.item_id AND sp.lang = 'ja'
                   WHERE im.matched_on NOT LIKE 'category:%' LIMIT 1""").fetchone()
        finally:
            conn.close()
        if not row:
            self.skipTest("no dish-specific images")
        self.assertNotIn("photo-kind", client.get(f"/dish/{row['slug']}").text)

    def test_the_label_matches_the_image_shown(self):
        """Five categories have no usable photograph and fall back to 和食. The
        label has to fall back with them, or a page reads 「卵のイメージ」 over a
        photograph of osechi."""
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT DISTINCT im.matched_on, im.url FROM item_images im
                   WHERE im.matched_on LIKE 'category:%'""").fetchall()
            cats = {r[0]: r[1] for r in conn.execute(
                "SELECT category, url FROM category_images")}
        except sqlite3.OperationalError:
            self.skipTest("no category images")
        finally:
            conn.close()
        for r in rows:
            label = r["matched_on"].split(":", 1)[1]
            self.assertIn(label, cats, f"{label} has no image of its own")
            self.assertEqual(r["url"], cats[label],
                             f"{label} is labelled over a different image")
