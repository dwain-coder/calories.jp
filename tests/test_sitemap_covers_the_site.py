"""The sitemap and the site must not drift apart.

Per-page tests already assert that /api, /cooking-yield and /column are listed.
Each was added when that page was, which is exactly why /embed was not: nobody
writes the test for the page they forgot. These two tests compare the whole set
in both directions instead.
"""
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.server import app
from dataset_manager.site import queries
from dataset_manager.site.router import router

client = TestClient(app)


def parameterless_html_routes():
    """Every GET route that answers with a page of its own.

    Decided by asking, not by reading the path: /blog, /ja and /shops are
    redirects kept for old links, and a rule based on names would have to list
    them and be updated whenever another is added.
    """
    skip = {"/robots.txt", "/sitemap.xml"}
    for route in router.routes:
        path = getattr(route, "path", "")
        if "{" in path or path in skip or "GET" not in getattr(route, "methods", set()):
            continue
        r = client.get(path, follow_redirects=False)
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            yield path


class TestEveryPageIsListed(unittest.TestCase):

    def test_a_page_is_either_in_the_sitemap_or_named_as_excluded(self):
        """A new route joins STATIC_PAGES or UNLISTED_PAGES — never neither.

        /embed shipped as a real, indexable page and stayed out of the sitemap
        for as long as it existed, because nothing compared the two lists.
        """
        listed = {"/" + p for p in queries.STATIC_PAGES}
        for path in parameterless_html_routes():
            with self.subTest(path=path):
                self.assertTrue(
                    path in listed or path in queries.UNLISTED_PAGES,
                    f"{path} is in neither STATIC_PAGES nor UNLISTED_PAGES")

    def test_the_sitemap_lists_nothing_that_404s(self):
        """The other direction: a renamed page must not linger in the sitemap.

        A sitemap of URLs that do not answer is worse than a short one — it
        spends crawl budget teaching Google that the site is unreliable.
        """
        body = client.get("/sitemap-pages-ja.xml")
        self.assertEqual(body.status_code, 200)
        for page in queries.STATIC_PAGES:
            with self.subTest(page=page or "/"):
                self.assertEqual(client.get("/" + page).status_code, 200)
                self.assertIn(f"/{page}</loc>" if page else "/</loc>", body.text)

    def test_excluded_pages_say_so_in_their_markup(self):
        """Keeping a page out of the sitemap does not keep it out of the index.

        A page reachable by a link is indexable whatever the sitemap says, so
        each exclusion carries a noindex of its own.
        """
        for path in queries.UNLISTED_PAGES:
            with self.subTest(path=path):
                self.assertIn("noindex", client.get(path).text)


if __name__ == "__main__":
    unittest.main()
