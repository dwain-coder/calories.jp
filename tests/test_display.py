import unittest

from dataset_manager.site.display import resolve_display_names, shorten_mext_name


class TestShorten(unittest.TestCase):
    def test_drops_subgroup_label(self):
        s, dropped = shorten_mext_name("こむぎ うどん・そうめん類 うどん ゆで")
        self.assertEqual(s, "こむぎ うどん ゆで")
        self.assertEqual(dropped, ["うどん・そうめん"])

    def test_drops_parenthesized_group(self):
        s, _ = shorten_mext_name("（植物油脂類） オリーブ油")
        self.assertEqual(s, "オリーブ油")

    def test_keeps_variant_drops_structural_half(self):
        # 若どり distinguishes this bird from 親; 主品目 is table structure.
        s, _ = shorten_mext_name("にわとり 若どり・主品目 むね 皮なし 生")
        self.assertEqual(s, "にわとり 若どり むね 皮なし 生")

    def test_never_drops_final_token(self):
        s, _ = shorten_mext_name("（かんきつ類）")
        self.assertEqual(s, "（かんきつ類）")

    def test_already_minimal_unchanged(self):
        for name in ("かに風味かまぼこ", "おおむぎ 押麦 乾", "ぶた 大型種肉 もも 脂身 生"):
            self.assertEqual(shorten_mext_name(name)[0], name)


class TestResolveCollisions(unittest.TestCase):
    def test_restores_label_that_carried_identity(self):
        pairs = [
            (1, "（いわし類） 缶詰 水煮"),
            (2, "（さば類） 缶詰 水煮"),
        ]
        out = resolve_display_names(pairs)
        self.assertEqual(out[1], "いわし 缶詰 水煮")
        self.assertEqual(out[2], "さば 缶詰 水煮")

    def test_no_two_items_share_a_display_name(self):
        pairs = [
            (1, "（いわし類） 缶詰 水煮"),
            (2, "（さば類） 缶詰 水煮"),
            (3, "あさり 缶詰 水煮"),
            (4, "こむぎ うどん・そうめん類 うどん ゆで"),
        ]
        out = resolve_display_names(pairs)
        self.assertEqual(len(set(out.values())), len(pairs))

    def test_falls_back_to_full_name_when_still_ambiguous(self):
        # Same short form, no group label available to restore -> keep full names.
        pairs = [(1, "テスト 生"), (2, "テスト 生")]
        out = resolve_display_names(pairs)
        self.assertEqual(out[1], "テスト 生")
        self.assertEqual(out[2], "テスト 生")


class TestRealCorpus(unittest.TestCase):
    def test_corpus_is_collision_free(self):
        import sqlite3
        from dataset_manager.api.database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """SELECT nm.item_id, nm.name FROM item_names nm
               JOIN items i ON i.id = nm.item_id
               WHERE i.source = 'MEXT Standard Tables' AND nm.lang = 'ja'
                 AND nm.is_primary = 1""").fetchall()
        conn.close()
        if not rows:
            self.skipTest("names not built")
        self.assertEqual(len(set(n for _, n in rows)), len(rows),
                         "two MEXT items share a display name")


if __name__ == "__main__":
    unittest.main()
