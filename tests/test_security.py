"""Round-1 security regression tests: SEC-F1 (run-workflow CSRF/DNS-rebinding), SEC-F2
(security response headers), SEC-F7 (no hardcoded secret-key fallback), and TH-F7 (forged
X-Forwarded-For/X-Real-IP/Forwarded never influence the loopback decision).
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as dashboard  # noqa: E402  (app.py adds src/ to sys.path itself)
import daily_workflow  # noqa: E402


class RunWorkflowCSRFTests(unittest.TestCase):
    """SEC-F1 / TH-F7: cross-site vectors that must now be rejected, and the legitimate
    local call that must still work."""

    ALLOWED_ENV = {"ALLOW_RUN_WORKFLOW": "true"}

    def setUp(self):
        self.client = dashboard.app.test_client()

    def post(self, headers=None, remote_addr="127.0.0.1", env=None, running=False):
        env = {**self.ALLOWED_ENV, **(env or {})}
        with patch.dict(os.environ, env), \
                patch.object(daily_workflow, "workflow_is_running", return_value=running), \
                patch.object(daily_workflow, "run_workflow_async",
                             return_value=(True, "Workflow started")) as run_async:
            if "VERCEL" not in env:
                os.environ.pop("VERCEL", None)
            response = self.client.post(
                "/api/run-workflow",
                environ_overrides={"REMOTE_ADDR": remote_addr},
                headers=headers or {},
            )
        return response, run_async

    def assert_forbidden(self, response, run_async):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "forbidden"})
        run_async.assert_not_called()

    def test_hostile_origin_is_rejected(self):
        response, run_async = self.post(headers={
            "Origin": "https://evil.example",
            "X-Requested-With": "run-now",
            "Host": "127.0.0.1",
        })
        self.assert_forbidden(response, run_async)

    def test_hostile_referer_form_style_post_with_no_custom_header_is_rejected(self):
        response, run_async = self.post(headers={
            "Referer": "https://evil.example/attack.html",
            "Host": "127.0.0.1",
        })
        self.assert_forbidden(response, run_async)

    def test_dns_rebound_host_is_rejected(self):
        response, run_async = self.post(headers={
            "Host": "evil.example",
            "X-Requested-With": "run-now",
        })
        self.assert_forbidden(response, run_async)

    def test_bare_no_cors_post_without_the_required_header_is_rejected(self):
        response, run_async = self.post(headers={"Host": "127.0.0.1:5000"})
        self.assert_forbidden(response, run_async)

    def test_origin_null_is_rejected(self):
        response, run_async = self.post(headers={
            "Origin": "null",
            "X-Requested-With": "run-now",
            "Host": "127.0.0.1",
        })
        self.assert_forbidden(response, run_async)

    def test_forged_forwarding_headers_from_a_non_loopback_remote_addr_are_rejected(self):
        for header, value in (
            ("X-Forwarded-For", "127.0.0.1"),
            ("X-Real-IP", "127.0.0.1"),
            ("Forwarded", "for=127.0.0.1"),
        ):
            with self.subTest(header=header):
                response, run_async = self.post(
                    headers={header: value, "X-Requested-With": "run-now", "Host": "127.0.0.1"},
                    remote_addr="10.0.0.5",
                )
                self.assert_forbidden(response, run_async)

    def test_legitimate_local_call_with_no_origin_succeeds(self):
        response, run_async = self.post(headers={
            "Host": "127.0.0.1:5000",
            "X-Requested-With": "run-now",
        })
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"started": True, "kind": "manual"})
        run_async.assert_called_once_with()

    def test_legitimate_local_call_with_same_origin_succeeds(self):
        response, run_async = self.post(headers={
            "Host": "127.0.0.1:5000",
            "Origin": "http://127.0.0.1:5000",
            "X-Requested-With": "run-now",
        })
        self.assertEqual(response.status_code, 202)
        run_async.assert_called_once_with()

    def test_no_cors_headers_are_ever_sent(self):
        response, _ = self.post(headers={
            "Host": "127.0.0.1:5000",
            "X-Requested-With": "run-now",
        })
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))


CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'; object-src 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _fake_select_rows(table, *, columns="*", filters=(), order_by=None, descending=False,
                       limit=None, page_size=1000):
    import pandas as pd
    return pd.DataFrame([])


class SecurityHeadersTests(unittest.TestCase):
    """SEC-F2: every response (pages, API JSON, errors, 404/405, degraded DB-down render)
    carries all five security headers with the exact expected values."""

    def setUp(self):
        self.client = dashboard.app.test_client()
        patcher = patch.object(dashboard, "select_rows", _fake_select_rows)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_all_headers(self, response):
        for name, value in SECURITY_HEADERS.items():
            self.assertEqual(response.headers.get(name), value, f"header {name} on {response}")

    def test_dashboard_page_has_all_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assert_all_headers(response)
        response.close()

    def test_legacy_page_has_all_headers(self):
        response = self.client.get("/legacy")
        self.assertEqual(response.status_code, 200)
        self.assert_all_headers(response)

    def test_api_routes_have_all_headers(self):
        for route in ("/api/dashboard-state", "/api/ytd-summary",
                      "/api/recommendations", "/api/bankroll-series",
                      "/api/slate", "/api/days", "/api/performance", "/api/predictions",
                      "/api/model", "/api/workflow-status", "/api/game/0022501100",
                      "/api/game/bad"):
            with self.subTest(route=route):
                self.assert_all_headers(self.client.get(route))

    def test_404_has_all_headers(self):
        self.assert_all_headers(self.client.get("/nope"))

    def test_405_has_all_headers(self):
        self.assert_all_headers(self.client.get("/api/run-workflow"))

    def test_degraded_db_down_render_has_all_headers(self):
        from database import DatabaseError

        def erroring(table, **kwargs):
            raise DatabaseError("boom")

        with patch.object(dashboard, "select_rows", erroring):
            self.assert_all_headers(self.client.get("/legacy"))
            self.assert_all_headers(self.client.get("/api/slate"))

    def test_static_file_response_has_all_headers(self):
        response = self.client.get("/static/style.css")
        self.assert_all_headers(response)
        response.close()

    def test_dashboard_assets_have_all_headers(self):
        for path in ("/static/dashboard.css", "/static/js/main.js", "/static/favicon.svg",
                     "/static/fonts/barlow-latin-400-normal.woff2", "/sample/days.json"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assert_all_headers(response)
                response.close()

    def test_sample_path_traversal_is_refused(self):
        for path in ("/sample/../../app.py", "/sample/..%2F..%2Fapp.py", "/sample/nope.json"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assert_all_headers(response)
                response.close()


# Everything the Vercel CDN serves straight from public/ (Flask never sees these requests
# there, so its after_request can't add the headers): the dashboard page itself, its
# static assets and the sample-mode JSON.
CDN_SOURCES = ("/", "/index.html", "/static/(.*)", "/sample/(.*)")


class VercelJsonHeadersTests(unittest.TestCase):
    """SEC-F2: vercel.json parses and every CDN-served source rule mirrors the same five
    headers, compared against the same SECURITY_HEADERS constant so they can't drift."""

    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "..", "vercel.json")
        with open(path, encoding="utf-8") as f:
            self.rules = json.load(f).get("headers", [])

    def test_every_cdn_source_rule_matches_flask_headers(self):
        for source in CDN_SOURCES:
            with self.subTest(source=source):
                matching = [r for r in self.rules if r.get("source") == source]
                self.assertEqual(len(matching), 1)
                headers = {h["key"]: h["value"] for h in matching[0]["headers"]}
                self.assertEqual(headers, SECURITY_HEADERS)

    def test_no_catch_all_rule(self):
        # Must not duplicate onto every (Flask) response: only the CDN-served paths.
        sources = [r.get("source") for r in self.rules]
        self.assertNotIn("/(.*)", sources)
        self.assertEqual(sorted(sources), sorted(CDN_SOURCES))

    def test_excludefiles_fits_vercels_limit(self):
        path = os.path.join(os.path.dirname(__file__), "..", "vercel.json")
        with open(path, encoding="utf-8") as f:
            exclude = json.load(f)["functions"]["app.py"]["excludeFiles"]
        self.assertLessEqual(len(exclude), 256)


class SecretKeyTests(unittest.TestCase):
    """SEC-F7: no hardcoded fallback secret key."""

    def test_secret_key_is_never_the_old_hardcoded_literal(self):
        self.assertNotEqual(dashboard.app.secret_key, "dev-secret-change-me")

    def test_secret_key_is_a_non_empty_string(self):
        self.assertTrue(dashboard.app.secret_key)


if __name__ == "__main__":
    unittest.main()
