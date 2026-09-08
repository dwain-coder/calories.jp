import sqlite3
import unittest

from dataset_manager.extractors.menus import import_menus, read_rows
from dataset_manager.validators.menus import (
    collapse_duplicates,
    is_non_food,
    is_section_label,
    mealtime_of,
    price_of,
)

HEADER = ("menu_id,item_id,restaurant_name,item_name,price,price_tax_incl,"
          "currency,description,menu_image,menu_all_pages\n")


def csv(*rows):
    return HEADER + "".join(r + "\n" for r in rows)


class TestPrice(unittest.TestCase):
    def test_prefers_tax_included_when_it_is_plausible(self):
        self.assertEqual(price_of("1680", "1848"), (1848, True))

    def test_keeps_the_decimal_point(self):
        # "1848.0" with the dot stripped is 18480 — a silent tenfold price rise.
        self.assertEqual(price_of("1680", "1848.0"), (1848, True))

    def test_rejects_a_tax_included_price_below_the_listed_one(self):
        # ~108 rows carry a garbage small number. Tax-included is never lower.
        self.assertEqual(price_of("957", "3"), (957, False))

    def test_no_usable_price_is_none_not_zero(self):
        self.assertEqual(price_of("", ""), (None, False))
        self.assertEqual(price_of("時価", ""), (None, False))
        self.assertEqual(price_of("0", "0"), (None, False))


class TestRejections(unittest.TestCase):
    def test_packaging_is_not_a_dish(self):
        self.assertTrue(is_non_food("紙コップ"))
        self.assertTrue(is_non_food("容器代"))
        self.assertFalse(is_non_food("餃子"))

    def test_menu_headings_are_not_restaurants(self):
        self.assertTrue(is_section_label("グランドメニュー"))
        self.assertTrue(is_section_label("ドリンク"))
        self.assertFalse(is_section_label("餃子の王将"))

    def test_mealtime_is_a_guess_that_may_decline(self):
        self.assertEqual(mealtime_of("生ビール"), "drinks")
        self.assertEqual(mealtime_of("朝食セット"), "breakfast")
        self.assertIsNone(mealtime_of("餃子"))


class TestDuplicates(unittest.TestCase):
    def test_disagreeing_prices_become_a_span_not_a_pick(self):
        rows = [
            {"name": "餃子", "mealtime": None, "price_yen": 800, "price_max_yen": None},
            {"name": "餃子", "mealtime": None, "price_yen": 2000, "price_max_yen": None},
        ]
        out = collapse_duplicates(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["price_yen"], out[0]["price_max_yen"]), (800, 2000))

    def test_an_exact_repeat_passes_through_unchanged(self):
        rows = [
            {"name": "餃子", "mealtime": None, "price_yen": 800, "price_max_yen": None},
            {"name": "餃子", "mealtime": None, "price_yen": 800, "price_max_yen": None},
        ]
        out = collapse_duplicates(rows)
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["price_max_yen"])


class TestReadRows(unittest.TestCase):
    def test_counts_every_rejection(self):
        text = csv(
            "NVM1,NVI1,餃子の王将,餃子,290,,JPY,焼き餃子,,",
            "NVM1,NVI2,餃子の王将,紙コップ,50,,JPY,,,",       # non-food
            "NVM1,NVI3,餃子の王将,,290,,JPY,,,",              # blank name
            "NVM2,NVI4,ドリンクメニュー,生ビール,500,,JPY,,,",  # section label
        )
        shops, stats = read_rows(text)
        self.assertEqual([s["menu_id"] for s in shops], ["NVM1"])
        self.assertEqual(stats["non_food"], 1)
        self.assertEqual(stats["blank"], 1)
        self.assertEqual(stats["section_label"], 1)

    def test_scraped_descriptions_never_survive_the_parse(self):
        shops, _ = read_rows(csv("NVM1,NVI1,店,餃子,290,,JPY,秘伝のタレで仕上げた自慢の一品,,"))
        item = shops[0]["items"][0]
        self.assertNotIn("desc", item)
        self.assertNotIn("秘伝", repr(item))

    def test_a_missing_column_is_an_error_not_an_empty_import(self):
        with self.assertRaises(ValueError):
            read_rows("menu_id,item_name\nNVM1,餃子\n")


class TestImport(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        # The corpus tables create_site_tables indexes/migrates against. Minimal
        # stand-ins: this test is about the menu import, not the composition data.
        self.conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, source TEXT)")
        self.conn.execute("CREATE TABLE nutrients (id INTEGER PRIMARY KEY)")
        self.conn.execute("INSERT INTO items (id, source) VALUES (1, 'MEXT Standard Tables')")

    def tearDown(self):
        self.conn.close()

    def test_imports_and_is_idempotent(self):
        text = csv("NVM1,NVI1,店,餃子,290,,JPY,,,", "NVM1,NVI2,店,ラーメン,700,,JPY,,,")
        first = import_menus(self.conn, text, imported_at="2026-08-01")
        second = import_menus(self.conn, text, imported_at="2026-08-01")
        self.assertEqual((first["shops"], first["items"]), (1, 2))
        self.assertEqual((second["shops"], second["items"]), (1, 2))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM shop_menu_items").fetchone()[0], 2)

    def test_a_reimport_keeps_matches_already_resolved(self):
        text = csv("NVM1,NVI1,店,餃子,290,,JPY,,,")
        import_menus(self.conn, text, imported_at="2026-08-01")
        self.conn.execute(
            "UPDATE shop_menu_items SET item_id = 1, match_confidence = 0.9, match_method = 'exact'")
        self.conn.commit()
        stats = import_menus(self.conn, text, imported_at="2026-08-01")
        self.assertEqual(stats["matches_kept"], 1)
        row = self.conn.execute(
            "SELECT item_id, match_method FROM shop_menu_items").fetchone()
        self.assertEqual(row, (1, "exact"))

    def test_shop_pages_are_not_indexable_by_default(self):
        # A shop page must EARN its index slot in build_shops; the schema default
        # is the backstop if a builder ever forgets to set it.
        import_menus(self.conn, csv("NVM1,NVI1,店,餃子,290,,JPY,,,"), imported_at="2026-08-01")
        self.conn.execute(
            """INSERT INTO shop_pages (shop_id, lang, slug, page_type)
               VALUES ((SELECT id FROM shops LIMIT 1), 'ja', 'ten', 'shop')""")
        self.assertEqual(
            self.conn.execute("SELECT indexable FROM shop_pages").fetchone()[0], 0)

    def test_price_range_is_the_shops_real_span(self):
        text = csv("NVM1,NVI1,店,餃子,290,,JPY,,,", "NVM1,NVI2,店,ラーメン,700,,JPY,,,")
        import_menus(self.conn, text, imported_at="2026-08-01")
        self.assertEqual(
            self.conn.execute("SELECT price_min, price_max FROM shops").fetchone(), (290, 700))


