"""Learned play probabilities (src/pplay.py): fitting, lookup fallbacks, appearance counts, the committed mapping and the
flagged integration in GameAvailability (default off must not change anything)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
import player_store  # noqa: E402
import pplay  # noqa: E402

DEN, LAL = 1610612743, 1610612747


def rows(status, n, played, base_min=25.0, app=10, reason=""):
    return [dict(status=status, reason=reason, base_min=base_min, app_l10=app, played=1 if i < played else 0)
            for i in range(n)]


class FitLookupTests(unittest.TestCase):
    def setUp(self):
        data = (rows("none", 400, 392, app=10) + rows("none", 200, 12, app=0)          # unlisted: 98% vs 6%
                + rows("questionable", 300, 156, reason="Injury/Illness - Left Ankle; Sprain")
                + rows("questionable", 120, 22, reason="G League - Two-Way", base_min=6.0)
                + rows("out", 500, 1) + rows("probable", 100, 91, reason="Injury/Illness - Illness; Illness"))
        self.t = pplay.fit_table(data, built_from="synthetic", cutoff="2025-01-01")

    def test_unlisted_rule_depends_on_recent_appearances(self):
        self.assertGreater(pplay.lookup(self.t, "none", "", 25.0, 10), 0.95)
        self.assertLess(pplay.lookup(self.t, "none", "", 25.0, 0), 0.10)

    def test_listed_status_depends_on_reason_group(self):
        inj = pplay.lookup(self.t, "questionable", "Injury/Illness - Right Knee; Soreness", 25.0, 10)
        gl = pplay.lookup(self.t, "questionable", "G League - On Assignment", 6.0, 10)
        self.assertAlmostEqual(inj, 0.52, delta=0.04)
        self.assertLess(gl, 0.25)
        self.assertLess(pplay.lookup(self.t, "out", "", 25.0, 10), 0.02)

    def test_fallbacks_go_to_the_hand_table(self):
        self.assertEqual(pplay.lookup(None, "questionable", "", 20.0, 5), config.STATUS_TO_P_PLAY["questionable"])
        self.assertEqual(pplay.lookup(self.t, "none", "", 20.0, None), 1.0)             # no game log with the team
        self.assertEqual(pplay.lookup(self.t, "doubtful", "", 20.0, 5), config.STATUS_TO_P_PLAY["doubtful"])  # no data
        sparse = pplay.fit_table(rows("questionable", 5, 5))                          # below min_cell_n
        self.assertEqual(pplay.lookup(sparse, "questionable", "", 20.0, 5), config.STATUS_TO_P_PLAY["questionable"])

    def test_estimates_are_shrunk_toward_the_parent_and_are_probabilities(self):
        tiny = pplay.fit_table(rows("none", 400, 392, app=10) + rows("none", 45, 0, app=10, base_min=3.0))
        cell = tiny["none"]["app4|bm0"]
        self.assertGreater(cell["p"], 0.0)                                              # 0/45 observed, shrunk upward
        self.assertLess(cell["p"], 0.4)
        for section in ("none", "listed"):
            for v in self.t[section].values():
                self.assertTrue(0.0 <= v["p"] <= 1.0 and v["n"] > 0)

    def test_buckets_and_reason_groups(self):
        self.assertEqual([pplay.bm_bucket(x) for x in (0, 5.9, 6, 17.9, 24, 40)], [0, 0, 1, 2, 4, 4])
        self.assertEqual([pplay.app_bucket(x) for x in (0, 1, 3, 4, 9, 10, 12)], [0, 1, 1, 2, 3, 4, 4])
        self.assertEqual(pplay.reason_group("G League - Two-Way"), "g_league")
        self.assertEqual(pplay.reason_group("Injury/Illness - Left Ankle; Sprain"), "injury")
        self.assertEqual(pplay.reason_group("Rest"), "other")
        self.assertEqual(pplay.reason_group(None), "other")

    def test_load_mapping_rejects_missing_and_wrong_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(pplay.load_mapping(os.path.join(tmp, "nope.json")))
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                json.dump({"format_version": 99}, fh)
            self.assertIsNone(pplay.load_mapping(bad))
            good = os.path.join(tmp, "good.json")
            with open(good, "w", encoding="utf-8") as fh:
                json.dump(self.t, fh)
            self.assertEqual(pplay.load_mapping(good)["built_from"], "synthetic")


class CommittedMappingTests(unittest.TestCase):
    def test_committed_mapping_is_valid_and_sane(self):
        t = pplay.load_mapping(os.path.join(config.DATA_DIR, "pplay", "pplay_mapping_v1.json"))
        self.assertIsNotNone(t)
        self.assertTrue(t["cutoff_game_date"])
        self.assertLess(pplay.lookup(t, "out", "Injury/Illness - Left Knee; Surgery", 25.0, 0), 0.02)
        self.assertLess(pplay.lookup(t, "doubtful", "Injury/Illness - Illness; Illness", 25.0, 8), 0.08)
        self.assertGreater(pplay.lookup(t, "probable", "Injury/Illness - Illness; Illness", 25.0, 9), 0.85)
        self.assertGreater(pplay.lookup(t, "none", "", 28.0, 10), 0.95)
        self.assertLess(pplay.lookup(t, "none", "", 28.0, 0), 0.15)
        q = pplay.lookup(t, "questionable", "Injury/Illness - Left Ankle; Sprain", 28.0, 10)
        self.assertTrue(0.4 < q < 0.7)


class AppearanceTests(unittest.TestCase):
    def test_counts_are_from_the_teams_previous_ten_games_only(self):
        recs = []
        for g in range(14):
            for pid in (1, 2, 3):
                if pid == 3 and g >= 4:
                    continue                       # player 3 stopped playing after game 3
                recs.append({"game_id": f"g{g:02d}", "player_id": pid, "team_id": DEN, "game_date": f"2026-11-{g + 1:02d}"})
            recs.append({"game_id": f"g{g:02d}", "player_id": 9, "team_id": LAL, "game_date": f"2026-11-{g + 1:02d}"})
        pg = pd.DataFrame(recs)
        got = pplay.appearances_last10(pg, DEN, [1, 2, 3, 4, 9])
        self.assertEqual(got, {1: 10, 2: 10, 3: 0})            # 4 never seen, 9 plays for another team: omitted


class GameAvailabilityFlagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        player_store.close_all()
        self.patches = [patch.dict(os.environ, {"NBA_PLAYER_LOCAL_DB": os.path.join(self.tmp.name, "pd.sqlite"),
                                                "NBA_PLAYER_STORE": "local"})]
        for p in self.patches:
            p.start()
        today = date.today()
        recs = []
        for g in range(15):
            gdate = (today - timedelta(days=40 - 2 * g)).isoformat()
            for team, home, base in ((DEN, 1, 100), (LAL, 0, 200)):
                for k in range(9):
                    if team == DEN and base + k == 101 and g >= 5:
                        continue                   # DEN's 101 (second best minutes) played the first 5 games only
                    recs.append({"game_id": f"00226{g:05d}", "player_id": base + k, "team_id": team, "game_date": gdate,
                                 "season": "2026-27", "is_home": home, "started": None,
                                 "minutes": [36, 34, 32, 30, 28, 26, 24, 20, 10][k]})
        player_store.upsert("player_games", recs)
        as_of = (today - timedelta(days=3)).isoformat()
        player_store.upsert("player_ratings", [
            {"player_id": b + k, "as_of": as_of, "rating_type": "rapm_lite_v1", "value": [8, 6, 1, 0, -1, -2, -2, -3, -4][k],
             "minutes_basis": 1000, "se": 1.0, "version": "t"} for b in (100, 200) for k in range(9)])
        table = pplay.fit_table(rows("none", 500, 490, app=10) + rows("none", 300, 15, app=0), built_from="t")
        self.mapping = os.path.join(self.tmp.name, "map.json")
        with open(self.mapping, "w", encoding="utf-8") as fh:
            json.dump(table, fh)
        self.today = today

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        player_store.close_all()
        self.tmp.cleanup()

    def game(self):
        import availability_predict as ap
        as_of = datetime.now(timezone.utc)
        return ap.GameAvailability("0022600099", self.today.isoformat(), DEN, LAL, as_of,
                                   statuses=pd.DataFrame(), rosters={})

    def test_default_source_is_the_hand_table_and_changes_nothing(self):
        self.assertEqual(config.P_PLAY_SOURCE, "status_table")
        ga = self.game()
        proj = ga.projection[DEN].set_index("player_id")
        self.assertEqual(float(proj.loc[101, "p_play"]), 1.0)
        self.assertEqual(ga.p_play, {})

    def test_learned_source_discounts_a_long_absent_unlisted_player_only(self):
        with patch.object(config, "P_PLAY_SOURCE", "learned_table"), patch.object(config, "P_PLAY_MAPPING_PATH", self.mapping):
            ga = self.game()
        den = ga.projection[DEN].set_index("player_id")
        self.assertLess(float(den.loc[101, "p_play"]), 0.2)        # played 0 of the last 10 games, not on the report
        self.assertGreater(float(den.loc[100, "p_play"]), 0.9)     # played all 10
        self.assertGreater(float(ga.projection[LAL].set_index("player_id").loc[200, "p_play"]), 0.9)

    def test_missing_mapping_falls_back_to_the_hand_table(self):
        with patch.object(config, "P_PLAY_SOURCE", "learned_table"), \
                patch.object(config, "P_PLAY_MAPPING_PATH", os.path.join(self.tmp.name, "absent.json")):
            ga = self.game()
        self.assertEqual(float(ga.projection[DEN].set_index("player_id").loc[101, "p_play"]), 1.0)


if __name__ == "__main__":
    unittest.main()
