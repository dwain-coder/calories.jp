"""WordPress writes the posts; this site renders them.

No WordPress is contacted here — the REST API is faked. These tests are about
what happens to a post between WordPress and the page, which is where the two
things that matter live: the HTML is sanitised, and the webhook cannot be used
by anyone who does not hold the secret.
"""
import os
import tempfile
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient


def _post(pid, slug, title, content, **extra):
    payload = {
        "id": pid, "slug": slug,
        "title": {"rendered": title},
        "content": {"rendered": content},
        "excerpt": {"rendered": "<p>An excerpt.</p>"},
        "date_gmt": "2026-09-01T09:00:00", "modified_gmt": "2026-09-02T09:00:00",
        "_embedded": {"author": [{"name": "Dwain"}]},
    }
    payload.update(extra)
    return payload


def fake_wp(posts):
    """An httpx client answering the WordPress REST API from a list."""
    def handler(request):
        page = int(request.url.params.get("page", 1))
        if page > 1:
            return httpx.Response(400, json={"code": "rest_post_invalid_page_number"})
        return httpx.Response(200, json=posts)
    return httpx.Client(transport=httpx.MockTransport(handler))


class BlogTestCase(unittest.TestCase):
    """Each test gets its own post store, so none of them see each other's."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._dir.name, "blog.db")
        from dataset_manager.blog import store
        self._patch = mock.patch.object(store, "DB_PATH", self.db)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._dir.cleanup()


class TestSanitising(BlogTestCase):
    def test_a_script_tag_never_reaches_the_page(self):
        """The reason WordPress is kept off this domain: a compromised WP must
        not be able to put executable code on calories.jp."""
        from dataset_manager.blog import sync, store
        sync.sync("https://wp.example", client=fake_wp([
            _post(1, "hello", "Hello", '<p>fine</p><script>alert(1)</script>')]))
        body = store.by_slug("hello")["content_html"]
        self.assertIn("fine", body)
        self.assertNotIn("<script", body.lower())
        self.assertNotIn("alert(1)", body)

    def test_event_handlers_and_javascript_urls_are_stripped(self):
        from dataset_manager.blog import sync, store
        sync.sync("https://wp.example", client=fake_wp([
            _post(2, "x", "X",
                  '<img src=x onerror="steal()"><a href="javascript:evil()">go</a>')]))
        body = store.by_slug("x")["content_html"]
        self.assertNotIn("onerror", body)
        self.assertNotIn("javascript:", body)

    def test_an_iframe_does_not_survive(self):
        from dataset_manager.blog import sync, store
        sync.sync("https://wp.example", client=fake_wp([
            _post(3, "f", "F", '<iframe src="https://evil.example"></iframe><p>ok</p>')]))
        self.assertNotIn("<iframe", store.by_slug("f")["content_html"])

    def test_ordinary_post_markup_survives(self):
        """A sanitiser that eats the writing is not a sanitiser, it is a bug."""
        from dataset_manager.blog import sync, store
        html = ('<h2>見出し</h2><p>本文と<strong>強調</strong>と'
                '<a href="https://example.jp">リンク</a></p>'
                '<ul><li>ひとつ</li></ul><table><tr><td>1</td></tr></table>')
        sync.sync("https://wp.example", client=fake_wp([_post(4, "ja", "記事", html)]))
        body = store.by_slug("ja")["content_html"]
        for fragment in ("<h2>", "見出し", "<strong>", "リンク", "<ul>", "<table>"):
            self.assertIn(fragment, body)
        self.assertIn('rel="noopener noreferrer"', body)


class TestSync(BlogTestCase):
    def test_posts_are_stored_and_rendered(self):
        from dataset_manager.blog import sync
        from dataset_manager.api.server import app
        stats = sync.sync("https://wp.example", client=fake_wp([
            _post(1, "first-post", "First post", "<p>Body</p>")]))
        self.assertEqual(stats["stored"], 1)
        client = TestClient(app)
        self.assertIn("First post", client.get("/column").text)
        r = client.get("/column/first-post")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Body", r.text)

    def test_unpublishing_in_wordpress_unpublishes_here(self):
        """Otherwise a deleted post stays up on a site the author cannot edit."""
        from dataset_manager.blog import sync, store
        sync.sync("https://wp.example", client=fake_wp([
            _post(1, "keep", "Keep", "<p>a</p>"), _post(2, "drop", "Drop", "<p>b</p>")]))
        self.assertEqual(len(store.recent()), 2)
        sync.sync("https://wp.example", client=fake_wp([_post(1, "keep", "Keep", "<p>a</p>")]))
        self.assertIsNone(store.by_slug("drop"))
        self.assertIsNotNone(store.by_slug("keep"))

    def test_an_edit_replaces_rather_than_duplicates(self):
        from dataset_manager.blog import sync, store
        sync.sync("https://wp.example", client=fake_wp([_post(1, "p", "Before", "<p>1</p>")]))
        sync.sync("https://wp.example", client=fake_wp([_post(1, "p", "After", "<p>2</p>")]))
        posts = store.recent()
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["title"], "After")

    def test_the_featured_image_comes_across(self):
        from dataset_manager.blog import sync, store
        sync.sync("https://wp.example", client=fake_wp([
            _post(1, "img", "Img", "<p>x</p>", _embedded={
                "author": [{"name": "Dwain"}],
                "wp:featuredmedia": [{"source_url": "https://wp.example/a.jpg",
                                      "alt_text": "alt text"}]})]))
        row = store.by_slug("img")
        self.assertEqual(row["image_url"], "https://wp.example/a.jpg")
        self.assertEqual(row["image_alt"], "alt text")


class TestWebhook(BlogTestCase):
    def test_without_a_secret_the_endpoint_does_not_exist(self):
        """A webhook that authenticates against an empty string is a door."""
        from dataset_manager.api import server
        with mock.patch.object(server, "WP_WEBHOOK_SECRET", ""):
            r = TestClient(server.app).post("/internal/sync-posts")
        self.assertEqual(r.status_code, 404)

    def test_a_wrong_secret_is_refused(self):
        from dataset_manager.api import server
        with mock.patch.object(server, "WP_WEBHOOK_SECRET", "right"):
            r = TestClient(server.app).post(
                "/internal/sync-posts", headers={"x-webhook-secret": "wrong"})
        self.assertEqual(r.status_code, 403)

    def test_the_right_secret_triggers_a_sync(self):
        from dataset_manager.api import server
        from dataset_manager.blog import sync as blog_sync
        with mock.patch.object(server, "WP_WEBHOOK_SECRET", "right"), \
             mock.patch.object(blog_sync, "sync", return_value={"fetched": 2}) as m:
            r = TestClient(server.app).post(
                "/internal/sync-posts", headers={"x-webhook-secret": "right"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["fetched"], 2)
        m.assert_called_once()

    def test_wordpress_being_down_is_not_this_site_s_emergency(self):
        from dataset_manager.api import server
        from dataset_manager.blog import sync as blog_sync
        from dataset_manager.blog import store
        store.upsert([{
            "wp_id": 1, "slug": "kept", "title": "Kept", "excerpt": None,
            "content_html": "<p>still here</p>", "author": None, "image_url": None,
            "image_alt": None, "published_at": "2026-01-01T00:00:00",
            "modified_at": None, "synced_at": "2026-01-01T00:00:00"}])
        with mock.patch.object(server, "WP_WEBHOOK_SECRET", "right"), \
             mock.patch.object(blog_sync, "sync", side_effect=httpx.ConnectError("down")):
            client = TestClient(server.app)
            r = client.post("/internal/sync-posts", headers={"x-webhook-secret": "right"})
            self.assertEqual(r.status_code, 502)
            # the last good copy is still being served
            self.assertEqual(client.get("/column/kept").status_code, 200)


class TestDiscoverableAndRobust(BlogTestCase):
    def test_posts_join_the_sitemap(self):
        from dataset_manager.blog import sync
        from dataset_manager.api.server import app
        sync.sync("https://wp.example", client=fake_wp([_post(1, "in-sitemap", "S", "<p>x</p>")]))
        body = TestClient(app).get("/sitemap-column-ja.xml").text
        self.assertIn("/column/in-sitemap", body)
        self.assertIn("/column</loc>", TestClient(app).get("/sitemap-pages-ja.xml").text)

    def test_a_post_carries_article_markup(self):
        from dataset_manager.blog import sync
        from dataset_manager.api.server import app
        sync.sync("https://wp.example", client=fake_wp([_post(1, "a", "A title", "<p>x</p>")]))
        html = TestClient(app).get("/blog/a").text
        self.assertIn('"@type": "Article"', html)
        self.assertIn("datePublished", html)

    def test_an_unreachable_store_renders_empty_rather_than_500(self):
        """The store is a mounted volume. A blog is the least important thing
        on a nutrition site and must never be able to take it down."""
        from dataset_manager.blog import store
        from dataset_manager.api.server import app
        with mock.patch.object(store, "connect", return_value=None):
            r = TestClient(app).get("/blog")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()


class TestSameHostWordPress(BlogTestCase):
    """On the Contabo box WordPress has no public name: the app asks nginx on
    loopback for a vhost that only exists there."""

    def test_a_host_header_is_sent_when_configured(self):
        from dataset_manager.blog import sync
        with mock.patch.object(sync, "WP_HOST", "wp.calories.internal"):
            self.assertEqual(sync._headers(), {"Host": "wp.calories.internal"})

    def test_nothing_is_forced_on_a_split_deployment(self):
        from dataset_manager.blog import sync
        with mock.patch.object(sync, "WP_HOST", ""):
            self.assertIsNone(sync._headers())

    def test_the_header_reaches_wordpress(self):
        from dataset_manager.blog import sync, store
        seen = {}

        def handler(request):
            seen["host"] = request.headers.get("host")
            return httpx.Response(200, json=[_post(1, "p", "P", "<p>x</p>")])

        with mock.patch.object(sync, "WP_HOST", "wp.calories.internal"):
            sync.sync("http://127.0.0.1",
                      client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertEqual(seen["host"], "wp.calories.internal")
        self.assertIsNotNone(store.by_slug("p"))
