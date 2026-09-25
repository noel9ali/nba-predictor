"""Dashboard read API (04-API-CONTRACT sec2, sec4-9; build tasks B5/B6): shapes, the
migration_pending degrade path, constant call counts (API-F1), errors, cache headers,
secret hygiene and hostile-string handling. No network: select_rows is faked.
"""
import os
import sys
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import app as dashboard  # noqa: E402
import daily_workflow  # noqa: E402
from contract_shapes import (  # noqa: E402
    DAYS, GAME_DETAIL, MODEL, PERFORMANCE, PREDICTIONS, SLATE, WORKFLOW_STATUS, check,
)
from database import DatabaseError, MissingColumnError, MissingTableError  # noqa: E402
from test_app import CountingFakeDB, FakeDB, prediction  # noqa: E402

TODAY = date(2026, 9, 24)  # offseason, like the real "today" of this build
NOW = datetime(2026, 9, 24, 16, 0, tzinfo=timezone.utc)
HOSTILE = "<img src=x onerror=alert(1)>"
V2_ON = {"NBA_SCHEMA_V2": "true"}
V2_OFF = {"NBA_SCHEMA_V2": "false"}


def season_tables():
    """A small 2025-26 season: two settled nights and one unsettled night."""
    preds = [
        prediction(22501100, "2026-04-10", "SAC", "GSW", 1, home_win_prob="0.61",
                   away_win_prob="0.39", bet_amount=55.58, odds="-105", profit_loss=52.93,
                   bet_placed="SAC"),
        prediction(22501101, "2026-04-10", "NYK", "BOS", 0, home_win_prob="0.58",
                   away_win_prob="0.42", bet_amount=25.0, odds="-118", profit_loss=-25.0,
                   bet_placed="NYK"),
        prediction(22501102, "2026-04-10", "ORL", "MIA", 1, home_win_prob="0.55",
                   away_win_prob="0.45", odds="-140"),
        prediction(22501150, "2026-04-11", "PHX", "LAL", 1, home_win_prob="0.70",
                   away_win_prob="0.30", bet_amount=40.0, odds="+120", profit_loss=48.0,
                   bet_placed="PHX"),
        prediction(22501151, "2026-04-11", "DEN", "MIN", 0, home_win_prob="0.66",
                   away_win_prob="0.34", bet_amount=30.0, odds="-110", profit_loss=-30.0,
                   bet_placed="DEN"),
        prediction(22501190, "2026-04-12", "CLE", "MIL", None, home_win_prob="0.64",
                   away_win_prob="0.36", bet_amount=20.0, odds="-150", bet_placed="CLE"),
        prediction(22501191, "2026-04-12", "TOR", "WAS", None),
    ]
    features, elo = [], []
    for i, (home, away) in enumerate([("SAC", "GSW"), ("NYK", "BOS"), ("ORL", "MIA"),
                                      ("PHX", "LAL"), ("DEN", "MIN"), ("CLE", "MIL"),
                                      ("TOR", "WAS")]):
        home_id, away_id = 100 + i, 200 + i
        features.append({
            "GAME_DATE": "2026-03-20", "HOME_TEAM_ABBREVIATION": home, "HOME_TEAM_ID": home_id,
            "HOME_roll_PTS": 115.0, "HOME_roll_FG_PCT": 0.48, "HOME_roll_REB": 44.0,
            "HOME_roll_AST": 27.0, "HOME_roll_TOV": 13.0, "HOME_roll_STOCKS": 12.0,
            "HOME_rest_days": "2.0",
            "AWAY_TEAM_ABBREVIATION": away, "AWAY_TEAM_ID": away_id,
            "AWAY_roll_PTS": "112.5", "AWAY_roll_FG_PCT": "0.47", "AWAY_roll_REB": "43.0",
            "AWAY_roll_AST": "25.0", "AWAY_roll_TOV": "14.5", "AWAY_roll_STOCKS": "13.0",
            "AWAY_rest_days": "1.0",
        })
        elo.append({"GAME_DATE": "2026-03-20", "HOME_TEAM_ID": home_id, "AWAY_TEAM_ID": away_id,
                    "HOME_ELO": 1550.0, "AWAY_ELO": 1490.0})
    return {"predictions": preds, "features": features, "elo": elo}


