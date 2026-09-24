import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as dashboard  # noqa: E402  (app.py adds src/ to sys.path itself)
import daily_workflow  # noqa: E402
from database import DatabaseError, MissingTableError  # noqa: E402


def _matches(value, operator, expected):
    if operator == "eq":
        return value == expected
    if operator in ("is", "not_is"):
        is_null = value is None
        return is_null if operator == "is" else not is_null
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
    """Stands in for database.select_rows: rows keyed by table name, or an error to raise."""

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
        # Text, as in the live schema before migration 0003.
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
            prediction(22400800, "2025-04-01", "NYK", "MIA", 1),
            prediction(22500100, "2025-11-01", "BOS", "LAL", 0,
                       bet_amount=20.0, odds="120", profit_loss=-20.0),
            prediction(22500900, "2026-03-01", "LAL", "BOS", 1,
                       bet_amount=25.0, odds="150", profit_loss=37.5),
            prediction(22500901, "2026-03-01", "DEN", "PHX", None),
        ],
        "bankroll": [
            {"date": "2025-04-01", "balance": 900.0},
            {"date": "2025-10-31", "balance": 1000.0},
            {"date": "2025-11-01", "balance": 980.0},
            {"date": "2026-03-01", "balance": 1017.5},
        ],
        "elo": [
            {"GAME_DATE": "2026-02-01", "HOME_TEAM_ID": 1, "AWAY_TEAM_ID": 2,
             "HOME_ELO": 1500.0, "AWAY_ELO": 1490.0},
            {"GAME_DATE": "2026-02-20", "HOME_TEAM_ID": 2, "AWAY_TEAM_ID": 1,
             "HOME_ELO": 1480.0, "AWAY_ELO": 1520.0},
        ],
        "features": [
            {"GAME_DATE": "2026-02-01", "HOME_TEAM_ABBREVIATION": "LAL", "HOME_TEAM_ID": 1,
             "HOME_roll_PTS": 115.0, "HOME_roll_FG_PCT": 0.48, "HOME_roll_REB": 44.0,
             "HOME_roll_AST": 27.0, "HOME_roll_TOV": 13.0, "HOME_roll_STOCKS": 12.0,
             "HOME_rest_days": "2.0",
             "AWAY_TEAM_ABBREVIATION": "BOS", "AWAY_TEAM_ID": 2,
             "AWAY_roll_PTS": "112.5", "AWAY_roll_FG_PCT": "0.47", "AWAY_roll_REB": "43.0",
             "AWAY_roll_AST": "25.0", "AWAY_roll_TOV": "12.5", "AWAY_roll_STOCKS": "13.0",
             "AWAY_rest_days": "1.0"},
        ],
    }


LEGACY_ROUTES = [
    "/api/dashboard-state",
    "/api/ytd-summary",
    "/api/recommendations",
    "/api/bankroll-series",
]

YTD_KEYS = {
    "year", "games", "wins", "losses", "accuracy", "bets_placed", "total_staked", "total_pl",
    "roi", "bankroll", "longest_win_streak", "longest_loss_streak", "max_drawdown",
}
EXISTING_KEYS = {
    "/api/dashboard-state": {
        "year", "game_date", "ytd_summary", "recommendations", "confidence_distribution",
        "top_edges", "bankroll_series", "peak_point", "trough_point",
    },
    "/api/ytd-summary": YTD_KEYS,
    "/api/recommendations": {"game_date", "recommendations"},
    "/api/bankroll-series": {"year", "points"},
}


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.client = dashboard.app.test_client()
        self.db = FakeDB(sample_tables())
        patcher = patch.object(dashboard, "select_rows", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)


