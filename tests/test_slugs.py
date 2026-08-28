import unittest

from dataset_manager.scripts.build_site import clean_mext_name, slugify_en, slugify_ja


class TestSlugs(unittest.TestCase):
    def test_en_basic(self):
        self.assertEqual(slugify_en("Chicken breast, skin-on, raw"), "chicken-breast-skin-on-raw")

    def test_en_accents(self):
        self.assertEqual(slugify_en("Crème fraîche"), "creme-fraiche")

    def test_en_deterministic(self):
        self.assertEqual(slugify_en("Hummus, commercial"), slugify_en("Hummus, commercial"))

    def test_ja_spaces(self):
        self.assertEqual(slugify_ja("にわとり むね 皮つき 生"), "にわとり-むね-皮つき-生")

    def test_ja_strips_unsafe(self):
        self.assertNotIn("/", slugify_ja("ういろう (企業)/テスト"))
        self.assertNotIn("(", slugify_ja("ういろう (企業)"))

    def test_clean_mext_name(self):
        self.assertEqual(
            clean_mext_name("＜鳥肉類＞　にわとり　［親・主品目］　むね　皮つき　生"),
            "にわとり 親・主品目 むね 皮つき 生",
        )

    def test_clean_plain_name_unchanged(self):
        self.assertEqual(clean_mext_name("けいらん"), "けいらん")


if __name__ == "__main__":
    unittest.main()
