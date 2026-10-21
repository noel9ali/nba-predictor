"""Phase 7: availability fields in the read API (shapes, empty-table behaviour, /api/injuries)."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import app as dashboard  # noqa: E402


# These tests use 2025-26 fixtures; pin the clock's season so the live 2026-27 default does not apply.
_season_patch = patch.object(dashboard, "current_season", return_value="2025-26")


def setUpModule():
    _season_patch.start()


def tearDownModule():
    _season_patch.stop()
from contract_shapes import GAME_DETAIL, INJURIES, MODEL, PERFORMANCE, SLATE, check  # noqa: E402
from database import MissingTableError  # noqa: E402
from test_api_v2 import TODAY, NOW, V2_OFF, V2_ON, season_tables  # noqa: E402
from test_app import FakeDB  # noqa: E402

DEN, MIN = 1610612743, 1610612750
GID = "0022501151"           # DEN (home) vs MIN, 2026-04-11, in season_tables()
REPORT = "2026-04-11T21:00:00+00:00"


def availability_tables():
    tables = season_tables()
    for p in tables["predictions"]:
        if str(p["game_id"]).zfill(10) == GID:
            p["model_name"] = "lr-calibrated-availability-v1"
    snap = {"game_id": GID, "game_date": "2026-04-11", "matchup": "MIN@DEN", "source": "nba_official_pdf"}
    tables["injury_snapshots"] = [
        {**snap, "snapshot_id": 1, "team_id": DEN, "player_id": 203999, "player_name_raw": "Jokić, Nikola",
         "status": "questionable", "reason": "Injury/Illness - Left Ankle; Sprain", "report_time": "2026-04-11T17:00:00+00:00"},
        {**snap, "snapshot_id": 2, "team_id": DEN, "player_id": 203999, "player_name_raw": "Jokić, Nikola",
         "status": "out", "reason": "Injury/Illness - Left Ankle; Sprain", "report_time": REPORT},
        {**snap, "snapshot_id": 3, "team_id": MIN, "player_id": 1630162, "player_name_raw": "Edwards, Anthony",
         "status": "questionable", "reason": None, "report_time": REPORT},
        {**snap, "snapshot_id": 4, "team_id": MIN, "player_id": None, "player_name_raw": "Unknown, Guy",
         "status": "out", "reason": "G League - Two-Way", "report_time": REPORT},
    ]
    tables["player_minutes_projection"] = [
        {"game_id": GID, "player_id": 203999, "as_of": "2026-04-11T22:00:00+00:00", "p_play": 0.0, "exp_min": 0.0,
         "min_if_play": 35.0, "role": "inactive"},
        {"game_id": GID, "player_id": 1630162, "as_of": "2026-04-11T22:00:00+00:00", "p_play": 0.5,
         "exp_min": 17.5, "min_if_play": 35.0, "role": "starter"},
    ]
    tables["player_ratings"] = [
        {"player_id": 203999, "as_of": "2026-04-06", "rating_type": "rapm_lite_v1", "value": 9.6, "minutes_basis": 4000},
        {"player_id": 1630162, "as_of": "2026-04-06", "rating_type": "rapm_lite_v1", "value": 3.2, "minutes_basis": 4000},
    ]
    tables["team_availability_features"] = [
        {"game_id": GID, "team_id": DEN, "as_of": "2026-04-11T22:00:00+00:00", "rest_days": 1, "is_b2b": 1,
         "star_out": 1, "rating_type": "rapm_lite_v1", "basis": "report"},
        {"game_id": GID, "team_id": MIN, "as_of": "2026-04-11T22:00:00+00:00", "rest_days": 3, "is_b2b": 0,
         "star_out": 0, "rating_type": "rapm_lite_v1", "basis": "report"},
    ]
    tables["prediction_scenarios"] = [
        {"game_id": GID, "model_name": "lr-calibrated-availability-v1", "scenario_key": "1630162=1", "weight": 0.5,
         "home_win_prob": 0.58, "label": "Anthony Edwards plays"},
        {"game_id": GID, "model_name": "lr-calibrated-availability-v1", "scenario_key": "1630162=0", "weight": 0.5,
         "home_win_prob": 0.66, "label": "Anthony Edwards out"},
    ]
    tables["prediction_factors"] = [
        {"game_id": GID, "model_name": "lr-calibrated-availability-v1", "factor_key": "ELO_DIFF",
         "label": "Elo difference", "group": "base", "prob_points": 8.1, "sort_order": 0},
        {"game_id": GID, "model_name": "lr-calibrated-availability-v1", "factor_key": "availability:0",
         "label": "Nikola Jokić out: -4.2 pts", "group": "availability", "prob_points": -4.2, "sort_order": 1},
        {"game_id": GID, "model_name": "lr-calibrated-availability-v1", "factor_key": "other",
         "label": "Other (calibration and rounding)", "group": "base", "prob_points": 3.1, "sort_order": 2},
    ]
    tables["prediction_availability_inputs"] = [
        {"game_id": GID, "model_name": "lr-calibrated-availability-v1", "prob_range_low": 0.58,
         "prob_range_high": 0.66, "status_changed_after_pred": 1, "predicted_at": "2026-04-11T22:00:00+00:00"},
    ]
    tables["model_runs"] = [{
        "trained_at": "2026-10-07T05:09:34+00:00", "production_model": "gradient-boosting-gridsearch",
        "cutoff_date": "2025-02-25", "test_games": 1596, "leaderboard": [],
        "feature_set_version": "avail_v1+ratings:2026-10-10",
        "candidates": {"rows": [{"model": "lr-calibrated-availability-v1", "feature_set": "baseline+avail_rapm",
                                 "accuracy": 0.69, "log_loss": 0.58, "brier_score": 0.20, "roc_auc": 0.75,
                                 "test_games": 1596}]},
    }]
    return tables


def text_ids(tables, env):
    """predictions.game_id is 10-character text under the v2 schema (bigint before it)."""
    if env is V2_ON:
        for p in tables["predictions"]:
            p["game_id"] = str(p["game_id"]).zfill(10)
    return tables


class AvailabilityApiTests(unittest.TestCase):
    env = V2_ON

    def setUp(self):
        self.client = dashboard.app.test_client()
        self.db = FakeDB(self.tables())
        for target, value in (("select_rows", self.db), ("today_et", lambda: TODAY), ("now_utc", lambda: NOW)):
            p = patch.object(dashboard, target, value)
            p.start()
            self.addCleanup(p.stop)
        env = patch.dict(os.environ, {**self.env, "ALLOW_RUN_WORKFLOW": "false"})
        env.start()
        self.addCleanup(env.stop)

    def tables(self):
        return text_ids(availability_tables(), self.env)

    def get(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def shape(self, body, shape):
        errors = check(body, shape)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_game_detail_fields(self):
        body = self.get(f"/api/game/{GID}")
        self.shape(body, GAME_DETAIL)
        home = body["availability"]["home"]
        self.assertEqual([(p["name"], p["status"]) for p in home], [("Nikola Jokić", "out")])   # newest report
        self.assertEqual(home[0]["rating"], 9.6)
        self.assertEqual(home[0]["impact_pts"], round(9.6 * 35 / 48, 1))
        self.assertEqual(home[0]["p_play"], 0.0)
        away = body["availability"]["away"]
        self.assertEqual([p["name"] for p in away], ["Guy Unknown", "Anthony Edwards"])        # out first
        self.assertIsNone(away[0]["player_id"])
        self.assertEqual(body["rest"], {"home": {"rest_days": 1, "is_b2b": True},
                                        "away": {"rest_days": 3, "is_b2b": False}})
        self.assertEqual(len(body["scenarios"]), 2)
        self.assertEqual(body["prob_range"], {"low": 0.58, "high": 0.66})
        self.assertEqual([f["key"] for f in body["factors"]], ["ELO_DIFF", "availability:0", "other"])

    def test_slate_summary(self):
        body = self.get("/api/slate?date=2026-04-11")
        self.shape(body, SLATE)
        game = next(g for g in body["games"] if g["game_id"] == GID)
        self.assertEqual(game["availability_summary"], {"home_out": 1, "away_out": 1, "key_out": ["Nikola Jokić"],
                                                        "uncertain": True, "status_changed": True})
        other = next(g for g in body["games"] if g["game_id"] != GID)
        self.assertIsNone(other["availability_summary"])

    def test_injuries_route(self):
        body = self.get("/api/injuries?date=2026-04-11")
        self.shape(body, INJURIES)
        self.assertEqual(body["report_time"], "2026-04-11T21:00:00Z")
        self.assertEqual(body["games"][0]["home"]["tricode"], "DEN")
        self.assertEqual(body["games"][0]["away"]["tricode"], "MIN")
        self.assertFalse(body["migration_pending"])
        empty = self.get("/api/injuries?date=2026-04-12")
        self.assertEqual(empty["games"], [])
        self.assertEqual(self.client.get("/api/injuries?date=nope").status_code, 400)

    def test_model_and_performance(self):
        model = self.get("/api/model")
        self.shape(model, MODEL)
        self.assertEqual(model["candidates"][0]["model"], "lr-calibrated-availability-v1")
        self.assertFalse(model["candidates"][0]["promoted"])
        self.assertFalse(model["availability_gate"])
        self.assertEqual(model["feature_set_version"], "avail_v1+ratings:2026-10-10")
        perf = self.get("/api/performance")
        self.shape(perf, PERFORMANCE)
        star = {s["key"]: s for s in perf["splits"]["star_out"]}
        self.assertEqual(star["star_out"]["bets"], 1)                       # the DEN bet on 2026-04-11


class EmptyTablesTests(AvailabilityApiTests):
    """Before the player-data migrations: every new field is an empty list or null, never an error,
    and existing payloads are not flagged migration_pending because of them."""

    def tables(self):
        return text_ids(season_tables(), self.env)

    def setUp(self):
        super().setUp()
        for table in ("injury_snapshots", "player_minutes_projection", "player_ratings", "team_availability_features",
                      "prediction_scenarios", "prediction_factors", "prediction_availability_inputs"):
            self.db.errors[table] = MissingTableError(f"Reading {table} failed: table is missing")

    def test_game_detail_fields(self):
        body = self.get(f"/api/game/{GID}")
        self.shape(body, GAME_DETAIL)
        self.assertEqual(body["availability"], {"home": [], "away": []})
        self.assertIsNone(body["rest"])
        self.assertEqual((body["scenarios"], body["factors"], body["prob_range"]), ([], [], None))
        self.assertFalse(body["migration_pending"])

    def test_slate_summary(self):
        body = self.get("/api/slate?date=2026-04-11")
        self.shape(body, SLATE)
        self.assertTrue(all(g["availability_summary"] is None for g in body["games"]))
        self.assertFalse(body["migration_pending"])

    def test_injuries_route(self):
        body = self.get("/api/injuries?date=2026-04-11")
        self.shape(body, INJURIES)
        self.assertEqual(body["games"], [])
        self.assertTrue(body["migration_pending"])

    def test_model_and_performance(self):
        model = self.get("/api/model")
        self.shape(model, MODEL)
        self.assertEqual(model["candidates"], [])
        perf = self.get("/api/performance")
        self.shape(perf, PERFORMANCE)
        self.assertEqual(perf["splits"]["star_out"], [])


class SchemaV1Tests(AvailabilityApiTests):
    """With the v2 schema off the additive fields are present but empty, and no player tables are read."""
    env = V2_OFF

    def test_game_detail_fields(self):
        body = self.get(f"/api/game/{GID}")
        self.shape(body, GAME_DETAIL)
        self.assertEqual(body["availability"], {"home": [], "away": []})
        self.assertFalse(any(c[0].startswith(("injury", "player_", "prediction_")) for c in self.db.calls))

    def test_slate_summary(self):
        body = self.get("/api/slate?date=2026-04-11")
        self.shape(body, SLATE)
        self.assertTrue(all("availability_summary" not in g for g in body["games"]))

    def test_injuries_route(self):
        body = self.get("/api/injuries?date=2026-04-11")
        self.shape(body, INJURIES)
        self.assertTrue(body["migration_pending"])

    def test_model_and_performance(self):
        perf = self.get("/api/performance")
        self.shape(perf, PERFORMANCE)
        self.assertNotIn("star_out", perf["splits"])


if __name__ == "__main__":
    unittest.main()
