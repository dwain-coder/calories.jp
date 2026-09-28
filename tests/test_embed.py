"""Widgets for someone else's page.

The site refuses to be framed everywhere else, so the routes that exist to be
framed are the one place that has to be checked deliberately. And a widget is
only worth handing out if the page it lands on links back: a link inside the
frame belongs to our own noindex document, so the citation that counts is the
one the snippet puts under the frame.
"""
import html
import re
import unittest
from urllib.parse import quote

from fastapi.testclient import TestClient

from dataset_manager.api.server import app
from dataset_manager.site import embeds
from dataset_manager.site.router import (EXAMPLE_CHAIN, EXAMPLE_COMPARE, EXAMPLE_FOOD,
                                          EXAMPLE_NUTRIENT)

client = TestClient(app)
BASE = "https://calories.jp"
FOOD, OTHER, CHAIN = quote(EXAMPLE_FOOD), quote(EXAMPLE_COMPARE), quote(EXAMPLE_CHAIN)

# Each widget, and the page it duplicates and must point back to. A comparison
# duplicates two pages; its canonical is the first and its citation names both.
WIDGETS = {
    "/embed/analyzer": "/analyzer",
    f"/embed/food/{FOOD}": f"/food/{FOOD}",
    f"/embed/compare/{FOOD}/{OTHER}": f"/food/{FOOD}",
    f"/embed/nutrient/{EXAMPLE_NUTRIENT}": f"/nutrient/{EXAMPLE_NUTRIENT}",
    f"/embed/menu/{CHAIN}": f"/menu/{CHAIN}",
    f"/embed/menu/{CHAIN}/protein": f"/menu/{CHAIN}",
    "/embed/cooking-yield": "/cooking-yield",
}


def snippets(page_html):
    """The code boxes on a page, as the text a reader copies."""
    return [html.unescape(code) for code in re.findall(
        r'<pre class="api-example" id="[^"]+"><code>(.*?)</code></pre>', page_html, re.S)]


class TestFraming(unittest.TestCase):
    def test_every_widget_may_be_framed(self):
        for path in WIDGETS:
            with self.subTest(path=path):
                r = client.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertIsNone(r.headers.get("X-Frame-Options"))
                self.assertIn("frame-ancestors *", r.headers["Content-Security-Policy"])

    def test_the_rest_of_the_site_still_refuses(self):
        for path in ("/", "/analyzer", "/column", "/menu", f"/food/{quote(EXAMPLE_FOOD)}"):
            h = client.get(path).headers
            self.assertEqual(h.get("X-Frame-Options"), "DENY", path)
            self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"], path)

    def test_the_other_protections_still_apply_to_the_embed(self):
        """Only the framing ban is lifted, not the rest of the policy."""
        h = client.get("/embed/analyzer").headers
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
        csp = h["Content-Security-Policy"]
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'self'", csp)


