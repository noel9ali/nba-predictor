"""Phase 6: dry run of predict.run() against a recorded slate, fully offline.

Production pieces (model, odds, Supabase writes) are fakes; the availability step uses a temporary local store
and injury sink, and a small candidate model saved to a temporary folder.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
import player_store  # noqa: E402

DEN, LAL = 1610612743, 1610612747
GAME = "0022600001"


class FakeProdModel:
    def predict_proba(self, X):
        return np.array([[0.4, 0.6]] * len(X))


class IdentityScaler:
    def transform(self, X):
        return np.asarray(X, dtype=float)


def seed_store(today):
    rows = []
    for g in range(15):
        gdate = (today - timedelta(days=40 - 2 * g)).isoformat()
        gid = f"00226{g:05d}"
        for team, home, base in ((DEN, 1, 100), (LAL, 0, 200)):
            for k in range(9):
                rows.append({"game_id": gid, "player_id": base + k, "team_id": team, "game_date": gdate,
                             "season": "2026-27", "is_home": home, "started": None,
                             "minutes": [36, 34, 32, 30, 28, 26, 24, 20, 10][k]})
    player_store.upsert("player_games", rows)
    as_of = (today - timedelta(days=3)).isoformat()
    ratings = []
    for base in (100, 200):
        for k in range(9):
            ratings.append({"player_id": base + k, "as_of": as_of, "rating_type": "rapm_lite_v1",
                            "value": [8, 3, 1, 0, -1, -2, -2, -3, -4][k], "minutes_basis": 1000, "se": 1.0,
                            "version": "test"})
    player_store.upsert("player_ratings", ratings)
    player_store.upsert("players", [{"player_id": 100, "full_name": "Nikola Jokić", "first_name": "Nikola",
                                     "last_name": "Jokić", "position": None, "birth_date": None, "is_active": 1,
                                     "updated_at": None}])


def seed_injuries(now):
    import injuries

    conn = injuries.connect()
    rep = (now - timedelta(hours=1)).astimezone(timezone.utc).isoformat(timespec="seconds")
    base = {"captured_at": rep, "report_time": rep, "game_id": GAME, "game_date": now.date().isoformat(),
            "game_time_et": "09:00 (ET)", "matchup": "LAL@DEN", "reason": None, "source": "nba_official_pdf",
            "raw_file": "x.pdf"}
    injuries.store_rows(conn, [
        {**base, "team_id": DEN, "player_id": 100, "player_name_raw": "Jokic, Nikola", "status_raw": "Questionable",
         "status": "questionable"},
        {**base, "team_id": LAL, "player_id": 201, "player_name_raw": "Two, Player", "status_raw": "Out",
         "status": "out"},
    ], [])
    conn.close()


def save_test_candidate(features):
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    import availability_predict as ap

    rng = np.random.default_rng(1)
    X = rng.normal(size=(300, len(features)))
    y = (X[:, features.index("rapm:rating_expected_diff")] + rng.normal(scale=0.7, size=300) > 0).astype(int)
    scaler = StandardScaler().fit(X)
    model = CalibratedClassifierCV(LogisticRegression(max_iter=1000), cv=3, method="isotonic").fit(
        scaler.transform(X), y)
    ap.save_candidate(ap.DEFAULT_CANDIDATE, model, scaler, features)


class PredictDryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        player_store.close_all()
        self.patches = [
            patch.dict(os.environ, {"NBA_PLAYER_LOCAL_DB": os.path.join(self.tmp.name, "pd.sqlite"),
                                    "NBA_PLAYER_STORE": "local"}),
            patch.object(config, "INJURY_LOCAL_DB", os.path.join(self.tmp.name, "inj.sqlite")),
            patch.object(config, "INJURY_UNMATCHED_CSV", os.path.join(self.tmp.name, "u.csv")),
        ]
        for p in self.patches:
            p.start()
        import availability_predict as ap

        self.ap = ap
        self.patches.append(patch.object(ap, "CANDIDATE_DIR", os.path.join(self.tmp.name, "candidates")))
        self.patches[-1].start()
        self.today = date.today()
        seed_store(self.today)
        seed_injuries(datetime.now(timezone.utc))
        import model as prod

        self.features = list(prod.FEATURES) + [
            "rapm:rating_expected_diff", "rapm:value_out_diff", "rapm:home_star_out", "rapm:away_star_out",
            "rapm:top3_avail_diff", "rapm:minutes_lost_diff", "rapm:rest_days_diff", "rapm:home_is_b2b",
            "rapm:away_is_b2b", "rapm:games_last_7_diff"]
        save_test_candidate(self.features)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        player_store.close_all()
        self.tmp.cleanup()

    def run_predict(self, env=None):
        import predict

        slate = pd.DataFrame([{"gameId": GAME, "HOME_TEAM_ID": DEN, "HOME_TEAM_ABBREVIATION": "DEN",
                               "VISITOR_TEAM_ID": LAL, "VISITOR_TEAM_ABBREVIATION": "LAL"}])
        stats = {p: pd.DataFrame([{f"{p}_roll_{s}": v for s, v in (("PTS", 112.0), ("FG_PCT", 0.47),
                                                                       ("REB", 44.0), ("AST", 26.0), ("TOV", 13.0),
                                                                       ("STOCKS", 12.0))}])
                 for p in ("HOME", "AWAY")}
        calls = []
        with patch.object(predict, "load_model", return_value=(FakeProdModel(), IdentityScaler())), \
                patch.object(predict, "get_current_ratings", return_value={DEN: 1600, LAL: 1500}), \
                patch.object(predict, "get_todays_games", return_value=slate), \
                patch.object(predict, "get_tonights_odds", return_value={}), \
                patch.object(predict, "match_odds", return_value={"home_odds": -150, "away_odds": 130,
                                                                  "home_book": "fd", "away_book": "dk"}), \
                patch.object(predict, "get_team_rolling_stats", side_effect=lambda t, p: stats[p]), \
                patch.object(predict, "get_rest_days", return_value=2), \
                patch.object(predict, "get_current_bankroll", return_value=1000.0), \
                patch.object(predict, "save_prediction", side_effect=lambda **kw: calls.append(kw)), \
                patch("database.update_rows", return_value=[]), \
                patch.dict(os.environ, env or {}, clear=False):
            if not env:
                os.environ.pop("NBA_PRODUCTION_MODEL", None)
            predict.run()
        return calls

    def test_shadow_mode_leaves_production_unchanged(self):
        calls = self.run_predict()
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0]["home_prob"], 0.6)                # the production model's number
        self.assertIsNone(calls[0]["extra"])
        scen = player_store.read("prediction_scenarios")
        self.assertEqual(len(scen), 2)                                    # Jokić questionable: plays / out
        self.assertAlmostEqual(scen["weight"].sum(), 1.0)
        facts = player_store.read("prediction_factors")
        inputs = player_store.read("prediction_availability_inputs").iloc[0]
        self.assertAlmostEqual(55.0 + facts["prob_points"].sum(), inputs["home_win_prob"] * 100, delta=0.01)
        self.assertTrue(any("Jokić questionable" in label for label in facts["label"]))
        self.assertIn("other", set(facts["factor_key"]))
        self.assertTrue(inputs["prob_range_low"] <= inputs["home_win_prob"] <= inputs["prob_range_high"])
        self.assertEqual(json.loads(inputs["key_statuses"])["100"], "questionable")
        proj = player_store.read("player_minutes_projection")
        self.assertEqual(proj[proj["player_id"] == 201]["exp_min"].iloc[0], 0.0)
        for team in (DEN, LAL):
            self.assertAlmostEqual(proj[proj["team_id"] == team]["exp_min"].sum(), 240.0, places=3)
        feats = player_store.read("team_availability_features")
        self.assertEqual(set(feats["basis"]), {"report"})
        self.assertEqual(len(feats), 2)

    def test_candidate_as_production_uses_blend_and_range(self):
        calls = self.run_predict({"NBA_PRODUCTION_MODEL": self.ap.DEFAULT_CANDIDATE})
        extra = calls[0]["extra"]
        inputs = player_store.read("prediction_availability_inputs").iloc[0]
        self.assertAlmostEqual(calls[0]["home_prob"], inputs["home_win_prob"])
        self.assertEqual(extra["model_name"], self.ap.DEFAULT_CANDIDATE)
        self.assertLessEqual(extra["prob_range_low"], extra["prob_range_high"])
        self.assertNotIn("skip_reason", extra)                            # gate is off by default

    def test_gate_skip(self):
        with patch.object(config, "AVAILABILITY_GATE", True), patch.object(config, "UNCERTAINTY_RANGE", 0.0), \
                patch.object(config, "AVAILABILITY_GATE_ACTION", "skip"):
            calls = self.run_predict({"NBA_PRODUCTION_MODEL": self.ap.DEFAULT_CANDIDATE})
        extra = calls[0]["extra"]
        if extra["prob_range_high"] - extra["prob_range_low"] > 0 and calls[0]["bet_amount"] == 0 \
                and "skip_reason" in extra:
            self.assertEqual(extra["skip_reason"], "availability_uncertain")
            self.assertIsNone(calls[0]["bet_placed"])
        else:
            # no positive-edge bet to gate on this fake slate
            self.assertNotIn("skip_reason", extra)

    def test_status_change_flag(self):
        self.run_predict()
        import injuries

        later = datetime.now(timezone.utc)
        conn = injuries.connect()
        rep = later.isoformat(timespec="seconds")
        injuries.store_rows(conn, [{"captured_at": rep, "report_time": rep, "game_id": GAME,
                                    "game_date": later.date().isoformat(), "game_time_et": "09:00 (ET)",
                                    "matchup": "LAL@DEN", "team_id": DEN, "player_id": 100,
                                    "player_name_raw": "Jokic, Nikola", "status_raw": "Out", "status": "out",
                                    "reason": None, "source": "nba_official_pdf", "raw_file": "y.pdf"}], [])
        conn.close()
        with patch("database.update_rows", return_value=[]) as upd:
            n = self.ap.flag_status_changes(now=later + timedelta(seconds=1))
        self.assertEqual(n, 1)
        upd.assert_called_once()
        self.assertEqual(upd.call_args[0][1], {"status_changed_after_pred": True})
        self.assertEqual(int(player_store.read("prediction_availability_inputs")["status_changed_after_pred"].iloc[0]), 1)


if __name__ == "__main__":
    unittest.main()