def v2_tables():
    """season_tables plus every [M] table and column (post-Gate M)."""
    tables = season_tables()
    for row in tables["predictions"]:
        row["game_id"] = str(row["game_id"]).zfill(10)
        row.update({
            "season": "2025-26", "tip_time_utc": f"{row['game_date']}T23:30:00Z",
            "bookmaker": "FanDuel" if row["bet_amount"] else None,
            "implied_prob": None, "edge": None, "bankroll_at_bet": 1111.67,
            "kelly_full": 0.2, "kelly_fraction": 0.25, "model_name": "legacy-calibrated-logistic",
            "predicted_at": f"{row['game_date']}T22:00:00Z",
            "status": "final" if row["correct"] is not None else "scheduled",
            "home_score": 110 if row["correct"] is not None else None,
            "away_score": 100 if row["correct"] is not None else None,
            "skip_reason": None,
        })
    tables["book_odds"] = [
        {"game_id": "0022501100", "bookmaker": b, "home_price": hp, "away_price": ap}
        for b, hp, ap in [("DraftKings", -113, -104), ("FanDuel", -105, -117),
                          ("BetMGM", -107, -115), ("BetRivers", None, None)]
    ]
    tables["bankroll"] = [
        {"date": "2026-04-09", "balance": 1000.0},
        {"date": "2026-04-10", "balance": 1027.93},
        {"date": "2026-04-11", "balance": 1045.93},
    ]
    tables["games"] = [
        {"GAME_DATE": f"2026-03-{d:02d}", "TEAM_ABBREVIATION": "SAC", "WL": wl, "SEASON": "2025-26"}
        for d, wl in zip(range(1, 13), "WWLWLWWLWWLW")
    ]
    tables["model_runs"] = [{
        "trained_at": "2026-09-18T01:11:09Z", "production_model": "legacy-calibrated-logistic",
        "cutoff_date": "2025-02-25", "test_games": 1596,
        "leaderboard": [
            {"rank": 5, "model": "legacy-calibrated-logistic", "test_games": 1596,
             "accuracy": 0.6817, "log_loss": 0.6194, "brier_score": 0.2089, "roc_auc": 0.7295,
             "baseline_home_win_rate": 0.5501},
            {"rank": 1, "model": "current-xgboost", "accuracy": 0.6704, "log_loss": 0.6082,
             "brier_score": 0.2100},
        ],
    }]
    tables["workflow_log"] = [
        {"run_date": "2026-09-24", "kind": "morning", "trigger": "schedule",
         "started_at": "2026-09-24T10:00:03Z", "finished_at": "2026-09-24T10:02:41Z",
         "status": "success", "pipeline_ok": True, "predict_ok": None, "sms_sent": True,
         "notes": ""},
        {"run_date": "2026-09-23", "kind": "predict", "trigger": "schedule",
         "started_at": "2026-09-23T22:00:00Z", "finished_at": "2026-09-23T22:01:00Z",
         "status": "failed", "pipeline_ok": None, "predict_ok": False, "sms_sent": False,
         "notes": "predict failed (exit code 1)"},
    ]
    return tables


class ApiTestCase(unittest.TestCase):
    env = V2_OFF

    def setUp(self):
        self.client = dashboard.app.test_client()
        self.db = FakeDB(self.tables())
        for target, value in (("select_rows", self.db), ("today_et", lambda: TODAY),
                              ("now_utc", lambda: NOW)):
            patcher = patch.object(dashboard, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {**self.env, "ALLOW_RUN_WORKFLOW": "false"})
        env.start()
        self.addCleanup(env.stop)

    def tables(self):
        return season_tables()

    def get(self, url, status=200):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        return response

    def assert_shape(self, body, shape):
        errors = check(body, shape)
        self.assertEqual(errors, [], "\n".join(errors))


