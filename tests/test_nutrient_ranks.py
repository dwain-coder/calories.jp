"""Percentiles: what population they are over, and what they refuse to say.

「鉄は肉類の上位1%」 is publishable where 「鉄分が豊富」 is not, but only because
the population is stated and fixed. Two things make that true and both are
tested here: the comparison is measured values against measured values, and a
group with too few of them produces no percentile at all.
"""
import sqlite3
import unittest

from dataset_manager.scripts.build_ranks import MIN_PEERS, build_nutrient_ranks
from dataset_manager.site import queries

DB = "data/metadata/site.db"


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


class TestThePopulation(unittest.TestCase):

    def setUp(self):
        self.conn = conn()

    def tearDown(self):
        self.conn.close()

    def test_peers_counts_measured_values_only(self):
        """76,436 of the 257,235 values are MEXT's own estimates. A percentile
        that counted them would inherit their uncertainty without showing it."""
        row = self.conn.execute(
            "SELECT code, category, peers FROM nutrient_ranks LIMIT 1").fetchone()
        measured = self.conn.execute(
            """SELECT COUNT(*) FROM nutrients n JOIN items i ON i.id = n.item_id
               WHERE n.code = ? AND i.category = ? AND n.amount IS NOT NULL
                 AND n.quality = 'measured' AND i.source_url LIKE 'mext_%'""",
            (row["code"], row["category"])).fetchone()[0]
        self.assertEqual(row["peers"], measured)

    def test_a_food_whose_own_value_is_estimated_gets_no_rank(self):
        estimated = self.conn.execute(
            """SELECT DISTINCT n.item_id, n.code FROM nutrients n
               JOIN nutrient_ranks r ON r.code = n.code
               WHERE n.quality = 'estimated' LIMIT 200""").fetchall()
        self.assertTrue(estimated, "no estimated values to check against")
        ranked = [(r["item_id"], r["code"]) for r in estimated
                  if self.conn.execute(
                      "SELECT 1 FROM nutrient_ranks WHERE item_id = ? AND code = ?",
                      (r["item_id"], r["code"])).fetchone()]
        self.assertFalse(ranked, f"{len(ranked)} estimated values were ranked")

    def test_no_rank_rests_on_fewer_than_twenty_peers(self):
        thin = self.conn.execute(
            "SELECT COUNT(*) FROM nutrient_ranks WHERE peers < ?",
            (MIN_PEERS,)).fetchone()[0]
        self.assertEqual(thin, 0)

    def test_a_percentile_is_a_percentage(self):
        out = self.conn.execute(
            "SELECT COUNT(*) FROM nutrient_ranks "
            "WHERE percentile < 0 OR percentile > 100").fetchone()[0]
        self.assertEqual(out, 0)


class TestTheArithmetic(unittest.TestCase):

    def build(self, values):
        """values: [(item_id, category, amount, quality)] -> {item_id: percentile}"""
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE items "
                  "(id INTEGER PRIMARY KEY, category TEXT, source_url TEXT)")
        c.execute("CREATE TABLE nutrients "
                  "(item_id INTEGER, code TEXT, amount REAL, quality TEXT)")
        for item_id, category, amount, quality in values:
            c.execute("INSERT OR IGNORE INTO items VALUES (?, ?, 'mext_00001')",
                      (item_id, category))
            c.execute("INSERT INTO nutrients VALUES (?, 'FE', ?, ?)",
                      (item_id, amount, quality))
        build_nutrient_ranks(c, codes=("FE",), min_peers=3)
        rows = {r["item_id"]: r["percentile"] for r in
                c.execute("SELECT item_id, percentile FROM nutrient_ranks")}
        peers = c.execute("SELECT peers FROM nutrient_ranks LIMIT 1").fetchone()
        c.close()
        return rows, (peers["peers"] if peers else 0)

    def test_the_largest_is_above_everyone_and_the_smallest_above_nobody(self):
        rows, peers = self.build([(i, "肉類", float(i), "measured") for i in range(1, 5)])
        self.assertEqual(peers, 4)
        self.assertEqual(rows[4], 100)
        self.assertEqual(rows[1], 0)

    def test_a_tie_shares_one_percentile(self):
        """Two foods holding the same amount cannot be 上位25% and 上位50%."""
        rows, _ = self.build([(1, "肉類", 1.0, "measured"), (2, "肉類", 5.0, "measured"),
                              (3, "肉類", 5.0, "measured"), (4, "肉類", 9.0, "measured")])
        self.assertEqual(rows[2], rows[3])
        self.assertEqual(rows[2], 33)      # above one of the other three

    def test_an_estimated_value_is_neither_ranked_nor_counted(self):
        rows, peers = self.build([(1, "肉類", 1.0, "measured"), (2, "肉類", 2.0, "measured"),
                                  (3, "肉類", 3.0, "measured"),
                                  (4, "肉類", 99.0, "estimated")])
        self.assertEqual(peers, 3)
        self.assertNotIn(4, rows)

    def test_a_thin_group_produces_nothing(self):
        rows, _ = self.build([(1, "肉類", 1.0, "measured"), (2, "肉類", 2.0, "measured")])
        self.assertEqual(rows, {})