if __name__ == "__main__":
    unittest.main()


class TestNotADish(unittest.TestCase):
    """A glass of water and a side of mustard are on the menu but are not what
    anyone came to count."""

    def test_add_ons_and_condiments_are_dropped(self):
        from dataset_manager.site import menuterms
        for name in ("トッピング 角煮", "追加 チーズ", "追加ソース", "替玉", "麺大盛",
                     "ソース", "ドレッシング", "わさび", "ガリ", "お冷", "ミルク"):
            self.assertTrue(menuterms.is_extra(name), name)

    def test_a_dish_that_merely_mentions_a_sauce_is_kept(self):
        """The reason the rules match a whole name and not a substring."""
        from dataset_manager.site import menuterms
        for name in ("豚骨醤油ラーメン", "濃厚渡り蟹のトマトクリームソース 生パスタランチ",
                     "自家製ハンバーグガーリックトマトソース", "元祖辛子明太子",
                     "US産リブアイステーキ 自家製醤油ソース [200g]"):
            self.assertFalse(menuterms.is_extra(name), name)

    def test_drinks_go_by_their_category(self):
        from dataset_manager.site import menuterms
        from dataset_manager.site.brand_assets import classify_dish_visual
        for name in ("生ビール", "アイスコーヒー", "コーラ", "ウーロン茶"):
            self.assertTrue(menuterms.is_drink(name, classify_dish_visual(name)["category"]), name)
        for name in ("ハンバーグ", "醤油らーめん", "茶碗蒸し"):
            self.assertFalse(menuterms.is_drink(name, classify_dish_visual(name)["category"]), name)


class TestDishNameIsRead(unittest.TestCase):
    """The estimator matched one keyword and ignored the rest of the name, so
    a 145g burger, its 110g sibling and a ダブル220g all cost 432.5 kcal, and a
    plate with shrimp on it cost the same as the plate without."""

    def _kcal(self, name):
        from dataset_manager.api.analyzer import (
            decompose_dish_text, calculate_nutrition_for_dishes)
        res = calculate_nutrition_for_dishes(decompose_dish_text(name), lang="ja")
        return res["totals"].get("energy_kcal"), res

    def test_a_stated_weight_changes_the_figure(self):
        small, _ = self._kcal("濃厚ビーフシチューの包み焼きハンバーグ110g")
        large, _ = self._kcal("濃厚ビーフシチューの包み焼きハンバーグ145g")
        self.assertGreater(large, small)
        self.assertGreater(large - small, 50)

    def test_the_stated_weight_reaches_the_main_component(self):
        from dataset_manager.api.analyzer import decompose_dish_text
        comps = decompose_dish_text("US産リブアイステーキ 自家製醤油ソース [300G]")[0]["components"]
        beef = [c for c in comps if c["name_ja"] == "牛肉"]
        self.assertEqual(beef[0]["estimated_grams"], 300.0)

    def test_a_garnish_weight_is_not_read_as_a_portion(self):
        from dataset_manager.api.analyzer import _stated_grams
        self.assertIsNone(_stated_grams("薬味 5g"))          # too small to be a portion
        self.assertIsNone(_stated_grams("大俵ハンバーグ"))      # says nothing
        self.assertEqual(_stated_grams("ステーキ 200g"), 200.0)

    def test_both_halves_of_a_combined_dish_are_counted(self):
        plain, _ = self._kcal("大俵ハンバーグ")
        combo, _ = self._kcal("大俵ハンバーグ＆エビフライ")
        self.assertGreater(combo, plain)

    def test_a_stated_weight_is_left_alone_when_it_names_one_of_two_dishes(self):
        """「…＆手ごねハンバーグ100g」 states 100 g about the second patty; applying
        it to the merged pair turned two burgers into one small one."""
        both, _ = self._kcal("大俵ハンバーグ＆手ごねハンバーグ100g")
        one, _ = self._kcal("大俵ハンバーグ")
        self.assertGreater(both, one)

    def test_a_dish_that_cannot_be_fully_costed_reports_it(self):
        """The shrimp resolves to no table row, so the total would be the
        burger's alone. precompute_nutrition refuses to store that."""
        _, res = self._kcal("殻付き海老グリル＆大俵ハンバーグ")
        self.assertTrue(res.get("unmatched"))
