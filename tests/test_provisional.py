"""Temporary 6 AM picks: status probabilities, earlier-report carry-forward, the tentative SMS (offline)."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import availability_predict as ap  # noqa: E402
import config  # noqa: E402
import daily_workflow  # noqa: E402
import injuries  # noqa: E402


def snapshot(conn, *rows):
    for team, pid, status, game_date, report_time in rows:
        conn.execute(
            "insert into injury_snapshots (captured_at, report_time, game_date, team_id, player_id, player_name_raw, "
            "status_raw, status, source) values (?, ?, ?, ?, ?, ?, ?, ?, 'nba_official_pdf')",
            (report_time, report_time, game_date, team, pid, f"p{pid}", status, status))


class PreviousStatusTests(unittest.TestCase):
    def test_newest_report_per_player_inside_the_window_only(self):
        conn = injuries.connect(":memory:")
        snapshot(conn,
                 (1, 10, "out", "2026-10-18", "2026-10-18T14:00:00+00:00"),
                 (1, 10, "questionable", "2026-10-19", "2026-10-19T14:00:00+00:00"),   # newer for player 10
                 (1, 11, "out", "2026-10-01", "2026-10-01T14:00:00+00:00"),            # outside the 7 days
                 (1, 12, "out", "2026-10-20", "2026-10-20T14:00:00+00:00"),            # today's game: not "previous"
                 (3, 13, "out", "2026-10-19", "2026-10-19T14:00:00+00:00"))            # another team
        df = injuries.previous_status([1, 2], "2026-10-20", 7, conn=conn, backend="local")
        self.assertEqual({int(r.player_id): r.status for r in df.itertuples()}, {10: "questionable"})

    def test_empty_archive_is_an_empty_frame(self):
        conn = injuries.connect(":memory:")
        self.assertTrue(injuries.previous_status([1], "2026-10-20", 7, conn=conn, backend="local").empty)


class ProvisionalPPlayTests(unittest.TestCase):
    def ga(self, status_of, played):
        pg = pd.DataFrame([{"player_id": p, "game_date": d} for p, d in played])
        return SimpleNamespace(home=1, away=2, game_date="2026-10-20", status_of=status_of, pg=pg)

    def prior(self, *rows):
        return pd.DataFrame([{"player_id": p, "status": s, "game_date": d} for p, s, d in rows])

    def run_p(self, ga, prior):
        with patch.object(injuries, "previous_status", return_value=prior):
            return ap.provisional_p_play(ga)

    def test_todays_statuses_become_probabilities_not_certainties(self):
        p = self.run_p(self.ga({1: "out", 2: "questionable", 3: "probable"}, []), self.prior())
        self.assertEqual(p, {1: config.PROVISIONAL_P_PLAY["out"], 2: 0.5, 3: config.PROVISIONAL_P_PLAY["probable"]})
        self.assertGreater(p[1], 0.0)                 # an "out" at 6 AM can still change

    def test_an_earlier_status_carries_forward_for_a_player_missing_today(self):
        p = self.run_p(self.ga({}, [(5, "2026-10-10")]), self.prior((5, "out", "2026-10-19")))
        self.assertEqual(p, {5: config.PROVISIONAL_CARRY_P_PLAY["out"]})

    def test_a_player_who_has_played_since_is_not_carried(self):
        p = self.run_p(self.ga({}, [(5, "2026-10-19")]), self.prior((5, "out", "2026-10-19"), (6, "out", "2026-10-19")))
        self.assertNotIn(5, p)                         # played on/after that report: stale
        self.assertIn(6, p)

    def test_todays_report_wins_over_an_earlier_one(self):
        p = self.run_p(self.ga({5: "probable"}, []), self.prior((5, "out", "2026-10-19")))
        self.assertEqual(p[5], config.PROVISIONAL_P_PLAY["probable"])

    def test_a_missing_archive_falls_back_to_todays_statuses(self):
        with patch.object(injuries, "previous_status", side_effect=RuntimeError("no archive")):
            p = ap.provisional_p_play(self.ga({1: "doubtful"}, []))
        self.assertEqual(p, {1: config.PROVISIONAL_P_PLAY["doubtful"]})


class TentativeSmsTests(unittest.TestCase):
    PICKS = [
        {"home_team": "DET", "away_team": "BOS", "home_win_prob": 0.4, "away_win_prob": 0.6,
         "predicted_winner": "BOS", "odds": 120, "bookmaker": "FanDuel"},
        {"home_team": "NYK", "away_team": "PHI", "home_win_prob": 0.7, "away_win_prob": 0.3,
         "predicted_winner": "NYK", "odds": None, "bookmaker": None},
    ]

    def test_morning_text_lists_temporary_picks_with_a_tentative_disclaimer(self):
        sms = daily_workflow.format_sms([], [], {}, include_today=False, temporary_picks=self.PICKS)
        self.assertIn("TENTATIVE picks", sms)
        self.assertIn("BOS @ DET — BOS (60%) | +120 (FanDuel)", sms)
        self.assertIn("NYK (70%) | no odds yet", sms)
        self.assertIn("tentative", sms)
        self.assertIn("can change", sms)
        self.assertNotIn("Bet:", sms)                  # never a stake in a temporary pick

    def test_morning_text_without_temporary_picks_is_unchanged(self):
        sms = daily_workflow.format_sms([], [], {}, include_today=False, temporary_picks=[])
        self.assertIn("Today's picks follow later", sms)
        self.assertNotIn("TENTATIVE", sms)


if __name__ == "__main__":
    unittest.main()