class TestEmbedContent(unittest.TestCase):
    def test_no_widget_competes_with_the_page_it_duplicates(self):
        for path, page in WIDGETS.items():
            with self.subTest(path=path):
                body = client.get(path).text
                self.assertIn("noindex,nofollow", body)
                self.assertIn(f'rel="canonical" href="{BASE}{page}"', body)

    def test_each_widget_says_where_its_numbers_came_from(self):
        """A widget on someone else's site that does not name its source is
        exactly what this site does not publish."""
        for path, page in WIDGETS.items():
            with self.subTest(path=path):
                self.assertIn(f'href="{BASE}{page}" target="_blank"', client.get(path).text)

    def test_no_widget_carries_site_chrome(self):
        for path in WIDGETS:
            with self.subTest(path=path):
                body = client.get(path).text
                self.assertNotIn("site-header", body)
                self.assertNotIn("site-footer", body)

    def test_every_widget_says_what_its_figures_are_and_are_not(self):
        """A number on someone else's page, without our site around it, needs
        its caveat in the frame: what kind of figure it is, that it is not
        advice, and where the full terms are."""
        from dataset_manager.site.i18n import t
        expected = {"/embed/analyzer": "api_terms_estimates", "/embed/cooking-yield": "embed_disc_yield"}
        for path in WIDGETS:
            kind = expected.get(path, "embed_disc_chain" if "/menu/" in path else "embed_disc_food")
            with self.subTest(path=path):
                body = client.get(path).text
                self.assertIn(t("ja", kind), body)
                self.assertIn(t("ja", "embed_disc_advice"), body)
                self.assertIn(f'href="{BASE}/terms"', body)

    def test_every_widget_reports_its_height(self):
        """An iframe cannot size itself; without this the widget is clipped."""
        for path in WIDGETS:
            with self.subTest(path=path):
                self.assertIn("postMessage", client.get(path).text)

    def test_the_converter_survives_its_move_into_a_partial(self):
        body = client.get("/embed/cooking-yield").text
        self.assertIn('var raw = dir === "forward" ? g : g * 100 / rate;', body)
        self.assertNotIn('id="yield-table"', body)   # the 497-row table stays on the page

    def test_every_menu_figure_carries_its_label(self):
        """The menu page never shows a calorie without the rung it stands on,
        and a widget of the same rows must not either."""
        body = client.get(f"/embed/menu/{quote(EXAMPLE_CHAIN)}").text
        rows = re.findall(r"<tr><td class=\"rank-num\">.*?</tr>", body, re.S)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("prov-tag", row)
        kcals = [int(k) for k in re.findall(r"<strong>(\d+)</strong> <small>kcal", body)]
        self.assertEqual(kcals, sorted(kcals))

    def test_the_protein_list_runs_the_other_way(self):
        body = client.get(f"/embed/menu/{CHAIN}/protein").text
        grams = [float(g) for g in re.findall(r"<strong>([\d.]+)</strong> <small>g", body)]
        self.assertEqual(len(grams), 10)
        self.assertEqual(grams, sorted(grams, reverse=True))

    def test_a_comparison_shows_both_foods_on_one_basis(self):
        body = client.get(f"/embed/compare/{FOOD}/{OTHER}").text
        self.assertEqual(body.count('<th class="wrap">'), 2)
        self.assertIn("100gあたり", body)

    def test_nothing_is_offered_for_a_page_search_engines_will_not_index(self):
        """A citation pointing at a noindex page is a link to nowhere."""
        self.assertEqual(client.get("/embed/menu/" + quote("8番らーめん")).status_code, 404)
        self.assertNotIn("embed-offer", client.get("/menu/" + quote("8番らーめん")).text)
        self.assertEqual(client.get("/embed/nutrient/no-such-thing").status_code, 404)
        self.assertEqual(client.get("/embed/food/no-such-food").status_code, 404)
        self.assertEqual(client.get(f"/embed/compare/{FOOD}/no-such-food").status_code, 404)

    def test_a_list_the_chain_cannot_support_is_not_served(self):
        """ガスト publishes calories but not protein. A protein ranking of it
        could only be built from our estimates."""
        self.assertEqual(client.get("/embed/menu/" + quote("ガスト") + "/protein").status_code, 404)
        self.assertEqual(client.get(f"/embed/compare/{FOOD}/{FOOD}").status_code, 404)


