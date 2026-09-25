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


def slate_tables(n_games, game_date="2026-03-01"):
    """predictions/features/elo tables for a synthetic n_games slate, with resolvable
    team_ids so the batched features/Elo lookups actually fire (API-F1)."""
    predictions, features, elo = [], [], []
    for i in range(n_games):
        home, away = f"H{i:02d}", f"A{i:02d}"
        home_id, away_id = 100 + i, 200 + i
        predictions.append(
            prediction(30000000 + i, game_date, home, away, None, bet_amount=10.0, odds="120")
        )
        features.append({
            "GAME_DATE": "2026-02-15", "HOME_TEAM_ABBREVIATION": home, "HOME_TEAM_ID": home_id,
            "HOME_roll_PTS": 110.0, "HOME_roll_FG_PCT": 0.47, "HOME_roll_REB": 42.0,
            "HOME_roll_AST": 24.0, "HOME_roll_TOV": 12.0, "HOME_roll_STOCKS": 11.0, "HOME_rest_days": "1.0",
            "AWAY_TEAM_ABBREVIATION": away, "AWAY_TEAM_ID": away_id,
            "AWAY_roll_PTS": 108.0, "AWAY_roll_FG_PCT": 0.46, "AWAY_roll_REB": 41.0,
            "AWAY_roll_AST": 23.0, "AWAY_roll_TOV": 13.0, "AWAY_roll_STOCKS": 10.0, "AWAY_rest_days": "2.0",
        })
        elo.append({
            "GAME_DATE": "2026-02-20", "HOME_TEAM_ID": home_id, "AWAY_TEAM_ID": away_id,
            "HOME_ELO": 1500.0 + i, "AWAY_ELO": 1490.0 + i,
        })
    return {
        "predictions": predictions,
        "bankroll": [{"date": game_date, "balance": 1000.0}],
        "features": features,
        "elo": elo,
    }


def stale_slate_tables(n_games, game_date="2026-10-21", stale_days=120):
    """Like slate_tables, but every team's only features/elo row is `stale_days` before
    game_date: a season-opening slate, where nobody has played within the short lookback
    window (API-F1 follow-up)."""
    tables = slate_tables(n_games, game_date=game_date)
    stale_date = (dashboard.date.fromisoformat(game_date) - dashboard.timedelta(days=stale_days)).isoformat()
    for row in tables["features"] + tables["elo"]:
        row["GAME_DATE"] = stale_date
    return tables


class CountingFakeDB:
    """Wraps a FakeDB and counts select_rows calls, per table, for query-budget tests."""

    def __init__(self, tables):
        self.db = FakeDB(tables)
        self.calls = []

    def __call__(self, table, **kwargs):
        self.calls.append(table)
        return self.db(table, **kwargs)

    @property
    def total_calls(self):
        return len(self.calls)


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
        response = self.client.get("/legacy")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="season"', html)
        self.assertIn('<option value="2025-26" selected>', html)
        self.assertIn('<option value="2024-25" >', html)

    def test_stylesheet_is_served_from_public_static(self):
        self.assertIn('href="/static/style.css"', self.client.get("/legacy").get_data(as_text=True))
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

    def test_game_date_not_in_the_sample_falls_back_to_the_latest_date(self):
        # TH-F8: pick_date()'s fallback-to-latest branch (game_date not in the known dates).
        # 2025-11-01 and 2026-03-01 are the 2025-26 dates; 2026-03-01 is the latest.
        body = self.client.get("/api/dashboard-state?season=2025-26&game_date=1999-01-01").get_json()
        self.assertEqual(body["game_date"], "2026-03-01")

        body = self.client.get("/api/recommendations?season=2025-26&game_date=1999-01-01").get_json()
        self.assertEqual(body["game_date"], "2026-03-01")


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
        self.assertEqual(self.client.get("/legacy").status_code, 200)

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
        response = self.client.get("/legacy")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Game data is unavailable right now", html)
        self.assertNotIn("detail-XYZ", html)


class RunWorkflowGatingTests(AppTestCase):
    ALLOWED_ENV = {"ALLOW_RUN_WORKFLOW": "true"}

    # SEC-F1: a same-origin, loopback call also needs this non-simple header (so a
    # cross-site browser request would need a CORS preflight the app never allows).
    LOCAL_HEADERS = {"X-Requested-With": "run-now"}

    def post(self, env, remote_addr="127.0.0.1", running=False, headers=None):
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
                response, run_async = self.post(
                    self.ALLOWED_ENV, remote_addr=address, headers=self.LOCAL_HEADERS
                )
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.get_json(), {"started": True, "kind": "manual"})
                run_async.assert_called_once_with()

    def test_conflict_while_a_run_is_in_progress(self):
        response, run_async = self.post(self.ALLOWED_ENV, running=True, headers=self.LOCAL_HEADERS)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json(), {"error": "already_running"})
        run_async.assert_not_called()


