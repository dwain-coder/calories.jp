import sqlite3
import unittest

from dataset_manager.extractors.chains import (
    Chain,
    _find_date,
    chain_status,
    import_chain,
    kcal_table_parser,
    name_key,
)
from dataset_manager.extractors.menus import import_menus
from dataset_manager.scripts.build_shops import MIN_ITEMS, MIN_RESOLVED_SHARE, gate

HEADER = ("menu_id,item_id,restaurant_name,item_name,price,price_tax_incl,"
          "currency,description,menu_image,menu_all_pages\n")


def menu_csv(*rows):
    return HEADER + "".join(r + "\n" for r in rows)


def fake_chain(published, shop_name="テスト寿司"):
    """A Chain whose 'download' returns rows directly — no network in tests."""
    return Chain(
        key="test",
        shop_name=shop_name,
        url="https://example.invalid/nutrition.pdf",
        source_page="https://example.invalid/allergen/",
        parser=lambda blob: (published, "2026-09-02"),
    )


class TestNameKey(unittest.TestCase):
    def test_spacing_and_bracketed_notes_do_not_block_a_join(self):
        self.assertEqual(name_key("えび天握り おろし盛り"), name_key("えび天握りおろし盛り"))
        self.assertEqual(name_key("（関西限定）炙りサーモン"), name_key("炙りサーモン"))


class TestImportChain(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, source TEXT)")
        self.conn.execute("CREATE TABLE nutrients (id INTEGER PRIMARY KEY)")
        import_menus(self.conn, menu_csv(
            "NVM1,NVI1,テスト寿司,まぐろ,132,,JPY,,,",
            "NVM1,NVI2,テスト寿司,えび天握り おろし盛り,176,,JPY,,,",
            "NVM1,NVI3,テスト寿司,コーヒーゼリー,143,,JPY,,,",
            "NVM1,NVI4,テスト寿司,季節の新商品,200,,JPY,,,",
        ), imported_at="2026-08-26")

    def tearDown(self):
        self.conn.close()

    def test_links_by_exact_name_and_by_normalised_name(self):
        stats = import_chain(self.conn, fake_chain([
            {"name": "まぐろ", "energy_kcal": 83.0},
            {"name": "えび天握りおろし盛り", "energy_kcal": 124.0},
        ]), opener=lambda url: b"")
        self.assertEqual(stats["linked"], 2)
        self.assertEqual(stats["linked_exact"], 1)      # まぐろ
        self.assertEqual(stats["source_updated"], "2026-09-02")

    def test_an_ambiguous_normalised_name_is_refused_not_guessed(self):
        # Two published products collapse to the same key once the bracketed note
        # is stripped, and they have different calories. Guessing one would print
        # a wrong number; the dish must be left without a figure.
        stats = import_chain(self.conn, fake_chain([
            {"name": "コーヒーゼリー(バニラアイスのせ)", "energy_kcal": 149.0},
            {"name": "コーヒーゼリー(ホイップ)", "energy_kcal": 210.0},
        ]), opener=lambda url: b"")
        self.assertEqual(stats["linked"], 0)
        self.assertEqual(stats["ambiguous_skipped"], 1)

    def test_every_figure_carries_its_source(self):
        # The site's rule: a number a reader cannot trace back does not ship.
        import_chain(self.conn, fake_chain([{"name": "まぐろ", "energy_kcal": 83.0}]),
                     opener=lambda url: b"")
        rows = self.conn.execute(
            "SELECT energy_kcal, source_url, source_page, source_updated, fetched_at "
            "FROM chain_nutrition").fetchall()
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNotNone(row[0])
            for provenance in row[1:]:
                self.assertTrue(provenance, "a figure was stored without provenance")

    def test_a_dish_the_chain_does_not_publish_gets_no_figure(self):
        import_chain(self.conn, fake_chain([{"name": "まぐろ", "energy_kcal": 83.0}]),
                     opener=lambda url: b"")
        unlinked = self.conn.execute(
            "SELECT name FROM shop_menu_items WHERE chain_nutrition_id IS NULL").fetchall()
        self.assertIn(("季節の新商品",), unlinked)

    def test_reimport_replaces_figures_rather_than_duplicating_them(self):
        chain = fake_chain([{"name": "まぐろ", "energy_kcal": 83.0}])
        import_chain(self.conn, chain, opener=lambda url: b"")
        import_chain(self.conn, chain, opener=lambda url: b"")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM chain_nutrition").fetchone()[0], 1)

    def test_refuses_a_chain_with_no_shop_in_the_corpus(self):
        with self.assertRaises(ValueError):
            import_chain(self.conn, fake_chain([], shop_name="存在しない店"),
                         opener=lambda url: b"")


