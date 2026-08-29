"""Analyzer assembly: dish breakdown, per-serving arithmetic, unmatched handling.

The vision call is faked — these tests are about what the endpoint does with a
model reply, which is where the numbers come from. No API key needed.
"""
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from dataset_manager.api import analyzer
from dataset_manager.api.server import app

client = TestClient(app)

JPEG = b"\xff\xd8\xff" + b"\x00" * 64          # magic bytes are all _sniff reads

LASAGNA = {
    "dishes": [{
        "dish_ja": "ミートラザニア", "dish_en": "meat lasagna", "servings_visible": 2,
        "components": [
            {"name_ja": "マカロニ・スパゲッティ ゆで", "name_en": "pasta, boiled",
             "estimated_grams": 120, "confidence": "medium"},
            {"name_ja": "うし ひき肉 生", "name_en": "beef, minced, raw",
             "estimated_grams": 80, "confidence": "medium"},
            {"name_ja": "普通牛乳", "name_en": "milk", "estimated_grams": 50, "confidence": "low"},
            {"name_ja": "ズィーグルンプフ", "name_en": "not a real food",
             "estimated_grams": 10, "confidence": "low"},
        ],
    }]
}


class FakeResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload, ensure_ascii=False)


def fake_client(payload):
    c = mock.MagicMock()
    c.models.generate_content.return_value = FakeResponse(payload)
    return c


def analyze(payload):
    """POST an image with the model's reply stubbed out, cache bypassed."""
    analyzer._hits.clear()
    with mock.patch("dataset_manager.api.server.get_gemini_client",
                    return_value=fake_client(payload)), \
         mock.patch.object(analyzer, "_cache_get", return_value=None), \
         mock.patch.object(analyzer, "_cache_put"):
        r = client.post("/api/meal-analyzer?lang=ja",
                        files={"image": ("meal.jpg", JPEG, "image/jpeg")})
    analyzer._hits.clear()
    return r


class TestDishBreakdown(unittest.TestCase):
    def test_composite_dish_is_costed_from_its_ingredients(self):
        d = analyze(LASAGNA).json()
        self.assertEqual(len(d["dishes"]), 1)
        dish = d["dishes"][0]
        self.assertEqual(dish["name_ja"], "ミートラザニア")
        # three of the four components resolve; the invented one does not
        self.assertEqual(dish["n_total"], 4)
        self.assertEqual(dish["n_matched"], 3)
        self.assertGreater(dish["totals"]["energy_kcal"], 0)
        self.assertEqual(len(dish["component_indexes"]), 3)

    def test_every_component_carries_its_own_figures(self):
        d = analyze(LASAGNA).json()
        for c in d["components"]:
            self.assertIsNotNone(c["db_match"]["item_id"])
            self.assertTrue(c["db_match"]["url"].startswith("/ja/food/"))
            self.assertTrue(c["ai_estimate"]["estimated"])
            # kcal is per-100g x grams, so it must fall out of the two
            per100 = c["db_match"]["per_100g"]["energy_kcal"]
            grams = c["ai_estimate"]["estimated_grams"]
            self.assertAlmostEqual(c["calculated"]["energy_kcal"], per100 * grams / 100, places=2)

    def test_unmatched_ingredient_is_named_but_never_costed(self):
        d = analyze(LASAGNA).json()
        self.assertTrue(d["unmatched"])
        u = d["unmatched"][0]
        self.assertEqual(u["dish_index"], 0)
        self.assertNotIn("calculated", u)
        # its grams are not folded into the dish or the meal
        summed = sum(c["calculated"]["energy_kcal"] for c in d["components"] if c["calculated"])
        self.assertAlmostEqual(d["totals"]["energy_kcal"], summed, places=2)

    def test_per_serving_divides_the_plate(self):
        d = analyze(LASAGNA).json()
        self.assertEqual(d["servings"], 2)
        self.assertAlmostEqual(d["per_serving"]["energy_kcal"],
                               d["totals"]["energy_kcal"] / 2, places=1)
        dish = d["dishes"][0]
        self.assertAlmostEqual(dish["per_serving"]["energy_kcal"],
                               dish["totals"]["energy_kcal"] / 2, places=1)

    def test_single_serving_has_no_per_serving_line(self):
        payload = json.loads(json.dumps(LASAGNA))
        payload["dishes"][0]["servings_visible"] = 1
        d = analyze(payload).json()
        self.assertIsNone(d["per_serving"])       # it would just repeat the total

    def test_flat_food_list_still_works(self):
        """Older cached shape, and what a model sometimes answers anyway."""
        d = analyze({"foods": [{"name_ja": "普通牛乳", "name_en": "milk",
                                "estimated_grams": 200, "confidence": "high"}]}).json()
        self.assertEqual(len(d["dishes"]), 1)
        self.assertEqual(d["dishes"][0]["n_matched"], 1)
        self.assertGreater(d["totals"]["energy_kcal"], 0)

    def test_cached_analysis_from_the_old_shape_still_renders(self):
        """A photo analysed before the breakdown existed must not come back
        as an empty report."""
        old = analyze(LASAGNA).json()
        old.pop("dishes"); old.pop("per_serving"); old.pop("servings")
        analyzer._hits.clear()
        with mock.patch.object(analyzer, "_cache_get", return_value=old):
            r = client.post("/api/meal-analyzer?lang=ja",
                            files={"image": ("meal.jpg", JPEG, "image/jpeg")})
        analyzer._hits.clear()
        d = r.json()
        self.assertTrue(d["cached"])
        self.assertEqual(len(d["dishes"]), 1)
        self.assertEqual(d["dishes"][0]["component_indexes"], [0, 1, 2])
        self.assertEqual(d["dishes"][0]["totals"], old["totals"])

    def test_empty_reply_is_not_a_crash(self):
        d = analyze({"dishes": []}).json()
        self.assertEqual(d["dishes"], [])
        self.assertEqual(d["components"], [])


if __name__ == "__main__":
    unittest.main()
