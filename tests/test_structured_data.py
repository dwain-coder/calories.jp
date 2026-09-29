"""The JSON-LD Search Console reads, checked against what it rejected.

Recipes: Missing field "image" and "recipeYield" (both critical).
Breadcrumbs: Missing field "item" (in "itemListElement").
"""
import json
import re
import sqlite3
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.database import DB_PATH
from dataset_manager.api.server import app
from dataset_manager.site import seo

client = TestClient(app)
LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def jsonld(path):
    return [json.loads(m) for m in LD.findall(client.get(path).text)]


def of_type(blocks, kind):
    return [b for b in blocks if b.get("@type") == kind]


class TestBreadcrumbs(unittest.TestCase):
    def test_only_the_last_crumb_may_have_no_url(self):
        ld = seo.breadcrumbs_jsonld([
            ("ホーム", "https://calories.jp/"), ("郷土料理", None),
            ("青森県", "https://calories.jp/category/青森県"), ("けいらん", None)])
        items = ld["itemListElement"]
        self.assertEqual([i["name"] for i in items], ["ホーム", "青森県", "けいらん"])
        self.assertEqual([i["position"] for i in items], [1, 2, 3])
        self.assertTrue(all("item" in i for i in items[:-1]))


class TestDishPages(unittest.TestCase):
    def _slug(self, own_photo):
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                f"""SELECT sp.slug FROM item_images im
                    JOIN site_pages sp ON sp.item_id = im.item_id AND sp.page_type = 'dish'
                    WHERE im.matched_on {'NOT ' if own_photo else ''}LIKE 'category:%'
                    LIMIT 1""").fetchone()
        except sqlite3.OperationalError:
            row = None
        finally:
            conn.close()
        if not row:
            self.skipTest("no such dish in this database")
        return "/dish/" + row[0]

    def test_a_dish_with_its_own_photograph_is_a_valid_recipe(self):
        blocks = jsonld(self._slug(own_photo=True))
        (recipe,) = of_type(blocks, "Recipe")
        self.assertTrue(recipe["image"].startswith("https://"))
        # Whole-pot totals under servingSize "100 g" were wrong; per serving is unknown.
        self.assertNotIn("nutrition", recipe)
        self.assertTrue(recipe["recipeCuisine"].endswith("の郷土料理"))
        (crumbs,) = of_type(blocks, "BreadcrumbList")
        self.assertTrue(all("item" in i for i in crumbs["itemListElement"][:-1]))
        self.assertIn("/category/", crumbs["itemListElement"][1]["item"])

    def test_a_category_stand_in_is_never_offered_as_the_dish(self):
        blocks = jsonld(self._slug(own_photo=False))
        self.assertEqual(of_type(blocks, "Recipe"), [])
        self.assertEqual(len(of_type(blocks, "BreadcrumbList")), 1)


class TestEveryPageType(unittest.TestCase):
    def test_no_breadcrumb_list_has_a_middle_crumb_without_a_url(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            food = conn.execute(
                "SELECT slug FROM site_pages WHERE page_type = 'food' LIMIT 1").fetchone()
        finally:
            conn.close()
        paths = ["/menu", "/category/青森県", "/nutrients"]
        if food:
            paths.append("/food/" + food[0])
        for path in paths:
            for crumbs in of_type(jsonld(path), "BreadcrumbList"):
                self.assertTrue(all("item" in i for i in crumbs["itemListElement"][:-1]),
                                path)


if __name__ == "__main__":
    unittest.main()