class SecretExposureTests(AppTestCase):
    def test_no_response_contains_the_secret_key(self):
        secret = "sb_" "secret_TESTVALUE"  # split so secret scanners skip this fake key
        # ALLOW_RUN_WORKFLOW is forced off so the POST can never start a real run.
        with patch.dict(os.environ, {"SUPABASE_SECRET_KEY": secret, "ALLOW_RUN_WORKFLOW": "false"}):
            bodies = [self.client.get(route).get_data(as_text=True) for route in ["/legacy", *LEGACY_ROUTES]]
            bodies.append(self.client.post("/api/run-workflow").get_data(as_text=True))
            self.db.errors["predictions"] = DatabaseError(f"Reading predictions failed: {secret}")
            bodies += [self.client.get(route).get_data(as_text=True) for route in ["/legacy", *LEGACY_ROUTES]]
        for body in bodies:
            self.assertNotIn("TESTVALUE", body)


class QueryBudgetTests(unittest.TestCase):
    """API-F1: select_rows call counts must stay constant as the slate grows."""

    def setUp(self):
        self.client = dashboard.app.test_client()

    def _get(self, route, n_games):
        counting = CountingFakeDB(slate_tables(n_games))
        with patch.object(dashboard, "select_rows", counting):
            response = self.client.get(f"{route}?season=2025-26&game_date=2026-03-01")
        self.assertEqual(response.status_code, 200)
        return response, counting

    def test_recommendations_call_count_is_constant_regardless_of_slate_size(self):
        _, one_game = self._get("/api/recommendations", 1)
        _, fifteen_games = self._get("/api/recommendations", 15)
        self.assertEqual(one_game.total_calls, fifteen_games.total_calls)
        self.assertLessEqual(fifteen_games.total_calls, 6)

    def test_dashboard_state_call_count_is_constant_regardless_of_slate_size(self):
        _, one_game = self._get("/api/dashboard-state", 1)
        _, fifteen_games = self._get("/api/dashboard-state", 15)
        self.assertEqual(one_game.total_calls, fifteen_games.total_calls)
        self.assertLessEqual(fifteen_games.total_calls, 10)

    def test_index_call_count_is_constant_regardless_of_slate_size(self):
        one_game = CountingFakeDB(slate_tables(1))
        with patch.object(dashboard, "select_rows", one_game):
            response = self.client.get("/legacy?season=2025-26&game_date=2026-03-01")
        self.assertEqual(response.status_code, 200)

        fifteen_games = CountingFakeDB(slate_tables(15))
        with patch.object(dashboard, "select_rows", fifteen_games):
            response = self.client.get("/legacy?season=2025-26&game_date=2026-03-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(one_game.total_calls, fifteen_games.total_calls)

    def test_normal_slate_call_counts_are_unchanged_by_the_retry(self):
        # The retry must be a no-op (0 extra calls) when nobody is actually missing.
        _, one_game = self._get("/api/recommendations", 1)
        _, fifteen_games = self._get("/api/recommendations", 15)
        self.assertEqual(one_game.total_calls, 6)
        self.assertEqual(fifteen_games.total_calls, 6)

        _, dash_one = self._get("/api/dashboard-state", 1)
        _, dash_fifteen = self._get("/api/dashboard-state", 15)
        self.assertEqual(dash_one.total_calls, 8)
        self.assertEqual(dash_fifteen.total_calls, 8)

    def test_recommendations_call_count_is_bounded_on_a_season_opening_slate(self):
        # A slate where nobody has played within the short lookback window: each batched
        # lookup pays for at most one retry, so the total stays a small constant that does
        # not grow with the slate size.
        opener_one = CountingFakeDB(stale_slate_tables(1))
        with patch.object(dashboard, "select_rows", opener_one):
            response = self.client.get("/api/recommendations?season=2026-27&game_date=2026-10-21")
        self.assertEqual(response.status_code, 200)

        opener_fifteen = CountingFakeDB(stale_slate_tables(15))
        with patch.object(dashboard, "select_rows", opener_fifteen):
            response = self.client.get("/api/recommendations?season=2026-27&game_date=2026-10-21")
        self.assertEqual(response.status_code, 200)

        self.assertEqual(opener_one.total_calls, opener_fifteen.total_calls)
        self.assertLessEqual(opener_one.total_calls, 10)  # 6 normal + at most 1 retry per lookup


class BatchedLookupTests(AppTestCase):
    def test_batched_elo_matches_the_per_team_result_when_the_latest_game_was_away(self):
        # LAL (team_id 1) played at home on 2026-02-01 (elo 1500) and away on 2026-02-20
        # (elo 1520); the away appearance is later, so the batched lookup must still pick it,
        # exactly like the old per-team latest_team_elo() did.
        result = dashboard._latest_elo_by_team([1, 2], "2026-03-01")
        self.assertEqual(result[1], 1520.0)
        self.assertEqual(result[2], 1480.0)

    def test_batched_lookups_still_find_teams_whose_last_game_was_months_ago(self):
        # A season-opening slate: neither team has played within TEAM_LOOKBACK_DAYS, so the
        # short-window query alone returns nothing for them (the regression the lead flagged
        # after 8cf861f). Team 5's latest game (of two, ~130d and ~120d before game_date) was
        # away, so this also re-checks the home/away tie-break at the wider retry window.
        game_date = "2026-10-21"
        older = (dashboard.date.fromisoformat(game_date) - dashboard.timedelta(days=130)).isoformat()
        newer = (dashboard.date.fromisoformat(game_date) - dashboard.timedelta(days=120)).isoformat()
        self.db.tables["elo"] = [
            {"GAME_DATE": older, "HOME_TEAM_ID": 5, "AWAY_TEAM_ID": 6,
             "HOME_ELO": 1500.0, "AWAY_ELO": 1430.0},
            {"GAME_DATE": newer, "HOME_TEAM_ID": 6, "AWAY_TEAM_ID": 5,
             "HOME_ELO": 1420.0, "AWAY_ELO": 1550.0},
        ]
        self.db.tables["features"] = [
            {"GAME_DATE": older, "HOME_TEAM_ABBREVIATION": "OPN", "HOME_TEAM_ID": 5,
             "HOME_roll_PTS": 100.0, "HOME_roll_FG_PCT": 0.45, "HOME_roll_REB": 40.0,
             "HOME_roll_AST": 22.0, "HOME_roll_TOV": 14.0, "HOME_roll_STOCKS": 9.0,
             "HOME_rest_days": "3.0",
             "AWAY_TEAM_ABBREVIATION": "OPA", "AWAY_TEAM_ID": 6,
             "AWAY_roll_PTS": 98.0, "AWAY_roll_FG_PCT": 0.44, "AWAY_roll_REB": 39.0,
             "AWAY_roll_AST": 21.0, "AWAY_roll_TOV": 15.0, "AWAY_roll_STOCKS": 8.0,
             "AWAY_rest_days": "4.0"},
        ]

        # Old, non-batched semantics: per team, the latest row on each side, later date wins.
        elo = dashboard._latest_elo_by_team([5, 6], game_date)
        self.assertEqual(elo[5], 1550.0)  # team 5's latest appearance was AWAY, in the newer row
        self.assertEqual(elo[6], 1420.0)  # team 6's latest appearance was HOME, in the newer row

        home_features = dashboard._latest_features_by_team(["OPN"], "HOME", game_date)
        self.assertEqual(home_features["OPN"]["roll_pts"], 100.0)
        away_features = dashboard._latest_features_by_team(["OPA"], "AWAY", game_date)
        self.assertEqual(away_features["OPA"]["roll_pts"], 98.0)


class CacheControlTests(AppTestCase):
    def test_index_success_sends_the_legacy_cache_control(self):
        response = self.client.get("/legacy")
        self.assertIn("s-maxage=300", response.headers["Cache-Control"])

    def test_index_degraded_sends_no_store(self):
        self.db.errors["predictions"] = DatabaseError("Reading predictions failed: detail-XYZ")
        response = self.client.get("/legacy")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")


class MigrationNoticeTests(AppTestCase):
    def test_index_shows_a_status_notice_when_migration_pending_but_not_fully_down(self):
        self.db.errors["bankroll"] = MissingTableError("Reading bankroll failed: table is missing")
        response = self.client.get("/legacy")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('role="status"', html)
        self.assertIn("migration", html.lower())

    def test_index_has_no_migration_notice_when_data_is_complete(self):
        response = self.client.get("/legacy")
        html = response.get_data(as_text=True)
        self.assertNotIn("migration", html.lower())


class ErrorHandlerTests(AppTestCase):
    def test_unknown_route_is_a_json_404(self):
        response = self.client.get("/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "not_found"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_wrong_method_is_a_json_405(self):
        response = self.client.get("/api/run-workflow")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.get_json(), {"error": "method_not_allowed"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
