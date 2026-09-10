"""What the analyzer is allowed to claim about a photograph.

Sixty-three photographs of chain meals, scored against the calories those
chains publish (tools/score_analyzer.py), put the estimate's median error at
22% and its ninetieth percentile at 53% — and the median ratio of published to
ours at 1.02. Unbiased and noisy. Nothing to calibrate, and no honest way to
print a figure to the kilocalorie.

So two rules, both tested here. The total is rounded and carries the band it
was measured to sit in. And where the menu itself states a weight, that weight
beats the model's guess at it.
"""
import re
import unittest
from pathlib import Path

from dataset_manager.api import analyzer


class TestTheTotalDoesNotOverclaim(unittest.TestCase):

    def test_the_headline_is_rounded(self):
        """718 kcal from a photograph is three significant figures of nothing."""
        self.assertEqual(analyzer.estimate_band(718)["point"], 700)
        self.assertEqual(analyzer.estimate_band(409)["point"], 400)
        self.assertEqual(analyzer.estimate_band(1237)["point"], 1250)

    def test_the_band_is_the_measured_one(self):
        band = analyzer.estimate_band(800)
        self.assertEqual(band["share_pct"], 25)
        self.assertEqual((band["low"], band["high"]), (600, 1000))

    def test_nothing_is_claimed_about_nothing(self):
        for empty in (0, None, -5):
            self.assertIsNone(analyzer.estimate_band(empty))

    def test_the_band_reaches_the_response(self):
        source = Path("dataset_manager/api/analyzer.py").read_text(encoding="utf-8")
        self.assertIn('"totals_band": estimate_band(', source)

    def test_the_widget_prints_the_band_and_not_the_raw_figure(self):
        js = Path("static/analyzer.js").read_text(encoding="utf-8")
        self.assertIn("d.totals_band", js)
        self.assertIn("estimateBand", js)
        self.assertNotRegex(
            js, r"kcal-hero.*Math\.round\(d\.totals\.energy_kcal\)[^;]*</p>",
            "the headline must come from the band, not the unrounded total")


class TestTheMenuBeatsTheModel(unittest.TestCase):

    def test_a_stated_weight_is_read(self):
        for name, grams in (("ラウンドステーキ(約120g)", 120),
                            ("プライムサーロインステーキ(約200g)", 200),
                            ("大俵ハンバーグ200g", 200)):
            with self.subTest(name):
                self.assertEqual(analyzer.stated_portion(name), {"grams": float(grams)})

    def test_a_sauce_sachet_is_not_a_portion(self):
        """「ソース20g」 is not what the dish is named after."""
        self.assertIsNone(analyzer.stated_portion("ハンバーグ ソース20g"))

    def test_a_name_that_states_nothing_states_nothing(self):
        for name in ("明太マヨ", "", None, "3種の味が楽しめる鶏竜田"):
            self.assertIsNone(analyzer.stated_portion(name))

    def test_the_heaviest_component_is_the_one_corrected(self):
        """A steak plate is named after the steak, not the onions beside it."""
        foods = [{"name_ja": "たまねぎ", "estimated_grams": 25.0},
                 {"name_ja": "牛肩肉", "estimated_grams": 180.0},
                 {"name_ja": "植物油", "estimated_grams": 5.0}]
        changed = analyzer.apply_stated_portion(
            "ラウンドステーキ(約120g)", foods,
            grams_of=lambda f: f.get("estimated_grams"),
            set_grams=lambda f, g: f.__setitem__("estimated_grams", g))
        self.assertEqual(changed, 1)
        self.assertEqual(foods[1]["estimated_grams"], 120.0)
        self.assertEqual(foods[0]["estimated_grams"], 25.0)

    def test_it_corrects_upward_too(self):
        """The サーロイン was read as 150 g and sold as 200. A rule that only
        capped would be fitting the error rather than using the fact."""
        foods = [{"name_ja": "牛サーロイン肉", "estimated_grams": 150.0}]
        analyzer.apply_stated_portion(
            "プライムサーロインステーキ(約200g)", foods,
            grams_of=lambda f: f.get("estimated_grams"),
            set_grams=lambda f, g: f.__setitem__("estimated_grams", g))
        self.assertEqual(foods[0]["estimated_grams"], 200.0)

    def test_a_count_is_parsed_and_deliberately_not_applied(self):
        """The 3 in 「…焼餃子3個・半チャーハン」 belongs to the gyoza, not to the
        heaviest thing on the tray. Applying counts took the benchmark from
        -2% to +5% and gained no accuracy, so it is read and not used."""
        self.assertEqual(
            analyzer.stated_portion("超粗びきステーキバーグ×３（ラージ）"), {"count": 3})
        foods = [{"name_ja": "ラーメン", "estimated_grams": 400.0}]
        changed = analyzer.apply_stated_portion(
            "RGC定食（バーミヤンラーメン・焼餃子3個・半チャーハン）", foods,
            grams_of=lambda f: f.get("estimated_grams"),
            set_grams=lambda f, g: f.__setitem__("estimated_grams", g))
        self.assertEqual(changed, 0)
        self.assertEqual(foods[0]["estimated_grams"], 400.0)

    def test_the_correction_runs_before_anything_is_computed(self):
        """Patching the total afterwards would leave the components, the
        per-dish totals and the micronutrients disagreeing with it."""
        source = Path("dataset_manager/api/analyzer.py").read_text(encoding="utf-8")
        body = source[source.index("def calculate_nutrition_for_dishes"):]
        self.assertLess(body.index("apply_stated_portion"), body.index("for di, dish in"))

    def test_a_named_analysis_is_not_cached_over_an_unnamed_one(self):
        source = Path("dataset_manager/api/analyzer.py").read_text(encoding="utf-8")
        self.assertIn("if not dish:\n        _cache_put(sha, lang, result)", source)


class TestTwoRegexesOneName(unittest.TestCase):

    def test_the_menu_parser_is_not_shadowed_by_the_dish_name_parser(self):
        """Both were called _STATED_G in one module, and Python keeps the last.

        The dish-name path's version is deliberately looser — it will read a
        bare number — so whichever was defined second silently became both.
        """
        source = Path("dataset_manager/api/analyzer.py").read_text(encoding="utf-8")
        names = re.findall(r"^(_\w+) = re\.compile", source, re.M)
        self.assertEqual(len(names), len(set(names)), f"shadowed: {names}")


if __name__ == "__main__":
    unittest.main()