class LegacyRouteTests(AppTestCase):
    def test_each_legacy_route_returns_its_existing_keys(self):
        for route in LEGACY_ROUTES:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                body = response.get_json()
                self.assertLessEqual(EXISTING_KEYS[route], set(body))
                self.assertEqual(body["season"], "2025-26")
                self.assertFalse(body["migration_pending"])
                self.assertIn("generated_at", body)
                self.assertIn("s-maxage=300", response.headers["Cache-Control"])

    def test_index_renders_the_season_selector(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="season"', html)
        self.assertIn('<option value="2025-26" selected>', html)
        self.assertIn('<option value="2024-25" >', html)

    def test_stylesheet_is_served_from_public_static(self):
        self.assertIn('href="/static/style.css"', self.client.get("/").get_data(as_text=True))
        response = self.client.get("/static/style.css")
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_recommendations_pad_ids_and_read_text_columns(self):
        body = self.client.get("/api/recommendations?season=2025-26").get_json()
        self.assertEqual(body["game_date"], "2026-03-01")
        lal = next(r for r in body["recommendations"] if r["home_team"] == "LAL")
        self.assertEqual(lal["id"], "0022500900")
        self.assertAlmostEqual(lal["expected_win_prob"], 0.62)
        self.assertEqual(lal["odds"], 150.0)
        self.assertAlmostEqual(lal["implied_prob"], 0.4)
        self.assertEqual(lal["recommendation_type"], "bet")
        details = lal["details"]
        # LAL played at home on 02-01 (1500) and away on 02-20 (1520): the later one wins.
        self.assertEqual(details["home_elo"], 1520.0)
        self.assertEqual(details["away_elo"], 1480.0)
        self.assertEqual(details["home_rest_days"], 2.0)
        self.assertEqual(details["away_rest_days"], 1.0)
        self.assertEqual(details["away_roll_pts"], 112.5)

    def test_dashboard_state_summarizes_the_selected_date(self):
        body = self.client.get("/api/dashboard-state?season=2025-26&game_date=2026-03-01").get_json()
        self.assertEqual(body["game_date"], "2026-03-01")
        self.assertEqual(len(body["recommendations"]), 2)
        self.assertEqual(body["peak_point"], {"date": "2026-03-01", "balance": 1017.5, "cum_pl": 17.5})
        self.assertEqual(body["ytd_summary"]["bankroll"], 1017.5)
        self.assertEqual(body["ytd_summary"]["max_drawdown"], 20.0)


class SeasonTests(AppTestCase):
    def test_season_for_uses_a_september_cutoff(self):
        self.assertEqual(dashboard.season_for("2025-11-01"), "2025-26")
        self.assertEqual(dashboard.season_for("2026-03-01"), "2025-26")
        self.assertEqual(dashboard.season_for("2025-04-01"), "2024-25")
        self.assertEqual(dashboard.season_for(date(2020, 8, 14)), "2019-20")
        self.assertEqual(dashboard.season_bounds("2025-26"), ("2025-09-01", "2026-08-31"))

    def test_ytd_summary_filters_by_season_not_calendar_year(self):
        body = self.client.get("/api/ytd-summary?season=2025-26").get_json()
        # 2025-11-01 and 2026-03-01 are both 2025-26; the 2026-03-01 DEN game is unsettled.
        self.assertEqual((body["games"], body["wins"], body["losses"]), (2, 1, 1))
        self.assertEqual(body["bets_placed"], 2)
        self.assertEqual(body["total_pl"], 17.5)
        self.assertEqual(body["year"], "2026")

        body = self.client.get("/api/ytd-summary?season=2024-25").get_json()
        self.assertEqual(body["games"], 1)
        self.assertEqual(body["bankroll"], 900.0)

    def test_year_alias_maps_to_the_season_ending_that_year(self):
        body = self.client.get("/api/ytd-summary?year=2026").get_json()
        self.assertEqual((body["season"], body["year"], body["games"]), ("2025-26", "2026", 2))
        body = self.client.get("/api/bankroll-series?year=2025").get_json()
        self.assertEqual(body["season"], "2024-25")
        self.assertEqual([p["date"] for p in body["points"]], ["2025-04-01"])

    def test_unknown_season_falls_back_to_the_latest(self):
        body = self.client.get("/api/ytd-summary?season=2010-11").get_json()
        self.assertEqual(body["season"], "2025-26")

    def test_malformed_season_is_a_bad_request(self):
        for value in ("2025", "2025-27", "latest"):
            with self.subTest(value=value):
                response = self.client.get(f"/api/ytd-summary?season={value}")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"], "bad_request")
                self.assertEqual(response.headers["Cache-Control"], "no-store")


class DatabaseFailureTests(AppTestCase):
    def test_missing_bankroll_table_is_migration_pending(self):
        self.db.errors["bankroll"] = MissingTableError("Reading bankroll failed: table is missing")

        response = self.client.get("/api/ytd-summary?season=2025-26")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["migration_pending"])
        self.assertEqual(body["games"], 2)
        self.assertIsNone(body["bankroll"])
        self.assertEqual(body["max_drawdown"], 0.0)

        body = self.client.get("/api/bankroll-series").get_json()
        self.assertEqual(body["points"], [])
        self.assertTrue(body["migration_pending"])

        body = self.client.get("/api/dashboard-state").get_json()
        self.assertTrue(body["migration_pending"])
        self.assertEqual(body["bankroll_series"], [])
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_database_error_is_503_without_exception_text(self):
        self.db.errors["predictions"] = DatabaseError("Reading predictions failed: detail-XYZ")
        for route in LEGACY_ROUTES:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json(), {"error": "database_unavailable"})
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn("detail-XYZ", response.get_data(as_text=True))

    def test_index_renders_empty_with_a_notice_when_the_database_is_down(self):
        self.db.errors["predictions"] = DatabaseError("Reading predictions failed: detail-XYZ")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Game data is unavailable right now", html)
        self.assertNotIn("detail-XYZ", html)