class TestWhatThePagesRead(unittest.TestCase):

    LIVER = "ぶた-副生物-肝臓-生"

    def setUp(self):
        self.conn = conn()

    def tearDown(self):
        self.conn.close()

    def item(self, slug):
        row = self.conn.execute(
            "SELECT item_id FROM site_pages WHERE lang = 'ja' AND slug = ?",
            (slug,)).fetchone()
        self.assertIsNotNone(row, f"no page for {slug}")
        return row["item_id"]

    def test_pork_liver_is_at_the_top_of_its_category_for_iron(self):
        standing = {s["term"]: s for s in
                    queries.food_nutrient_standing(self.conn, self.item(self.LIVER))}
        self.assertIn("鉄", standing)
        self.assertGreaterEqual(standing["鉄"]["percentile"], 95)
        self.assertEqual(standing["鉄"]["category"], "肉類")

    def test_the_macro_bars_come_from_the_same_table(self):
        """They were two percentiles built two ways under one heading: a live
        COUNT over measured AND estimated for the bars, this table for the list.
        """
        item_id = self.item(self.LIVER)
        item = dict(self.conn.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
        bars = queries.nutrient_ranks(self.conn, item, None)
        self.assertTrue(bars)
        stored = {(r["percentile"], r["peers"]) for r in self.conn.execute(
            "SELECT percentile, peers FROM nutrient_ranks WHERE item_id = ? "
            "AND code IN ('ENERC_KCAL','PROT-','FAT-','CHOCDF-')", (item_id,))}
        for bar in bars:
            self.assertIn((bar["percentile"], bar["peers"]), stored, bar["field"])

    def test_a_macro_is_not_listed_twice(self):
        terms = {s["term"] for s in
                 queries.food_nutrient_standing(self.conn, self.item(self.LIVER))}
        self.assertNotIn("たんぱく質", terms)
        self.assertNotIn("脂質", terms)


class TestHowItReads(unittest.TestCase):

    PAGE = None

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.PAGE = Path("templates/food.html").read_text(encoding="utf-8")

    def test_a_food_in_the_bottom_tenth_is_not_described_as_being_in_a_top_band(self):
        """Pork liver is the 11th percentile of 肉類 for calories, and the one
        line said 「多い方から上位89%」 — which reads as high to anyone skimming."""
        self.assertIn("rank_line_low", self.PAGE)
        self.assertIn("r.percentile < 50", self.PAGE)


class TestCategoryLeaders(unittest.TestCase):

    def test_every_category_with_a_rank_group_gets_one_line(self):
        """`percentile = 100` needs a food strictly above every peer, so a tie
        at the top left the category out — iron listed three of eighteen."""
        leaders = queries.nutrient_category_leaders("ja", "FE")
        self.assertGreater(len(leaders), 10)
        self.assertEqual(len(leaders), len({row["category"] for row in leaders}))

    def test_the_leader_is_the_largest_in_its_category(self):
        c = conn()
        try:
            for leader in queries.nutrient_category_leaders("ja", "FE")[:5]:
                biggest = c.execute(
                    """SELECT MAX(n.amount) FROM nutrient_ranks r
                       JOIN nutrients n ON n.item_id = r.item_id AND n.code = r.code
                       WHERE r.code = 'FE' AND r.category = ?""",
                    (leader["category"],)).fetchone()[0]
                self.assertEqual(leader["amount"], biggest, leader["category"])
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