class TestTheSnippetsLinkBack(unittest.TestCase):
    """What a writer pastes is what earns the link, so check the pasted text."""

    @classmethod
    def setUpClass(cls):
        cls.index = client.get("/embed").text
        cls.codes = snippets(cls.index)

    def test_every_widget_is_on_the_index(self):
        for path in WIDGETS:
            with self.subTest(path=path):
                self.assertTrue(any(f'src="{BASE}{path}"' in c for c in self.codes), path)

    def test_the_link_is_outside_the_frame_and_names_the_page(self):
        for path, page in WIDGETS.items():
            with self.subTest(path=path):
                code = next(c for c in self.codes if f'src="{BASE}{path}"' in c)
                link = code.index(f'<a href="{BASE}{page}">')
                self.assertGreater(link, code.index("</iframe>"))
                self.assertIn(f'>calories.jp「', code[link:])

    def test_a_comparison_cites_both_foods(self):
        code = next(c for c in self.codes if "/embed/compare/" in c)
        after = code[code.index("</iframe>"):]
        self.assertIn(f'<a href="{BASE}/food/{FOOD}">', after)
        self.assertIn(f'<a href="{BASE}/food/{OTHER}">', after)

    def test_the_link_is_an_ordinary_visible_link(self):
        """nofollow or a hidden link would give up exactly what the snippet is for;
        a hidden one is also what search engines penalise."""
        for code in self.codes:
            self.assertNotIn("nofollow", code)
            self.assertNotIn("display:none", code.replace(" ", ""))

    def test_the_host_page_checks_who_is_resizing_what(self):
        """Any page can postMessage to a host. The snippet should not resize
        itself on a stranger's say-so, nor stretch the wrong frame when a post
        carries two widgets."""
        for code in (c for c in self.codes if "<iframe" in c):
            self.assertIn(f'e.origin !== "{BASE}"', code)
            self.assertIn("contentWindow === e.source", code)

    def test_the_search_box_needs_neither_a_frame_nor_a_script(self):
        box = embeds.search_box()
        self.assertIn(box, self.codes)
        self.assertNotIn("<iframe", box)
        self.assertNotIn("<script", box)
        self.assertIn(f'action="{BASE}/search"', box)
        self.assertIn('name="q"', box)
        # The home page gets the bare name, not a phrase repeated on every blog.
        self.assertIn(f'<a href="{BASE}/">calories.jp</a>', box)

    def test_the_documented_rate_limit_is_the_enforced_one(self):
        from dataset_manager.api import analyzer
        self.assertIn(str(analyzer.RATE_LIMIT), self.index)


class TestTheCodeIsOfferedWhereTheFiguresAre(unittest.TestCase):
    def test_each_page_offers_its_own_widget(self):
        for path, page in WIDGETS.items():
            if path == "/embed/analyzer" or "/compare/" in path:
                continue    # no page of their own; see the builder tests below
            with self.subTest(page=page):
                codes = snippets(client.get(page).text)
                self.assertTrue(any(f'src="{BASE}{path}"' in c for c in codes), page)

    def test_a_food_page_also_offers_plain_html(self):
        """Many blogs strip iframes. The table form works there, and puts the
        figures in the writer's own page with the citation under them."""
        codes = snippets(client.get(f"/food/{quote(EXAMPLE_FOOD)}").text)
        table = next(c for c in codes if c.startswith("<table>"))
        self.assertNotIn("<iframe", table)
        self.assertIn(f'<a href="{BASE}/food/{quote(EXAMPLE_FOOD)}">', table)
        # Pasted HTML never updates, so its caveat has to be in the paste.
        from dataset_manager.site.i18n import t
        self.assertIn(t("ja", "embed_disc_html"), table)


class TestTheMenuRanking(unittest.TestCase):
    def test_a_qualifier_does_not_hide_a_topping(self):
        """ガスト lists its add-ons as 「【お料理ご注文のお客様限定】［追加］ケチャップ」;
        read as a dish, a ketchup sachet topped its lowest-calorie list."""
        from dataset_manager.site import menuterms
        for name in ("【お料理ご注文のお客様限定】［追加］ケチャップ",
                     "【お料理ご注文のお客様限定】[追加]にんにく醤油ソース",
                     "【お料理ご注文のお客様限定】トッピング 生ハム"):
            self.assertTrue(menuterms.is_extra(menuterms.unqualified(name)), name)
        for name in ("【期間限定】ハンバーグ", "ゴロゴロ野菜サラダ"):
            self.assertFalse(menuterms.is_extra(menuterms.unqualified(name)), name)

    MENU = [{"name": "チキンのトマト煮込み", "kcal": 30, "protein_g": 40, "kcal_source": "mext_calc"},
            {"name": "【限定】トッピング 生ハム", "kcal": 11, "protein_g": 3, "kcal_source": "chain"},
            {"name": "味噌汁", "kcal": 28, "protein_g": 2.1, "kcal_source": "chain"},
            {"name": "ロースかつ定食", "kcal": 980, "protein_g": 38.5, "kcal_source": "chain"},
            {"name": "ごはん", "kcal": 156, "protein_g": 2.5, "kcal_source": "table"},
            {"name": "未公表の皿", "kcal": None, "protein_g": None, "kcal_source": None}]

    def test_it_ranks_only_what_the_chain_published(self):
        """Not our estimates — sorting by one floats its worst errors to the
        top — and not a composition-table figure, which is per 100 g and
        cannot be ranked against a whole dish."""
        from dataset_manager.site.router import menu_ranked
        self.assertEqual([m["name"] for m in menu_ranked(self.MENU)], ["味噌汁", "ロースかつ定食"])
        self.assertEqual([m["name"] for m in menu_ranked(self.MENU, "protein")],
                         ["ロースかつ定食", "味噌汁"])


