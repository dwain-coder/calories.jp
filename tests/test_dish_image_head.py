"""A Japanese dish name names the dish at its end, not its start.

The catalogue is ordered by cuisine, and matching used to stop at the first
rule that hit anywhere in the string. So ポテトサラダ got a photo of chips, and
every 「コーヒー [ホット / アイス]」 on a café menu got an ice-cream parfait —
アイス is listed above コーヒー.
"""
import unittest

from dataset_manager.site.food_images import classify_key


class TestTheHeadNamesTheDish(unittest.TestCase):

    def test_a_modifier_does_not_win_over_the_head(self):
        """ポテト modifies サラダ. The salad is the dish."""
        self.assertEqual(classify_key("ポテトサラダ"), "salad_green")
        self.assertEqual(classify_key("グリルチキンのパワーサラダ"), "salad_green")
        self.assertEqual(classify_key("マグロステーキのニース風サラダ"), "salad_green")

    def test_the_head_still_wins_when_it_is_the_first_word(self):
        """Nothing about head-final should break the ordinary case."""
        for name, key in (("フレンチフライポテト", "french_fries"),
                          ("牛丼", "gyudon_beef"),
                          ("ざるそば", "soba"),
                          ("マルゲリータピザ", "pizza")):
            with self.subTest(name=name):
                self.assertEqual(classify_key(name), key)

    def test_iced_drinks_are_drinks_not_ice_cream(self):
        """アイス before コーヒー in the list is why this was wrong everywhere."""
        self.assertEqual(classify_key("アイスコーヒー"), "coffee")
        self.assertEqual(classify_key("コーヒー [ホット / アイス]"), "coffee")

    def test_a_tie_goes_to_the_more_specific_rule(self):
        """味噌ラーメン and ラーメン both end at the same character; the specific
        pattern is listed first and must keep its own photo."""
        self.assertEqual(classify_key("味噌ラーメン"), "ramen_miso")
        self.assertEqual(classify_key("アボカドチーズバーガー"), "burger_cheese")
        self.assertEqual(classify_key("豚骨ラーメン"), "ramen_tonkotsu")
        self.assertEqual(classify_key("豚骨醤油ラーメン"), "ramen_tonkotsu")

    def test_what_comes_after_a_delimiter_is_the_side_not_the_dish(self):
        """Past a comma or a space the name lists what arrives alongside."""
        self.assertEqual(
            classify_key("フレンチフライ サワークリーム&スイートチリソース"), "french_fries")
        self.assertEqual(
            classify_key("パンケーキ(ストロベリー&バニラアイス)"), "pancakes")

    def test_a_leading_marker_does_not_erase_the_name(self):
        """Menus prefix names — 「V ...」 for vegan, 「新 ...」 for new. Splitting
        on the space leaves a head of one letter, so the whole name is read."""
        self.assertEqual(classify_key("V ゴボウとキノコの豆乳腸活スープ"), "soup_miso")

    def test_an_unknown_name_falls_back_rather_than_raising(self):
        for name in ("", None, "？？？"):
            with self.subTest(name=name):
                self.assertTrue(classify_key(name))


if __name__ == "__main__":
    unittest.main()
