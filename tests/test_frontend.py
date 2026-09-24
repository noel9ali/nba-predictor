"""Regression tests for the frontend round-1 fixes (FE-F1/F2/F3/F4/F5/F6/F7/F9, FE-04 CSP refactor).

These render templates/index.html through the Flask test client (fake select_rows, no
network/DB) and check static properties of the HTML and of public/static/app.js. Behaviour
that only a real browser can exercise (focus trap, Esc-to-close, SVG rendering of the
bankroll-chart tooltip) is NOT covered here -- see the fixer's handback message for the
browser checklist.
"""
import os
import re
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as dashboard  # noqa: E402  (app.py adds src/ to sys.path itself)

APP_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "static", "app.js")


def _matches(value, operator, expected):
    """Copied from tests/test_app.py's FakeDB helper (kept local, per fixer file ownership)."""
    if operator == "eq":
        return value == expected
    if operator in ("is", "not_is"):
        is_null = value is None
        return is_null if operator == "is" else not is_null
    if operator == "in":
        return value in expected
    if value is None:
        return False
    if operator == "gte":
        return value >= expected
    if operator == "lte":
        return value <= expected
    if operator == "gt":
        return value > expected
    if operator == "lt":
        return value < expected
    raise AssertionError(f"FakeDB does not support {operator}")


class FakeDB:
    """Stands in for database.select_rows: rows keyed by table name (copied from test_app.py)."""

    def __init__(self, tables, errors=None):
        self.tables = tables
        self.errors = errors or {}
        self.calls = []

    def __call__(self, table, *, columns="*", filters=(), order_by=None, descending=False,
                 limit=None, page_size=1000):
        self.calls.append((table, list(filters)))
        if table in self.errors:
            raise self.errors[table]
        rows = [dict(r) for r in self.tables.get(table, [])]
        for column, operator, expected in filters:
            rows = [r for r in rows if _matches(r.get(column), operator, expected)]
        order = [order_by] if isinstance(order_by, str) else list(order_by or [])
        for column in reversed(order):
            rows.sort(key=lambda r: r.get(column), reverse=descending)
        if limit is not None:
            rows = rows[:limit]
        if columns != "*":
            rows = [{c: r.get(c) for c in columns.split(",")} for r in rows]
        return pd.DataFrame(rows)


def prediction(game_id, game_date, home, away, correct, **extra):
    row = {
        "game_id": game_id,
        "game_date": game_date,
        "home_team": home,
        "away_team": away,
        "home_win_prob": "0.62",
        "away_win_prob": "0.38",
        "predicted_winner": home,
        "actual_winner": home if correct == 1 else (away if correct == 0 else None),
        "correct": correct,
        "bet_placed": None,
        "bet_amount": 0.0,
        "odds": None,
        "profit_loss": None,
    }
    row.update(extra)
    return row


def sample_tables():
    return {
        "predictions": [
            prediction(22500900, "2026-03-01", "LAL", "BOS", 1,
                       bet_amount=25.0, odds="150", profit_loss=37.5),
        ],
        "bankroll": [
            {"date": "2026-02-01", "balance": 1000.0},
            {"date": "2026-03-01", "balance": 1017.5},
        ],
        "elo": [],
        "features": [],
    }


def null_fields_tables():
    """A game with a null predicted_winner/odds/edge (FE-F7)."""
    return {
        "predictions": [
            prediction(22500901, "2026-03-01", "DEN", "PHX", None,
                       predicted_winner=None, bet_amount=0.0, odds=None),
        ],
        "bankroll": [],
        "elo": [],
        "features": [],
    }


XSS_PAYLOAD = "</script><img src=x onerror=alert('XSS-FIRED')>"


def xss_tables():
    """A game whose home_team carries an HTML/script-breaking payload (FE-F1/FE-02)."""
    return {
        "predictions": [
            prediction(22500902, "2026-03-01", XSS_PAYLOAD, "PHX", None,
                       bet_amount=0.0, odds=None),
        ],
        "bankroll": [
            {"date": "2026-03-01", "balance": 1000.0},
        ],
        "elo": [],
        "features": [],
    }


class FrontendTestCase(unittest.TestCase):
    def setUp(self):
        self.client = dashboard.app.test_client()

    def _render(self, tables):
        db = FakeDB(tables)
        patcher = patch.object(dashboard, "select_rows", db)
        patcher.start()
        self.addCleanup(patcher.stop)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)


class NoInlineScriptOrHandlersTests(FrontendTestCase):
    """(a) No inline <script> with code (the JSON data block is allowed), no on*= attrs."""

    def test_no_inline_script_code_outside_the_json_data_block(self):
        html = self._render(sample_tables())
        for attrs, inner in re.findall(r"<script([^>]*)>([\s\S]*?)</script>", html):
            if "application/json" in attrs:
                continue
            self.assertEqual(
                inner.strip(), "",
                f"found inline script code in a <script{attrs}> tag: {inner[:80]!r}",
            )

    def test_no_inline_event_handler_attributes(self):
        html = self._render(sample_tables())
        # Word-boundary + leading-whitespace requirement so this doesn't false-positive on
        # substrings like data-confidence="..." (which contains "onfidence=").
        matches = re.findall(r'\son[a-z]+\s*=', html)
        self.assertEqual(matches, [], f"found inline event-handler attributes: {matches}")