ROUTES = {
    "/api/slate?date=2026-04-10": SLATE,
    "/api/slate": SLATE,
    "/api/game/0022501100": GAME_DETAIL,
    "/api/days": DAYS,
    "/api/performance": PERFORMANCE,
    "/api/performance?season=all": PERFORMANCE,
    "/api/predictions": PREDICTIONS,
    "/api/model": MODEL,
    "/api/workflow-status": WORKFLOW_STATUS,
}


ALL_E_ROUTES = {"/api/days"}
# Routes that read an [M] table (not just [M] predictions columns) on this fixture.
M_TABLE_ROUTES = {"/api/slate?date=2026-04-10", "/api/game/0022501100", "/api/performance",
                  "/api/performance?season=all", "/api/model", "/api/workflow-status"}


class PreMigrationShapeTests(ApiTestCase):
    def test_every_route_matches_the_contract_and_flags_migration_pending(self):
        for url, shape in ROUTES.items():
            with self.subTest(url=url):
                body = self.get(url).get_json()
                self.assert_shape(body, shape)
                # /api/days is all [E] data (04 sec5), so nothing is pending there.
                self.assertEqual(body["migration_pending"], url not in ALL_E_ROUTES)

    def test_no_route_reads_an_m_table_before_the_migration(self):
        for url in ROUTES:
            self.db.calls.clear()
            self.get(url)
            tables = {table for table, _ in self.db.calls}
            self.assertFalse(tables & {"bankroll", "book_odds", "workflow_log", "model_runs",
                                       "games"}, f"{url} read {tables}")

    def test_slate_fields_that_need_gate_m_are_null(self):
        body = self.get("/api/slate?date=2026-04-10").get_json()
        game = next(g for g in body["games"] if g["game_id"] == "0022501100")
        self.assertIsNone(game["home"]["record"])  # games is incomplete until the re-collect
        self.assertIsNone(game["home"]["l10"])
        self.assertIsNone(game["book_grid"])
        self.assertIsNone(game["tip_time_utc"])
        self.assertIsNone(game["bet"]["bankroll_at_bet"])
        self.assertIsNone(body["recap"]["bankroll_before"])


class SlateTests(ApiTestCase):
    def test_a_settled_night_is_all_final_with_a_recap(self):
        body = self.get("/api/slate?date=2026-04-10").get_json()
        self.assertEqual(body["phase"], "all_final")
        self.assertTrue(body["is_past"])
        self.assertEqual(body["season"], "2025-26")
        self.assertEqual(body["last_slate_date"], None)
        self.assertEqual(body["summary"]["games"], 3)
        self.assertEqual(body["summary"]["bets_placed"], 2)
        self.assertAlmostEqual(body["summary"]["staked"], 80.58)
        self.assertAlmostEqual(body["summary"]["settled_pl"], 27.93)
        recap = body["recap"]
        self.assertEqual(recap["picks"], "2-1")
        self.assertEqual(recap["bets"], "1-1")
        self.assertAlmostEqual(recap["net_pl"], 27.93)
        self.assertEqual(recap["best_bet"], {"game_id": "0022501100", "profit_loss": 52.93})
        self.assertEqual(recap["worst_bet"], {"game_id": "0022501101", "profit_loss": -25.0})

    def test_game_fields_are_computed_from_the_prediction(self):
        body = self.get("/api/slate?date=2026-04-10").get_json()
        game = next(g for g in body["games"] if g["game_id"] == "0022501100")
        self.assertEqual(game["status"], "final")
        self.assertEqual(game["home"]["name"], "Sacramento Kings")
        self.assertEqual(game["pick"], "SAC")
        self.assertEqual(game["odds"], -105)
        self.assertAlmostEqual(game["implied_prob"], 105 / 205)
        self.assertAlmostEqual(game["edge"], 0.61 - 105 / 205)
        self.assertEqual(game["bet"]["result"], "hit")
        self.assertEqual(game["bet"]["side"], "SAC")
        no_bet = next(g for g in body["games"] if g["game_id"] == "0022501102")
        self.assertIsNone(no_bet["bet"])
        self.assertEqual(no_bet["result"], "hit")

    def test_an_unsettled_past_night_is_still_picks_posted(self):
        body = self.get("/api/slate?date=2026-04-12").get_json()
        self.assertEqual(body["phase"], "picks_posted")
        self.assertEqual(body["last_slate_date"], "2026-04-11")
        self.assertTrue(all(g["status"] == "scheduled" for g in body["games"]))

    def test_offseason_today_is_no_games_with_a_link_to_the_last_slate(self):
        body = self.get("/api/slate").get_json()
        self.assertEqual(body["date"], "2026-09-24")
        self.assertEqual(body["phase"], "no_games")
        self.assertTrue(body["offseason"])
        self.assertEqual(body["last_slate_date"], "2026-04-12")
        self.assertEqual(body["games"], [])
        self.assertIsNone(body["recap"])

    def test_a_day_within_a_week_of_the_last_slate_waits_for_predictions(self):
        with patch.object(dashboard, "today_et", lambda: date(2026, 4, 14)):
            body = self.get("/api/slate").get_json()
        self.assertEqual(body["phase"], "before_predictions")
        self.assertFalse(body["offseason"])

    def test_a_past_date_with_no_games_is_no_games(self):
        body = self.get("/api/slate?date=2026-04-01").get_json()
        self.assertEqual(body["phase"], "no_games")
        self.assertFalse(body["offseason"])

    def test_bad_date_is_a_bad_request(self):
        for value in ("2026-4-1", "yesterday", "2026-13-01", "<script>"):
            with self.subTest(value=value):
                body = self.get(f"/api/slate?date={value}", status=400).get_json()
                self.assertEqual(body["error"], "bad_request")

    def test_cache_headers_split_today_and_past(self):
        self.assertEqual(self.get("/api/slate").headers["Cache-Control"],
                         dashboard.CACHE_SLATE_TODAY)
        self.assertEqual(self.get("/api/slate?date=2026-04-10").headers["Cache-Control"],
                         dashboard.CACHE_PAST)


