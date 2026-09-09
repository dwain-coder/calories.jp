"""Menu rows get a photograph of the right kind of dish, served from here.

Two failures this replaces. The catalogue held 21 bundled files for 39 keys, so
one photograph appeared forty times down a single chain menu. And its Unsplash
ids were built into live URLs, so a page with 340 rows fetched 340 third-party
images and told Unsplash who was reading which restaurant.
"""
import sqlite3
import unittest
from pathlib import Path

from dataset_manager.site import dish_concepts, queries
from dataset_manager.site.food_images import (
    CLASSIFICATION_RULES, classify_key, get_dish_image)

STATIC = Path("static")


def stored_photos():
    conn = queries.get_connection()
    try:
        return {r["concept"]: dict(r) for r in conn.execute("SELECT * FROM dish_photos")}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


class TestPhotographsAreServedFromHere(unittest.TestCase):

    def test_no_url_points_at_a_third_party(self):
        """340 rows on a chain menu is 340 requests if these are remote."""
        for name in ("ハンバーガー", "牛丼", "存在しない料理", "枝豆", "定食"):
            img = get_dish_image(name)
            for field in ("url", "card_url", "thumb_url", "local_fallback"):
                with self.subTest(name=name, field=field):
                    self.assertTrue(img[field].startswith("/static/"),
                                    f"{field} = {img[field]}")

    def test_every_stored_photograph_exists_on_disk(self):
        for concept, row in stored_photos().items():
            with self.subTest(concept=concept):
                self.assertTrue((STATIC / row["file"].lstrip("/static/")).is_file()
                                or (STATIC / "media" / "food" /
                                    Path(row["file"]).name).is_file(),
                                f"{row['file']} is missing")

    def test_every_photograph_is_freely_licensed(self):
        from dataset_manager.images.wikimedia import is_free
        for concept, row in stored_photos().items():
            with self.subTest(concept=concept):
                licence = (row["licence"] or "").lower()
                self.assertTrue("public domain" in licence or "cc0" in licence
                                or is_free(licence), f"{concept}: {row['licence']}")


class TestConceptsAndRulesAgree(unittest.TestCase):

    def test_every_concept_with_a_photograph_is_reachable(self):
        """A photograph for a concept no rule ever returns is dead weight.

        This is the mistake worth catching: adding 45 pictures and forgetting
        the 45 rules that select them leaves the menu exactly as it was.
        """
        # culinary_default is the fallback and is reached by nothing matching,
        # which is the one legitimate way to have a photograph and no rule.
        keys = {key for _, key in CLASSIFICATION_RULES} | {"culinary_default"}
        for concept in stored_photos():
            with self.subTest(concept=concept):
                self.assertIn(concept, keys,
                              f"{concept} has a photograph but no rule selects it")

    def test_the_concept_list_and_the_rules_do_not_drift(self):
        keys = {key for _, key in CLASSIFICATION_RULES} | {"culinary_default"}
        unreachable = set(dish_concepts.ALL) - keys
        self.assertFalse(unreachable, f"concepts no rule returns: {sorted(unreachable)}")


class TestTheRowsThatMatter(unittest.TestCase):

    def test_common_izakaya_and_teishoku_dishes_are_recognised(self):
        """These are what a 233-chain corpus is full of, and what the original
        fast-food catalogue had no answer for."""
        for name, key in (("焼き鳥盛り合わせ", "yakitori"),
                          ("枝豆", "edamame"),
                          ("冷奴", "hiyayakko"),
                          ("だし巻き卵", "tamagoyaki"),
                          ("日替わり定食", "teishoku"),
                          ("オムライス", "omurice"),
                          ("麻婆豆腐", "mapo_tofu"),
                          ("チャーハン", "chahan"),
                          ("たこ焼き", "takoyaki"),
                          ("ビビンバ", "bibimbap")):
            with self.subTest(name=name):
                self.assertEqual(classify_key(name), key)

    def test_a_real_dish_name_outranks_the_word_set(self):
        """定食 and セット sit at the bottom of the rules for this reason:
        「唐揚げ定食」 is a karaage photograph, not a generic tray."""
        self.assertEqual(classify_key("唐揚げ定食"), "teishoku")
        self.assertEqual(classify_key("ハンバーグセット"), "teishoku")


if __name__ == "__main__":
    unittest.main()
