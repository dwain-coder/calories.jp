"""The Helm-only endpoints: shut without a key, honest about what each figure is."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from dataset_manager.api import writer_api
from dataset_manager.api.server import app

client = TestClient(app)
KEY = {"X-API-Key": "test-key"}


class TestWriterApi(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(writer_api, "WRITER_API_KEY", "test-key")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_key_is_required(self):
        self.assertEqual(client.get("/api/menus").status_code, 401)
        self.assertEqual(client.get("/api/menus", headers={"X-API-Key": "nope"}).status_code, 401)
        self.assertEqual(client.get("/api/menus", headers=KEY).status_code, 200)

    def test_no_key_configured_means_no_endpoint(self):
        with mock.patch.object(writer_api, "WRITER_API_KEY", ""):
            self.assertEqual(client.get("/api/reference-values", headers=KEY).status_code, 404)

    def test_a_partial_dish_total_says_it_is_partial(self):
        """朴葉ずし's rice does not resolve, so its total is a lower bound."""
        hit = next(r for r in client.get("/api/search", params={"q": "朴葉ずし"}).json()
                   if r["page_type"] == "dish")
        body = client.get(f"/api/dishes/{hit['item_id']}/nutrition", headers=KEY).json()
        n = body["nutrition"]
        self.assertEqual(n["basis"], "whole_recipe")
        self.assertFalse(n["complete"])
        self.assertLess(n["n_resolved"], n["n_total"])
        self.assertTrue(any(i["matched_food"] is None for i in body["ingredients"]))
        self.assertIn("うちの郷土料理", body["attribution"]["text"])

    def test_every_menu_figure_says_what_it_is(self):
        body = client.get("/api/menus/モスバーガー", headers=KEY).json()
        self.assertTrue(body["sources"]["chain"]["page"].startswith("https://"))
        for item in body["items"]:
            self.assertEqual(item["basis"], writer_api.BASIS.get(item["kcal_source"]), item["name"])
        self.assertTrue(any(i["kcal_source"] == "chain" for i in body["items"]))

    def test_rankings_are_measured_only(self):
        body = client.get("/api/nutrients/protein", params={"limit": 5}, headers=KEY).json()
        self.assertEqual((body["basis"], body["quality"]), ("per_100g", "measured_only"))
        self.assertEqual(len(body["ranking"]), 5)

    def test_reference_values_are_the_2025_tables(self):
        body = client.get("/api/reference-values", headers=KEY).json()
        self.assertEqual(body["labelling_reference"]["macros"]["protein_g"], 85)
        self.assertEqual(body["labelling_reference"]["macros"]["salt_g"], 7.0)
        self.assertEqual(body["labelling_reference"]["micros"]["VITD"]["value"], 9.0)
        self.assertEqual(body["claim_thresholds"]["nutrients"]["PROT-"]["high"], 17.0)
        self.assertEqual(body["salt_target"]["women_below_g"], 6.5)


if __name__ == "__main__":
    unittest.main()