class TestRefresh(unittest.TestCase):
    """A refresh must SAY what the chain moved. A silent overwrite of a calorie is
    the one way a wrong figure can reach a reader through this design."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, source TEXT)")
        self.conn.execute("CREATE TABLE nutrients (id INTEGER PRIMARY KEY)")
        import_menus(self.conn, menu_csv(
            "NVM1,NVI1,テスト寿司,まぐろ,132,,JPY,,,",
            "NVM1,NVI2,テスト寿司,えび,110,,JPY,,,",
        ), imported_at="2026-08-26")

    def tearDown(self):
        self.conn.close()

    def test_first_import_is_not_reported_as_a_change(self):
        stats = import_chain(self.conn, fake_chain([{"name": "まぐろ", "energy_kcal": 83.0}]),
                             opener=lambda url: b"")
        self.assertTrue(stats["was_empty"])
        self.assertEqual(stats["changed"], [])

    def test_a_revised_calorie_is_reported_with_both_values(self):
        import_chain(self.conn, fake_chain([{"name": "まぐろ", "energy_kcal": 83.0}]),
                     opener=lambda url: b"")
        stats = import_chain(self.conn, fake_chain([{"name": "まぐろ", "energy_kcal": 91.0}]),
                             opener=lambda url: b"")
        self.assertFalse(stats["was_empty"])
        self.assertEqual(stats["changed"], [("まぐろ", 83.0, 91.0)])

    def test_added_and_withdrawn_dishes_are_reported(self):
        import_chain(self.conn, fake_chain([{"name": "まぐろ", "energy_kcal": 83.0}]),
                     opener=lambda url: b"")
        stats = import_chain(self.conn, fake_chain([{"name": "えび", "energy_kcal": 74.0}]),
                             opener=lambda url: b"")
        self.assertEqual(stats["added"], ["えび"])
        self.assertEqual(stats["removed"], ["まぐろ"])

    def test_status_reports_what_we_hold_and_when_we_fetched_it(self):
        import_chain(self.conn, fake_chain([{"name": "まぐろ", "energy_kcal": 83.0}]),
                     opener=lambda url: b"", fetched_at="2026-09-06")
        rows = chain_status(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chain"], "テスト寿司")
        self.assertEqual(rows[0]["figures"], 1)
        self.assertEqual(rows[0]["fetched_at"], "2026-09-06")
        self.assertIsNotNone(rows[0]["days_since_fetch"])


class TestKcalTableParser(unittest.TestCase):
    """The row grammar the chains' PDFs share, exercised on text rather than PDFs
    so a chain's layout change shows up as a failing case, not a silent zero."""

    def rows(self, text, **kw):
        parse = kcal_table_parser(**kw)
        # The parser reads pages; feed it text through a stub reader.
        import unittest.mock as mock
        page = mock.Mock()
        page.extract_text.return_value = text
        reader = mock.Mock()
        reader.pages = [page]
        with mock.patch("pypdf.PdfReader", return_value=reader):
            return parse(b"")

    def test_fixed_column_layout(self):
        # はま寿司 prints a symbol for every one of the 28 allergens.
        flags = " ".join(["●"] * 28)
        rows, _ = self.rows(f"大切りうなぎ握り 148 {flags}", symbols="●-△ー", exact_columns=28)
        self.assertEqual(rows, [{"name": "大切りうなぎ握り", "energy_kcal": 148.0}])

    def test_variable_column_layout_including_none_at_all(self):
        # くら寿司 prints only the allergens that apply — sometimes none.
        rows, _ = self.rows("あじ 85" + chr(10) + "味玉 140 ● ● ▲", symbols="●▲△")
        self.assertEqual([r["name"] for r in rows], ["あじ", "味玉"])
        self.assertEqual([r["energy_kcal"] for r in rows], [85.0, 140.0])

    def test_a_name_ending_in_a_number_keeps_its_number(self):
        # 「たこ焼き(6個) 388」 must not parse as 「たこ焼き(」 at 6 kcal.
        rows, _ = self.rows("たこ焼き 6個 388", symbols="●▲△")
        self.assertEqual(rows, [{"name": "たこ焼き 6個", "energy_kcal": 388.0}])

    def test_prose_and_headings_are_not_read_as_dishes(self):
        rows, _ = self.rows(chr(10).join(["定番寿司", "2026年9月4日現在", "アレルゲン一覧表"]), symbols="●▲△")
        self.assertEqual(rows, [])

    def test_an_implausible_figure_is_a_parse_artefact_not_a_calorie(self):
        rows, _ = self.rows("表番号 99999", symbols="●▲△")
        self.assertEqual(rows, [])

    def test_reads_both_date_conventions(self):
        self.assertEqual(_find_date("アレルゲン一覧表(店内)　 更新日 2026/9/2"), "2026-09-02")
        self.assertEqual(_find_date("2026年9月4日現在"), "2026-09-04")
        self.assertIsNone(_find_date("no date here"))


class TestGate(unittest.TestCase):
    def test_a_thin_menu_never_becomes_indexable(self):
        ok, why = gate({"items": MIN_ITEMS - 1, "resolved": MIN_ITEMS - 1, "priced": 5})
        self.assertFalse(ok)
        self.assertIn("dishes", why)

    def test_a_menu_reprint_without_calories_is_refused(self):
        # The whole point: a page that adds no sourced figure is the page that
        # got kalori.jp's menu pages deindexed.
        ok, _ = gate({"items": 100, "resolved": 5, "priced": 100})
        self.assertFalse(ok)

    def test_a_menu_with_enough_sourced_calories_passes(self):
        ok, why = gate({"items": 100, "resolved": int(100 * MIN_RESOLVED_SHARE) + 1,
                        "priced": 100})
        self.assertTrue(ok)
        self.assertIn("sourced nutrition", why)

    def test_no_price_is_refused(self):
        ok, _ = gate({"items": 100, "resolved": 100, "priced": 0})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
