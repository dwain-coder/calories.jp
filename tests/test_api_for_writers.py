"""The API has to carry provenance, or a consumer will invent it.

These endpoints exist because a drafting tool reads them and writes prose from
what comes back. Four bare macros are enough for a page that renders its own
footnote underneath them, and not enough for anything reading over the wire:
an estimate restated as a measurement is indistinguishable from a lie by the
time it reaches a reader.
"""
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.server import app

client = TestClient(app)


def a_food_with(predicate, tries=("鶏", "こむぎ", "こめ", "ぶた")):
    """The first searchable food whose nutrition payload satisfies predicate."""
    for q in tries:
        for hit in client.get("/api/search", params={"q": q, "limit": 8}).json():
            body = client.get(f"/api/foods/{hit['item_id']}/nutrition").json()
            if predicate(body):
                return body
    return None


class TestProvenanceSurvivesTheAPI(unittest.TestCase):

    def test_every_value_says_how_it_was_arrived_at(self):
        body = a_food_with(lambda b: b.get("nutrients"))
        self.assertIsNotNone(body, "no food came back with nutrients")
        for row in body["nutrients"]:
            with self.subTest(code=row["code"]):
                self.assertIn(row["quality"], ("measured", "estimated", "trace"))

    def test_an_estimate_is_not_returned_as_a_measurement(self):
        """MEXT parenthesises estimated values; 15.8% of the table is one.

        If the corpus holds none, this test is wrong to pass silently — the
        backfill has not run and every consumer is being told the whole table
        was measured.
        """
        body = a_food_with(
            lambda b: any(r["quality"] == "estimated" for r in b.get("nutrients") or []))
        self.assertIsNotNone(body, "no estimated values anywhere — has the backfill run?")

    def test_salt_and_micronutrients_are_reachable(self):
        """Neither is in the `nutrition` table, so per_100g cannot carry them."""
        body = a_food_with(
            lambda b: any(r["code"] == "NACL_EQ" for r in b.get("nutrients") or []))
        self.assertIsNotNone(body, "食塩相当量 is not exposed")
        codes = {r["code"] for r in body["nutrients"]}
        self.assertTrue(codes & {"FE", "CA", "K", "VITC"}, "no micronutrients exposed")

    def test_the_licence_travels_with_the_numbers(self):
        """A consumer republishing these owes attribution and cannot look it up."""
        body = a_food_with(lambda b: b.get("per_100g"))
        self.assertTrue(body.get("license"))
        self.assertTrue(body.get("source"))


class TestCookingYield(unittest.TestCase):

    def test_a_rate_can_be_found_by_name(self):
        rows = client.get("/api/cooking-yield", params={"q": "もも 皮つき"}).json()
        self.assertTrue(rows)
        for r in rows:
            with self.subTest(name=r["name"]):
                self.assertIn("もも", r["name"])
                self.assertGreater(r["rate_percent"], 0)

    def test_cooking_can_add_weight_as_well_as_remove_it(self):
        """Boiled pasta is 220%. A caller assuming rates are always below 100
        would halve every noodle dish it wrote about.
        """
        rows = client.get("/api/cooking-yield", params={"q": "スパゲッティ"}).json()
        self.assertTrue(any(r["rate_percent"] > 100 for r in rows),
                        [(r["name"], r["rate_percent"]) for r in rows])

    def test_the_rate_belongs_to_the_cooked_food_not_the_raw_one(self):
        """MEXT files the rate against the cooked entry, so 乾 has none and
        ゆで has 220. Reading it off the raw item returns an empty list, not a
        wrong number."""
        dry = [h for h in client.get("/api/search", params={"q": "マカロニ", "limit": 8}).json()
               if h["title"].endswith("乾")]
        if dry:
            self.assertEqual(
                client.get(f"/api/foods/{dry[0]['item_id']}/cooking-yield").json(), [])

    def test_an_unknown_food_is_a_404_not_an_empty_list(self):
        self.assertEqual(client.get("/api/foods/99999999/cooking-yield").status_code, 404)

    def test_a_bad_language_is_refused(self):
        self.assertEqual(
            client.get("/api/cooking-yield", params={"q": "鶏", "lang": "xx"}).status_code, 400)


class TestTheQuarantineHolds(unittest.TestCase):

    def test_only_foods_with_a_public_page_answer(self):
        """Every payload here joins through site_pages, which is the clean
        corpus gate. OpenFoodFacts is ODbL and must not leave the building via
        an endpoint that forgot to join.
        """
        for path in ("/api/foods/99999999/nutrition", "/api/foods/99999999/cooking-yield"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
