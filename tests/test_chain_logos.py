"""A chain gets its own logo, or a tile that is plainly not a logo.

What it must never get is a drawing that approximates the real mark. That is
neither the logo nor honestly not-the-logo, and it is the version a trade mark
owner has cause to object to — an earlier attempt shipped hand-drawn golden
arches and a KFC bucket before this replaced them.
"""
import sqlite3
import unittest
from pathlib import Path

from dataset_manager.site import queries
from dataset_manager.site.brand_assets import get_chain_brand_badge

LOGO_DIR = Path("static/media/logos")


def stored_logos():
    conn = queries.get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM chain_logos")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


class TestLogosAreRealAndFree(unittest.TestCase):

    def test_every_stored_logo_has_a_file_on_disk(self):
        """A path in the database and no file is a broken image on a menu page."""
        for row in stored_logos():
            with self.subTest(chain=row["chain"]):
                self.assertTrue((LOGO_DIR / Path(row["file"]).name).is_file(),
                                f"{row['file']} is missing")

    def test_every_logo_is_freely_licensed(self):
        """These are republished, so the licence is not a detail.

        Japanese chain wordmarks are typically PD-textlogo: below the threshold
        of originality, therefore uncopyrightable. Anything that is not public
        domain or an explicit free licence has no business being served.
        """
        from dataset_manager.images.wikimedia import is_free
        for row in stored_logos():
            with self.subTest(chain=row["chain"]):
                licence = (row["licence"] or "").lower()
                self.assertTrue(
                    "public domain" in licence or "cc0" in licence or is_free(licence),
                    f"{row['chain']}: {row['licence']}")

    def test_a_chain_without_a_logo_falls_back_to_a_tile(self):
        badge = get_chain_brand_badge("架空の存在しない店")
        self.assertIsNone(badge.get("logo_file"))
        self.assertTrue(badge.get("mark"))

    def test_a_known_chain_keeps_its_colours_alongside_its_logo(self):
        """The tile palette still styles the surround, so losing the logo file
        degrades to the previous appearance rather than to nothing."""
        badge = get_chain_brand_badge("マクドナルド")
        self.assertTrue(badge.get("bg"))
        self.assertTrue(badge.get("mark"))

    def test_no_drawn_imitation_marks_remain(self):
        """The SVG approximations are gone and must not come back."""
        source = Path("dataset_manager/site/brand_assets.py").read_text(encoding="utf-8")
        self.assertNotIn("logo_svg", source)
        self.assertNotIn("<svg", source)


if __name__ == "__main__":
    unittest.main()