class StateJsonBlockTests(FrontendTestCase):
    """(b) The state JSON block parses, and a hostile payload stays escaped inside it."""

    def test_dashboard_state_json_parses_and_payload_stays_escaped(self):
        import json

        html = self._render(xss_tables())
        match = re.search(
            r'<script type="application/json" id="dashboard-state">([\s\S]*?)</script>',
            html,
        )
        self.assertIsNotNone(match, "no <script type=application/json id=dashboard-state> block found")
        raw = match.group(1)

        # The literal string "</script>" must never appear raw inside the block (it would
        # close the script early / could be abused to inject markup after it).
        self.assertNotIn("</script>", raw.lower())

        data = json.loads(raw)
        home_team = data["recommendations"][0]["home_team"]
        self.assertEqual(home_team, XSS_PAYLOAD)


class AppJsStaticSinkTests(unittest.TestCase):
    """(c) app.js has no insertAdjacentHTML, and no innerHTML = assignment sink."""

    def test_app_js_exists_and_has_no_html_string_sinks(self):
        self.assertTrue(os.path.isfile(APP_JS_PATH), f"expected {APP_JS_PATH} to exist")
        with open(APP_JS_PATH, "r", encoding="utf-8") as fh:
            content = fh.read()

        # Coarse static check: any use of insertAdjacentHTML, or of `.innerHTML =` (an
        # assignment to innerHTML, as opposed to e.g. a comment mentioning the property),
        # is a potential HTML-string injection sink. app.js should build DOM/SVG nodes with
        # createElement/createElementNS and set textContent instead.
        self.assertNotIn("insertAdjacentHTML", content)
        self.assertEqual(re.findall(r"\.innerHTML\s*=", content), [])


class AccessibilityMarkupTests(FrontendTestCase):
    """(d) search input has an associated label; modal has role=dialog + aria-modal."""

    def test_search_input_has_a_label(self):
        html = self._render(sample_tables())
        self.assertRegex(html, r'<label[^>]*for="search-games"')

    def test_modal_has_dialog_role_and_aria_modal(self):
        html = self._render(sample_tables())
        modal_match = re.search(r'<div id="summary-modal"[^>]*>', html)
        self.assertIsNotNone(modal_match)
        modal_tag = modal_match.group(0)
        self.assertIn('role="dialog"', modal_tag)
        self.assertIn('aria-modal="true"', modal_tag)


class NoLiteralNoneTests(FrontendTestCase):
    """(e) A fixture with null fields never renders the literal text None/null/undefined."""

    def test_no_literal_none_in_rendered_page(self):
        html = self._render(null_fields_tables())
        self.assertNotIn(">None<", html)
        self.assertNotIn(">null<", html)
        self.assertNotIn(">undefined<", html)


class NoScriptSubmitTests(FrontendTestCase):
    """(f) A <noscript> submit control lets the season/date form work without JS."""

    def test_noscript_submit_button_exists(self):
        html = self._render(sample_tables())
        self.assertIn("<noscript>", html)
        noscript_match = re.search(r"<noscript>([\s\S]*?)</noscript>", html)
        self.assertIsNotNone(noscript_match)
        self.assertRegex(noscript_match.group(1), r'<button[^>]*type="submit"')


class TouchTargetAndMotionCssTests(unittest.TestCase):
    """(FE-F3/FE-F6) static CSS checks: 44x44 hit targets, prefers-reduced-motion guard."""

    def setUp(self):
        css_path = os.path.join(
            os.path.dirname(__file__), "..", "public", "static", "style.css"
        )
        with open(css_path, "r", encoding="utf-8") as fh:
            self.css = fh.read()

    def test_close_modal_meets_44px_minimum(self):
        block = re.search(r"\.close-modal\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(block)
        width = re.search(r"width:\s*(\d+)px", block.group(1))
        height = re.search(r"height:\s*(\d+)px", block.group(1))
        self.assertIsNotNone(width)
        self.assertIsNotNone(height)
        self.assertGreaterEqual(int(width.group(1)), 44)
        self.assertGreaterEqual(int(height.group(1)), 44)

    def test_chip_meets_44px_minimum_height(self):
        block = re.search(r"\.chip\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(block)
        min_height = re.search(r"min-height:\s*(\d+)px", block.group(1))
        self.assertIsNotNone(min_height, "expected .chip to declare a min-height >= 44px")
        self.assertGreaterEqual(int(min_height.group(1)), 44)

    def test_prefers_reduced_motion_media_query_exists(self):
        self.assertIn("prefers-reduced-motion: reduce", self.css)


if __name__ == "__main__":
    unittest.main()
