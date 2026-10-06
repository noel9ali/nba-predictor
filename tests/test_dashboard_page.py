"""The Hardwood Tickets pages are served the way the Vercel CDN serves them: / is public/index.html
(Tonight, also Past nights), /model and /model.html are public/model.html (B7), the old Fan Board
template stays at /legacy, and sample-mode JSON is served from /sample/."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import app as dashboard  # noqa: E402
from test_app import FakeDB, sample_tables  # noqa: E402

PUBLIC = os.path.join(os.path.dirname(__file__), "..", "public")


class DashboardPageTests(unittest.TestCase):
    def setUp(self):
        self.client = dashboard.app.test_client()
        self.db = FakeDB(sample_tables())
        patcher = patch.object(dashboard, "select_rows", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_serves(self, path, filename, entry):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/html")
        body = response.get_data()
        response.close()
        # Compare bytes: a checkout with core.autocrlf rewrites line endings, and the page
        # must be served exactly as it is on disk either way.
        with open(os.path.join(PUBLIC, filename), "rb") as fh:
            self.assertEqual(body, fh.read())
        self.assertIn(f'<script type="module" src="/static/js/{entry}"></script>', body.decode("utf-8"))
        self.assertEqual(response.headers["Cache-Control"], "no-cache")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])

    def test_root_serves_tonight(self):
        self.assert_serves("/", "index.html", "tonight.js")

    def test_model_route_serves_the_model_page(self):
        self.assert_serves("/model", "model.html", "model.js")
        self.assert_serves("/model.html", "model.html", "model.js")

    def test_pages_read_no_data(self):
        # The pages are static; everything they show comes from /api/* (and the CDN on Vercel).
        for path in ("/", "/model"):
            self.client.get(path).close()
        self.assertEqual(self.db.calls, [])

    def test_root_ignores_query_strings(self):
        for query in ("?sample=1", "?sample=1&scene=final", "?date=2026-11-16", "?date=banana"):
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
        for name in ("performance.json", "model.json", "featured-pick.json", "live-replay-6.json"):
            with self.subTest(name=name):
                response = self.client.get(f"/sample/{name}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "application/json")
                response.close()


if __name__ == "__main__":
    unittest.main()
