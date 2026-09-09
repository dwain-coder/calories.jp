"""The analyzer as a widget for someone else's page.

The site refuses to be framed everywhere else, so the one route that exists to
be framed is the one place that has to be checked deliberately.
"""
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.server import app

client = TestClient(app)


class TestFraming(unittest.TestCase):
    def test_the_embed_may_be_framed(self):
        r = client.get("/embed/analyzer")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.headers.get("X-Frame-Options"))
        self.assertIn("frame-ancestors *", r.headers["Content-Security-Policy"])

    def test_the_rest_of_the_site_still_refuses(self):
        for path in ("/", "/analyzer", "/column", "/menu"):
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
    def test_it_does_not_compete_with_the_page_it_duplicates(self):
        html = client.get("/embed/analyzer").text
        self.assertIn("noindex,nofollow", html)
        self.assertIn('rel="canonical" href="https://calories.jp/analyzer"', html)

    def test_it_says_where_the_numbers_came_from(self):
        """A widget on someone else's site that does not name its source is
        exactly what this site does not publish."""
        html = client.get("/embed/analyzer").text
        self.assertIn("calories.jp", html)
        self.assertIn("/analyzer", html)

    def test_it_carries_no_site_chrome(self):
        html = client.get("/embed/analyzer").text
        self.assertNotIn("site-header", html)
        self.assertNotIn("site-footer", html)

    def test_it_reports_its_height_to_the_host_page(self):
        """An iframe cannot size itself; without this the widget is clipped."""
        self.assertIn("postMessage", client.get("/embed/analyzer").text)


class TestSnippetPage(unittest.TestCase):
    def test_the_snippet_can_be_copied(self):
        html = client.get("/embed").text
        self.assertIn('id="copy-embed"', html)
        self.assertIn('id="embed-snippet"', html)

    def test_the_snippet_checks_the_message_origin(self):
        """Any page can postMessage to a host. The snippet we hand out should
        not resize itself on a stranger's say-so."""
        self.assertIn('e.origin !== "https://calories.jp"', client.get("/embed").text)

    def test_the_documented_rate_limit_is_the_enforced_one(self):
        from dataset_manager.api import analyzer
        self.assertIn(str(analyzer.RATE_LIMIT), client.get("/embed").text)


if __name__ == "__main__":
    unittest.main()
