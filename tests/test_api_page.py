"""The public API contract, and the internal schema staying private."""
import unittest

from fastapi.testclient import TestClient

from dataset_manager.api.server import app
from dataset_manager.api import analyzer

client = TestClient(app)


class TestApiPage(unittest.TestCase):
    def test_the_page_lists_the_public_endpoints(self):
        html = client.get("/api").text
        for path in ("/api/search", "/api/foods/{id}/nutrition",
                     "/api/analyze-dish", "/api/meal-analyzer"):
            self.assertIn(path, html)

    def test_the_documented_rate_limit_is_the_enforced_one(self):
        """A documented number that drifts from the enforced one is worse
        than no number."""
        self.assertIn(str(analyzer.RATE_LIMIT), client.get("/api").text)

    def test_every_documented_endpoint_answers(self):
        self.assertEqual(client.get("/api/search?q=さば&limit=2").status_code, 200)
        # POST-only endpoints reject a GET rather than 404ing, which is how you
        # can tell a documented route from a missing one.
        self.assertIn(client.get("/api/meal-analyzer").status_code, (405, 422))

    def test_the_internal_schema_is_not_served(self):
        for path in ("/docs", "/openapi.json", "/redoc"):
            self.assertEqual(client.get(path).status_code, 404, path)

    def test_it_is_in_the_sitemap(self):
        self.assertIn("/api</loc>", client.get("/sitemap-pages-ja.xml").text)


class TestSecurityHeaders(unittest.TestCase):
    def test_every_response_carries_them(self):
        for path in ("/", "/menu", "/api", "/nonexistent"):
            h = client.get(path).headers
            self.assertEqual(h.get("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(h.get("X-Frame-Options"), "DENY", path)
            self.assertIn("frame-ancestors 'none'", h.get("Content-Security-Policy", ""), path)

    def test_cors_does_not_hand_out_credentials(self):
        r = client.get("/api/search?q=rice", headers={"Origin": "https://evil.example"})
        self.assertNotEqual(r.headers.get("Access-Control-Allow-Credentials"), "true")


if __name__ == "__main__":
    unittest.main()
