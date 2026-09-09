"""Prefecture pages: what a region cooks, and what it cooks with.

MAFF's dishes share items.category with MEXT's food groups, so both rendered
through the same comparison template — which leads with a calorie column, and a
dish has no stored calorie. Every prefecture page was a list of names beside
thirty blanks.
"""
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.server import app
from dataset_manager.site import queries

client = TestClient(app)


class TestEveryPrefectureHasAPage(unittest.TestCase):
    def test_all_forty_seven_render(self):
        missing = []
        for pref in queries.PREFECTURES:
            if pref == "北海道県":          # not a real label, guarded in the tuple
                continue
            if queries.prefecture_data("ja", pref) is None:
                missing.append(pref)
        self.assertEqual(missing, [], f"no dishes for: {missing}")

    def test_a_prefecture_gets_the_prefecture_template(self):
        html = client.get("/category/青森県").text
        self.assertIn("青森県の郷土料理", html)
        self.assertIn("主な材料", html)

    def test_a_food_group_still_gets_the_comparison_table(self):
        """The two page types share a URL space; only prefectures changed."""
        html = client.get("/category/魚介類").text
        self.assertNotIn("郷土料理", html)


class TestSignatureIngredients(unittest.TestCase):
    """The fact that makes the page more than a list: which ingredients this
    prefecture reaches for more than the country does."""

    def test_okinawa_is_the_place_that_cooks_with_awamori_and_lard(self):
        sig = {s["name"] for s in queries.prefecture_data("ja", "沖縄県")["signature"]}
        self.assertTrue(any("泡盛" in n for n in sig), sig)
        self.assertTrue(any("ラード" in n for n in sig), sig)

    def test_the_ratio_is_local_over_national(self):
        for s in queries.prefecture_data("ja", "京都府")["signature"]:
            self.assertLessEqual(s["used_here"], s["used_total"])
            self.assertGreaterEqual(s["used_here"], 2)   # one dish is not a pattern

    def test_seasonings_everyone_uses_do_not_dominate(self):
        """Sugar is in 690 of 1,350 recipes. A raw count would put it on all 47
        pages and say nothing."""
        for pref in ("青森県", "沖縄県", "京都府", "鹿児島県"):
            names = {s["name"] for s in queries.prefecture_data("ja", pref)["signature"]}
            self.assertNotIn("車糖 上白糖", names, pref)
            self.assertNotIn("食塩", names, pref)


class TestLinking(unittest.TestCase):
    def test_prefectures_link_to_each_other(self):
        """Search brings a reader to one prefecture; the cluster has to be
        walkable from there."""
        html = client.get("/category/沖縄県").text
        for pref in ("青森県", "京都府", "鹿児島県"):
            self.assertIn(pref, html)

    def test_dishes_link_to_their_own_pages(self):
        data = queries.prefecture_data("ja", "青森県")
        html = client.get("/category/青森県").text
        self.assertIn(f'/dish/{data["dishes"][0]["slug"]}', html)


if __name__ == "__main__":
    unittest.main()