class TestTheBuilders(unittest.TestCase):
    """/embed builds the code for any food, pair, nutrient or chain."""

    def code(self, query, key):
        body = client.get("/embed", params=query).text
        return [c for c in snippets(body) if f"/embed/{key}" in c], body

    def test_any_two_foods(self):
        codes, _ = self.code({"a": EXAMPLE_COMPARE, "b": EXAMPLE_FOOD}, "compare")
        self.assertIn(f'src="{BASE}/embed/compare/{OTHER}/{FOOD}"', codes[0])

    def test_typed_text_finds_a_food_without_javascript(self):
        codes, _ = self.code({"food_q": "ぶた"}, "food/")
        self.assertTrue(codes)
        self.assertNotIn(f"/embed/food/{FOOD}", codes[0])

    def test_text_typed_over_a_choice_goes_by_the_text(self):
        """Without JavaScript the hidden slug still holds the old choice."""
        codes, _ = self.code({"food": EXAMPLE_FOOD, "food_q": "ぶた"}, "food/")
        self.assertNotIn(f"/embed/food/{FOOD}", codes[0])

    def test_a_pair_of_one_food_is_not_a_comparison(self):
        codes, _ = self.code({"a": EXAMPLE_FOOD, "b": EXAMPLE_FOOD}, "compare")
        self.assertIn(f"/embed/compare/{FOOD}/{OTHER}", codes[0])

    def test_any_nutrient(self):
        codes, _ = self.code({"nutrient": "fat"}, "nutrient")
        self.assertIn(f'src="{BASE}/embed/nutrient/fat"', codes[0])

    def test_a_chain_without_protein_figures_says_so(self):
        codes, body = self.code({"chain": "ガスト", "rank": "protein"}, "menu")
        self.assertEqual(len(codes), 1)
        self.assertIn("/embed/menu/" + quote("ガスト") + '"', codes[0])
        self.assertIn("たんぱく質を公表していない", body)

    def test_nonsense_falls_back_to_the_examples(self):
        r = client.get("/embed", params={"food": "x", "a": "y", "nutrient": "z", "chain": "w", "rank": "v"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"/embed/food/{FOOD}", html.unescape(r.text))

    def test_only_the_plain_page_is_indexable(self):
        self.assertNotIn("noindex", client.get("/embed").text)
        self.assertIn("noindex", client.get("/embed", params={"nutrient": "fat"}).text)

    def test_a_food_page_leads_to_the_comparison_builder(self):
        body = client.get(f"/food/{FOOD}").text
        self.assertIn(f'href="/embed?a={FOOD}#compare" rel="nofollow"', body)


class TestFoodFigures(unittest.TestCase):
    def test_an_estimate_keeps_its_parentheses(self):
        """MEXT prints its own estimates in parentheses. Dropping them on
        someone else's page turns an estimate into a measurement."""
        rows, serving = embeds.food_rows({
            "nutrition": {"energy_kcal": 105.0, "protein_g": 23.3, "fat_g": 1.9,
                          "carbohydrate_g": None},
            "macro_quality": {"fat_g": "estimated"}, "salt_g": 0.1, "serving": None})
        self.assertIsNone(serving)
        self.assertEqual([r[1] for r in rows], ["105 kcal", "23.3 g", "(1.9) g", "—", "0.1 g"])

    def test_the_serving_column_follows_the_page(self):
        rows, serving = embeds.food_rows({
            "nutrition": {"energy_kcal": 156.0}, "macro_quality": {}, "salt_g": None,
            "serving": {"label": "茶碗1杯", "grams": 150.0, "salt_g": 0.0,
                        "nutrition": {"energy_kcal": 234.0}}})
        self.assertEqual(serving["label"], "茶碗1杯")
        self.assertEqual(rows[0][1:], ("156 kcal", "234 kcal"))


if __name__ == "__main__":
    unittest.main()