class GameTests(ApiTestCase):
    def test_game_detail_has_the_tape_and_result(self):
        body = self.get("/api/game/0022501100").get_json()
        self.assertEqual(body["game"]["game_id"], "0022501100")
        tape = body["tape"]
        self.assertEqual(tape["home"]["elo"], 1550.0)
        self.assertEqual(tape["away"]["elo"], 1490.0)
        self.assertEqual(tape["home"]["rest_days"], 2.0)
        self.assertEqual(tape["better"]["elo"], "home")
        self.assertEqual(tape["better"]["roll_tov"], "home")  # 13.0 < 14.5: fewer is better
        self.assertEqual(tape["better"]["rest_days"], "home")
        self.assertEqual(body["result"]["winner"], "SAC")
        self.assertEqual(body["result"]["correct"], 1)

    def test_unsettled_game_has_no_result(self):
        self.assertIsNone(self.get("/api/game/0022501190").get_json()["result"])

    def test_bad_and_unknown_ids(self):
        for bad in ("22501100", "00225011000", "abcdefghij"):
            with self.subTest(bad=bad):
                self.get(f"/api/game/{bad}", status=400)
        self.assertEqual(self.get("/api/game/0099999999", status=404).get_json(),
                         {"error": "not_found"})


class DaysTests(ApiTestCase):
    def test_days_lists_newest_first(self):
        body = self.get("/api/days").get_json()
        self.assertEqual([d["date"] for d in body["days"]],
                         ["2026-04-12", "2026-04-11", "2026-04-10"])
        first, last = body["days"][0], body["days"][-1]
        self.assertEqual(first["pending"], 2)
        self.assertEqual(first["picks"], "0-0")
        self.assertEqual(last, {"date": "2026-04-10", "games": 3, "picks": "2-1", "bets": "1-1",
                                "net_pl": 27.93, "pending": 0})
        self.assertFalse(body["has_earlier"])

    def test_end_and_n_window(self):
        body = self.get("/api/days?end=2026-04-11&n=1").get_json()
        self.assertEqual([d["date"] for d in body["days"]], ["2026-04-11"])
        self.assertTrue(body["has_earlier"])

    def test_bad_params(self):
        for query in ("n=0", "n=32", "n=abc", "end=04-11-2026"):
            with self.subTest(query=query):
                self.get(f"/api/days?{query}", status=400)


