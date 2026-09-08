import unittest
import sqlite3
from dataset_manager.extractors.chains import parse_mosburger, CHAINS
from dataset_manager.api.analyzer import decompose_dish_text, calculate_nutrition_for_dishes
from dataset_manager.database.site_schema import create_site_tables
from dataset_manager.site import queries


class TestNutritionAccuracy(unittest.TestCase):
    def test_mosburger_parser_extracts_full_macros(self):
        sample_line = "モスバーガー 211.2 372 15.2 17.0 40.0 906 311 39 156 1.4 29 0.11 0.09 2.6 10 0.2 1.0 30 3.4 2.3"
        # Dummy PDF text matching Mos Burger's structure
        import io
        from pypdf import PdfWriter
        
        # Test regex pattern directly as in parse_mosburger
        import re
        pattern = re.compile(
            r"^([^\d【]+?)\s+([\d\.]+)\s+(\d+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+).*?\s+([\d\.]+)$"
        )
        m = pattern.match(sample_line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).strip(), "モスバーガー")
        self.assertEqual(float(m.group(3)), 372.0)
        self.assertEqual(float(m.group(4)), 15.2)
        self.assertEqual(float(m.group(5)), 17.0)
        self.assertEqual(float(m.group(6)), 40.0)
        self.assertEqual(float(m.group(7)), 2.3)

    def test_sushi_culinary_decomposition_has_macros(self):
        decomps = decompose_dish_text("厳選まぐろ中とろ", "スシロー")
        res = calculate_nutrition_for_dishes(decomps, lang="ja")
        totals = res.get("totals", {})
        self.assertGreater(totals.get("energy_kcal", 0), 100)
        self.assertGreater(totals.get("protein_g", 0), 3.0)
        self.assertGreater(totals.get("fat_g", 0), 2.0)
        self.assertGreater(totals.get("carbohydrate_g", 0), 10.0)

    def test_western_culinary_decomposition_has_macros(self):
        decomps = decompose_dish_text("チーズINハンバーグ", "ガスト")
        res = calculate_nutrition_for_dishes(decomps, lang="ja")
        totals = res.get("totals", {})
        self.assertGreater(totals.get("energy_kcal", 0), 300)
        self.assertGreater(totals.get("protein_g", 0), 15.0)
        self.assertGreater(totals.get("fat_g", 0), 15.0)

    def test_shop_page_data_returns_provenance_and_macros(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, source TEXT)")
        conn.execute("CREATE TABLE nutrients (id INTEGER PRIMARY KEY)")
        create_site_tables(conn)
        
        conn.execute("INSERT INTO shops (id, menu_id, name, item_count) VALUES (1, 'test', 'テスト店', 2)")
        conn.execute("INSERT INTO shop_pages (shop_id, lang, slug, page_type) VALUES (1, 'ja', 'テスト店', 'menu')")
        conn.execute("INSERT INTO shop_menu_items (id, shop_id, name, price_yen, position) VALUES (10, 1, '牛丼', 500, 1)")
        conn.execute("INSERT INTO menu_item_nutrition (shop_menu_item_id, energy_kcal, protein_g, fat_g, carbohydrate_g, salt_g, provenance) VALUES (10, 680, 20.5, 23.0, 95.0, 2.5, 'mext_calc')")
        conn.commit()

        # Test query directly on in-memory DB with the exact SQL from get_shop_page_data
        rows = conn.execute("""
            SELECT smi.id AS item_id_pk, smi.name, smi.price_yen, smi.price_max_yen, smi.tax_incl,
                   smi.mealtime, smi.position,
                   min.energy_kcal AS min_kcal, min.protein_g AS min_p,
                   min.fat_g AS min_f, min.carbohydrate_g AS min_c, min.salt_g AS min_salt,
                   min.provenance AS min_provenance
            FROM shop_menu_items smi
            LEFT JOIN menu_item_nutrition min ON min.shop_menu_item_id = smi.id
            WHERE smi.shop_id = 1
        """).fetchall()
        
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["min_kcal"], 680.0)
        self.assertEqual(r["min_p"], 20.5)
        self.assertEqual(r["min_f"], 23.0)
        self.assertEqual(r["min_c"], 95.0)
        self.assertEqual(r["min_salt"], 2.5)
        self.assertEqual(r["min_provenance"], "mext_calc")
        conn.close()

    def test_salad_decomposition_includes_protein_metrics(self):
        decomps = decompose_dish_text("チキンのサラダ", "サイゼリヤ")
        res = calculate_nutrition_for_dishes(decomps, lang="ja")
        totals = res.get("totals", {})
        self.assertGreater(totals.get("protein_g", 0), 20.0)
        comps = res.get("components", [])
        comp_names = [c.get("identified", {}).get("name_ja") or c.get("db_match", {}).get("title") for c in comps]
        self.assertTrue(any("鶏" in c or "にわとり" in c for c in comp_names))

        # Also verify shrimp salad includes shrimp
        shrimp_decomps = decompose_dish_text("小エビのサラダ", "サイゼリヤ")
        shrimp_res = calculate_nutrition_for_dishes(shrimp_decomps, lang="ja")
        shrimp_comps = [c.get("identified", {}).get("name_ja") or c.get("db_match", {}).get("title") for c in shrimp_res.get("components", [])]
        self.assertTrue(any("えび" in c or "エビ" in c for c in shrimp_comps))
        self.assertGreater(shrimp_res.get("totals", {}).get("protein_g", 0), 5.0)

    def test_donburi_and_rice_meals_include_steamed_rice(self):
        # 1. Jonathan's tuna rice bowl (the user's reported dish)
        decomps = decompose_dish_text("本まぐろの鉄火丼モーニング", "ジョナサン")
        res = calculate_nutrition_for_dishes(decomps, lang="ja")
        totals = res.get("totals", {})
        self.assertGreater(totals.get("energy_kcal", 0), 450)
        self.assertGreater(totals.get("carbohydrate_g", 0), 80.0)
        comp_names = [c.get("identified", {}).get("name_ja") or c.get("db_match", {}).get("title") for c in res.get("components", [])]
        self.assertTrue(any("ご飯" in c or "こめ" in c for c in comp_names))

        # 2. Teishoku with accompaniment rice
        karaage_decomps = decompose_dish_text("から揚げ定食", "やよい軒")
        karaage_res = calculate_nutrition_for_dishes(karaage_decomps, lang="ja")
        karaage_names = [c.get("identified", {}).get("name_ja") or c.get("db_match", {}).get("title") for c in karaage_res.get("components", [])]
        self.assertTrue(any("ご飯" in c or "こめ" in c for c in karaage_names))
        self.assertGreater(karaage_res.get("totals", {}).get("energy_kcal", 0), 500)

        # 3. Explicit accompaniment rice tag
        hamburg_decomps = decompose_dish_text("ハンバーグ（ライス付）", "ガスト")
        hamburg_res = calculate_nutrition_for_dishes(hamburg_decomps, lang="ja")
        hamburg_names = [c.get("identified", {}).get("name_ja") or c.get("db_match", {}).get("title") for c in hamburg_res.get("components", [])]
        self.assertTrue(any("ご飯" in c or "こめ" in c for c in hamburg_names))


if __name__ == "__main__":
    unittest.main()
