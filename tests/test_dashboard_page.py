"""B9: the new dashboard (public/index.html) is served at / and the old Fan Board template
at /legacy, locally the same way the Vercel CDN serves them."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import app as dashboard  # noqa: E402
from test_app import FakeDB, sample_tables  # noqa: E402

INDEX_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "index.html")


class DashboardPageTests(unittest.TestCase):
    def setUp(self):
        self.client = dashboard.app.test_client()
        self.db = FakeDB(sample_tables())
        patcher = patch.object(dashboard, "select_rows", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_root_serves_the_static_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/html")
        body = response.get_data()
        response.close()
        # Compare bytes: a checkout with core.autocrlf rewrites line endings, and the page
        # must be served exactly as it is on disk either way.
        with open(INDEX_PATH, "rb") as fh:
            self.assertEqual(body, fh.read())
        html = body.decode("utf-8")
        self.assertIn('<script type="module" src="/static/js/main.js"></script>', html)
        self.assertEqual(response.headers["Cache-Control"], "no-cache")

    def test_root_reads_no_data(self):
        # The page is static; everything it shows comes from /api/* (and the CDN on Vercel).
        self.client.get("/").close()
        self.assertEqual(self.db.calls, [])

    def test_root_ignores_query_strings(self):
        for query in ("?sample=1", "?sample=1&scene=final", "?season=bad"):
            with self.subTest(query=query):
                response = self.client.get(f"/{query}")
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_legacy_serves_the_old_template(self):
        response = self.client.get("/legacy")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/static/style.css"', html)
        self.assertIn('action="/legacy"', html)
        self.assertIn('id="dashboard-state"', html)

    def test_sample_files_are_served_as_json(self):
        response = self.client.get("/sample/performance.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        response.close()


if __name__ == "__main__":
    unittest.main()