class PerformanceTests(ApiTestCase):
    def test_fallback_bankroll_is_1000_plus_cumulative_pl(self):
        body = self.get("/api/performance?season=2025-26").get_json()
        self.assertTrue(body["migration_pending"])
        series = body["series"]
        self.assertEqual(series[0], {"date": "2026-04-09", "bankroll": 1000.0, "nightly_pl": 0.0,
                                     "bets": "0-0", "picks": "0-0", "pending": 0})
        self.assertEqual([p["bankroll"] for p in series[1:]], [1027.93, 1045.93, 1045.93])
        kpis = body["kpis"]
        self.assertEqual(kpis["bankroll"], 1045.93)
        self.assertEqual(kpis["bets"], "2-2")
        self.assertEqual(kpis["picks"], "3-2")
        self.assertAlmostEqual(kpis["accuracy"], 0.6)
        self.assertAlmostEqual(kpis["staked"], 150.58)
        self.assertAlmostEqual(kpis["net_pl"], 45.93)
        self.assertEqual(kpis["pending"], 2)
        self.assertEqual(body["recent_bets"], ["W", "L", "W", "L"])

    def test_drawdown_uses_peak_and_trough_dates(self):
        self.db.tables["predictions"].append(
            prediction(22501160, "2026-04-11", "UTA", "POR", 0, bet_amount=100.0, odds="+150",
                       profit_loss=-100.0))
        kpis = self.get("/api/performance").get_json()["kpis"]
        self.assertEqual(kpis["max_drawdown"],
                         {"amount": 82.0, "peak_date": "2026-04-10", "trough_date": "2026-04-11"})

    def test_splits_bucket_by_confidence_and_edge(self):
        splits = self.get("/api/performance").get_json()["splits"]
        self.assertEqual(splits["book"], [])  # bookmaker is [M]
        confidence = {s["key"]: s for s in splits["confidence"]}
        self.assertEqual(set(confidence), {"high", "medium"})
        self.assertEqual(confidence["high"]["bets"], 2)  # 0.70 and 0.66
        self.assertEqual(sum(s["bets"] for s in splits["edge"]), 4)

    def test_malformed_season_is_a_bad_request(self):
        self.get("/api/performance?season=2025", status=400)