class RunWorkflowGatingTests(AppTestCase):
    ALLOWED_ENV = {"ALLOW_RUN_WORKFLOW": "true"}

    def post(self, env, remote_addr="127.0.0.1", running=False):
        with patch.dict(os.environ, env), \
                patch.object(daily_workflow, "workflow_is_running", return_value=running), \
                patch.object(daily_workflow, "run_workflow_async",
                             return_value=(True, "Workflow started")) as run_async:
            if "VERCEL" not in env:
                os.environ.pop("VERCEL", None)
            response = self.client.post(
                "/api/run-workflow", environ_overrides={"REMOTE_ADDR": remote_addr}
            )
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return response, run_async

    def assert_forbidden(self, response, run_async):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "forbidden"})
        run_async.assert_not_called()

    def test_forbidden_on_vercel(self):
        self.assert_forbidden(*self.post({**self.ALLOWED_ENV, "VERCEL": "1"}))

    def test_forbidden_when_the_flag_is_off(self):
        self.assert_forbidden(*self.post({"ALLOW_RUN_WORKFLOW": "false"}))

    def test_forbidden_from_a_non_loopback_address(self):
        self.assert_forbidden(*self.post(self.ALLOWED_ENV, remote_addr="10.0.0.5"))

    def test_starts_when_local_and_allowed(self):
        for address in ("127.0.0.1", "::1"):
            with self.subTest(address=address):
                response, run_async = self.post(self.ALLOWED_ENV, remote_addr=address)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.get_json(), {"started": True, "kind": "manual"})
                run_async.assert_called_once_with()

    def test_conflict_while_a_run_is_in_progress(self):
        response, run_async = self.post(self.ALLOWED_ENV, running=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json(), {"error": "already_running"})
        run_async.assert_not_called()


class SecretExposureTests(AppTestCase):
    def test_no_response_contains_the_secret_key(self):
        secret = "sb_" "secret_TESTVALUE"  # split so secret scanners skip this fake key
        # ALLOW_RUN_WORKFLOW is forced off so the POST can never start a real run.
        with patch.dict(os.environ, {"SUPABASE_SECRET_KEY": secret, "ALLOW_RUN_WORKFLOW": "false"}):
            bodies = [self.client.get(route).get_data(as_text=True) for route in ["/", *LEGACY_ROUTES]]
            bodies.append(self.client.post("/api/run-workflow").get_data(as_text=True))
            self.db.errors["predictions"] = DatabaseError(f"Reading predictions failed: {secret}")
            bodies += [self.client.get(route).get_data(as_text=True) for route in ["/", *LEGACY_ROUTES]]
        for body in bodies:
            self.assertNotIn("TESTVALUE", body)


if __name__ == "__main__":
    unittest.main()