class PredictionsTests(ApiTestCase):
    def test_newest_first_and_paged(self):
        body = self.get("/api/predictions?page_size=2").get_json()
        self.assertEqual(body["total"], 7)
        self.assertEqual([r["game_id"] for r in body["rows"]], ["0022501191", "0022501190"])
        self.assertEqual(body["rows"][0]["result"], "pending")
        body = self.get("/api/predictions?page_size=2&page=4").get_json()
        self.assertEqual([r["game_id"] for r in body["rows"]], ["0022501100"])

    def test_filters(self):
        cases = {
            "team=sac": 1, "team=Kings": 1, "team=Celtics": 1, "bets_only=true": 5,
            "result=hit": 3, "result=miss": 2, "result=pending": 2,
            "min_edge=0.1": 2, "bets_only=true&result=miss": 2,
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(self.get(f"/api/predictions?{query}").get_json()["total"],
                                 expected)

    def test_bad_params(self):
        for query in ("result=win", "bets_only=maybe", "min_edge=abc", "min_edge=5",
                      "page=0", "page_size=101", "page=x", "team=%3Cscript%3E"):
            with self.subTest(query=query):
                self.get(f"/api/predictions?{query}", status=400)


class ModelTests(ApiTestCase):
    def test_pre_migration_model_fields_are_null_but_season_numbers_are_real(self):
        body = self.get("/api/model").get_json()
        self.assertIsNone(body["production_model"])
        self.assertIsNone(body["test"])
        self.assertEqual(body["leaderboard"], [])
        self.assertEqual(body["season_live"], {"season": "2025-26", "picks": 5,
                                               "accuracy": 0.6})
        self.assertEqual(sum(b["n"] for b in body["calibration"]), 5)


class WorkflowStatusTests(ApiTestCase):
    def test_public_view_never_imports_or_asks_the_runner(self):
        with patch.object(daily_workflow, "workflow_is_running") as running:
            body = self.get("/api/workflow-status").get_json()
        running.assert_not_called()
        self.assertFalse(body["controls_allowed"])
        self.assertEqual(body["latest"], {"morning": None, "predict": None, "manual": None})

    def test_local_view_reports_running_and_is_never_cached(self):
        with patch.dict(os.environ, {"ALLOW_RUN_WORKFLOW": "true"}), \
                patch.object(daily_workflow, "workflow_is_running", return_value=True), \
                patch.object(daily_workflow, "run_workflow_async") as run_async:
            os.environ.pop("VERCEL", None)
            response = self.client.get(
                "/api/workflow-status", headers={"Host": "127.0.0.1:5000",
                                                 "X-Requested-With": "run-now"},
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            )
        run_async.assert_not_called()
        body = response.get_json()
        self.assertTrue(body["controls_allowed"])
        self.assertTrue(body["running"])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_controls_are_never_allowed_on_vercel(self):
        with patch.dict(os.environ, {"ALLOW_RUN_WORKFLOW": "true", "VERCEL": "1"}):
            response = self.client.get(
                "/api/workflow-status", headers={"Host": "127.0.0.1:5000",
                                                 "X-Requested-With": "run-now"},
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            )
        self.assertFalse(response.get_json()["controls_allowed"])


class PostMigrationTests(ApiTestCase):
    env = V2_ON

    def tables(self):
        return v2_tables()

    def test_every_route_matches_the_contract_without_migration_pending(self):
        for url, shape in ROUTES.items():
            with self.subTest(url=url):
                body = self.get(url).get_json()
                self.assert_shape(body, shape)
                self.assertFalse(body["migration_pending"], url)

    def test_slate_uses_book_odds_records_and_bankroll(self):
        body = self.get("/api/slate?date=2026-04-10").get_json()
        game = next(g for g in body["games"] if g["game_id"] == "0022501100")
        grid = game["book_grid"]
        self.assertEqual(grid["books"], dashboard.PREFERRED_BOOKS)
        self.assertEqual(grid["home"], [-113, -105, -107, None, None])
        self.assertEqual(grid["best_home_idx"], 1)
        self.assertEqual(grid["best_away_idx"], 0)
        self.assertEqual(game["home"]["record"], "8-4")
        self.assertEqual(game["home"]["l10"], "LWLWWLWWLW")
        self.assertEqual(game["bookmaker"], "FanDuel")
        self.assertEqual(game["tip_time_utc"], "2026-04-10T23:30:00Z")
        self.assertEqual(body["recap"]["bankroll_before"], 1000.0)
        self.assertEqual(body["recap"]["bankroll_after"], 1027.93)

    def test_performance_reads_the_bankroll_table(self):
        body = self.get("/api/performance").get_json()
        self.assertEqual(body["series"][0]["bankroll"], 1000.0)
        self.assertEqual(body["kpis"]["bankroll"], 1045.93)
        books = {s["key"] for s in body["splits"]["book"]}
        self.assertEqual(books, {"FanDuel"})

    def test_model_reads_the_latest_model_run(self):
        body = self.get("/api/model").get_json()
        self.assertEqual(body["production_model"], "legacy-calibrated-logistic")
        self.assertEqual(body["test"]["games"], 1596)
        self.assertEqual(body["test"]["accuracy"], 0.6817)
        self.assertEqual(body["test"]["brier"], 0.2089)
        self.assertEqual(len(body["leaderboard"]), 2)

    def test_workflow_states(self):
        latest = self.get("/api/workflow-status").get_json()["latest"]
        self.assertEqual(latest["morning"]["state"], "ok")
        self.assertEqual(latest["predict"]["state"], "failed")
        self.assertEqual(latest["predict"]["notes"], "predict failed (exit code 1)")
        self.assertIsNone(latest["manual"])

    def test_missed_morning_run_and_stale_running_run(self):
        log = self.db.tables["workflow_log"]
        log[0]["run_date"] = "2026-09-23"  # nothing today, and it's past 06:30 ET
        log.insert(0, {"run_date": "2026-09-24", "kind": "manual", "trigger": "manual",
                       "started_at": "2026-09-24T15:30:00Z", "finished_at": None,
                       "status": "running", "pipeline_ok": None, "predict_ok": None,
                       "sms_sent": None, "notes": None})
        latest = self.get("/api/workflow-status").get_json()["latest"]
        self.assertEqual(latest["morning"]["state"], "missed")
        self.assertEqual(latest["manual"]["state"], "running")
        log[0]["started_at"] = "2026-09-24T12:00:00Z"  # 4h ago: it died
        latest = self.get("/api/workflow-status").get_json()["latest"]
        self.assertEqual(latest["manual"]["state"], "failed")

    def test_missing_m_tables_degrade_to_migration_pending(self):
        for table in ("book_odds", "bankroll", "games", "model_runs", "workflow_log"):
            self.db.errors[table] = MissingTableError(f"Reading {table} failed: table is missing")
        for url, shape in ROUTES.items():
            with self.subTest(url=url):
                body = self.get(url).get_json()
                self.assert_shape(body, shape)
                self.assertEqual(body["migration_pending"], url in M_TABLE_ROUTES, url)

    def test_missing_v2_prediction_columns_fall_back_to_the_base_columns(self):
        real = self.db

        def fake(table, **kwargs):
            if table == "predictions" and "tip_time_utc" in kwargs.get("columns", ""):
                raise MissingColumnError("Reading predictions failed: column is missing")
            return real(table, **kwargs)

        with patch.object(dashboard, "select_rows", fake):
            body = self.get("/api/slate?date=2026-04-10").get_json()
        self.assert_shape(body, SLATE)
        self.assertTrue(body["migration_pending"])
        self.assertEqual(len(body["games"]), 3)

    def test_game_id_is_matched_as_text_after_the_migration(self):
        self.assertEqual(self.get("/api/game/0022501100").get_json()["game"]["bookmaker"],
                         "FanDuel")


def big_slate(n_games, game_date="2026-04-10", v2=False):
    """n_games on one date, with features/elo (and [M] rows when v2) for every team."""
    tables = v2_tables() if v2 else season_tables()
    preds, features, elo, odds, games = [], [], [], [], []
    for i in range(n_games):
        home, away = f"H{i:02d}", f"A{i:02d}"
        gid = 22501300 + i
        row = prediction(gid, game_date, home, away, 1, bet_amount=10.0, odds="120",
                         profit_loss=12.0)
        if v2:
            row.update({k: None for k in dashboard.PREDICTION_V2_COLUMNS.split(",")
                        if k not in row})
            row["game_id"] = str(gid).zfill(10)
            row["status"] = "final"
            odds.append({"game_id": row["game_id"], "bookmaker": "FanDuel",
                         "home_price": 120, "away_price": -140})
            games.append({"GAME_DATE": "2026-04-01", "TEAM_ABBREVIATION": home, "WL": "W",
                          "SEASON": "2025-26"})
        preds.append(row)
        features.append({"GAME_DATE": "2026-04-01", "HOME_TEAM_ABBREVIATION": home,
                         "HOME_TEAM_ID": 500 + i, "AWAY_TEAM_ABBREVIATION": away,
                         "AWAY_TEAM_ID": 600 + i})
        elo.append({"GAME_DATE": "2026-04-01", "HOME_TEAM_ID": 500 + i,
                    "AWAY_TEAM_ID": 600 + i, "HOME_ELO": 1500.0, "AWAY_ELO": 1500.0})
    tables["predictions"] = preds
    tables["features"] = features
    tables["elo"] = elo
    if v2:
        tables["book_odds"] = odds
        tables["games"] = games
    return tables


class QueryBudgetTests(unittest.TestCase):
    """API-F1/F20: call counts are constant in slate size and bounded."""

    BUDGET_PRE_M = {"/api/slate?date=2026-04-10": 2, "/api/game/0022501300": 5,
                    "/api/days": 2, "/api/performance": 2, "/api/predictions": 2,
                    "/api/model": 2, "/api/workflow-status": 0}
    # Post-M adds book_odds and games (slate, game) and bankroll (recap, performance); the
    # game drawer's 7 is the accepted API-F20 shape: constant, bounded and CDN-cached.
    BUDGET_POST_M = {"/api/slate?date=2026-04-10": 5, "/api/game/0022501300": 7,
                     "/api/days": 2, "/api/performance": 3, "/api/predictions": 2,
                     "/api/model": 3, "/api/workflow-status": 1}

    def count(self, url, n_games, v2):
        counting = CountingFakeDB(big_slate(n_games, v2=v2))
        env = {**(V2_ON if v2 else V2_OFF), "ALLOW_RUN_WORKFLOW": "false"}
        with patch.object(dashboard, "select_rows", counting), \
                patch.object(dashboard, "today_et", lambda: TODAY), \
                patch.dict(os.environ, env):
            response = dashboard.app.test_client().get(url)
        self.assertEqual(response.status_code, 200, url)
        return counting.total_calls

    def test_call_counts_are_constant_and_within_budget(self):
        for v2, budget in ((False, self.BUDGET_PRE_M), (True, self.BUDGET_POST_M)):
            for url, expected in budget.items():
                with self.subTest(url=url, v2=v2):
                    one = self.count(url, 1, v2)
                    fifteen = self.count(url, 15, v2)
                    self.assertEqual(one, fifteen)
                    self.assertEqual(fifteen, expected)


class ErrorAndHygieneTests(ApiTestCase):
    def test_database_errors_are_503_without_exception_text(self):
        self.db.errors["predictions"] = DatabaseError("Reading predictions failed: detail-XYZ")
        for url in ROUTES:
            if url == "/api/workflow-status":
                continue  # reads no predictions
            with self.subTest(url=url):
                response = self.get(url, status=503)
                self.assertEqual(response.get_json(), {"error": "database_unavailable"})
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn("detail-XYZ", response.get_data(as_text=True))

    def test_no_response_contains_the_secret_key(self):
        secret = "sb_" "secret_TESTVALUE"  # split so secret scanners skip this fake key
        with patch.dict(os.environ, {"SUPABASE_SECRET_KEY": secret}):
            bodies = [self.client.get(url).get_data(as_text=True) for url in ROUTES]
            self.db.errors["predictions"] = DatabaseError(f"Reading predictions failed: {secret}")
            bodies += [self.client.get(url).get_data(as_text=True) for url in ROUTES]
        for body in bodies:
            self.assertNotIn("TESTVALUE", body)

    def test_hostile_strings_come_back_as_json_data(self):
        self.db.tables["predictions"].append(
            prediction(22501400, "2026-04-11", HOSTILE, "BOS", 1, predicted_winner=HOSTILE))
        for url in ("/api/slate?date=2026-04-11", "/api/predictions", "/api/game/0022501400"):
            with self.subTest(url=url):
                response = self.get(url)
                self.assertEqual(response.mimetype, "application/json")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertIn(HOSTILE, response.get_data(as_text=True).replace("\\u003c", "<")
                              .replace("\\u003e", ">"))
        rows = self.get("/api/predictions").get_json()["rows"]
        self.assertIn(f"BOS @ {HOSTILE}", [r["matchup"] for r in rows])


class PostMigrationHostileTests(ApiTestCase):
    env = V2_ON

    def tables(self):
        tables = v2_tables()
        tables["book_odds"][0]["bookmaker"] = HOSTILE
        tables["model_runs"][0]["production_model"] = HOSTILE
        tables["model_runs"][0]["leaderboard"][0]["model"] = HOSTILE
        tables["workflow_log"][0]["notes"] = HOSTILE
        return tables

    def test_hostile_book_model_and_notes_pass_through_as_data(self):
        game = self.get("/api/game/0022501100").get_json()["game"]
        self.assertIn(HOSTILE, game["book_grid"]["books"])
        self.assertEqual(self.get("/api/model").get_json()["production_model"], HOSTILE)
        latest = self.get("/api/workflow-status").get_json()["latest"]
        self.assertEqual(latest["morning"]["notes"], HOSTILE)


if __name__ == "__main__":
    unittest.main()
