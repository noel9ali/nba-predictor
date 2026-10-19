import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import elo  # noqa: E402


def fake_select(elo_rows, games_rows):
    def _select(table, **kwargs):
        if table == "elo":  # real query is ordered newest first
            return pd.DataFrame(sorted(elo_rows, key=lambda r: r["GAME_DATE"], reverse=True))
        return pd.DataFrame(games_rows)
    return _select


# One 2025-26 game: team 1 (home, 1600) beats team 2 (1500).
ELO_ROWS = [{"GAME_ID": "G1", "GAME_DATE": "2026-04-12", "HOME_TEAM_ID": 1, "AWAY_TEAM_ID": 2,
             "HOME_ELO": 1600.0, "AWAY_ELO": 1500.0}]
GAMES_ROWS = [{"GAME_ID": "G1", "TEAM_ID": 1, "MATCHUP": "AAA vs. BBB", "WL": "W"},
              {"GAME_ID": "G1", "TEAM_ID": 2, "MATCHUP": "BBB @ AAA", "WL": "L"}]


class CurrentRatingsSeasonTests(unittest.TestCase):
    def ratings(self, today, elo_rows=ELO_ROWS):
        with patch.object(elo, "select_rows", fake_select(elo_rows, GAMES_ROWS)):
            return elo.get_current_ratings(today=today)

    def test_reverted_on_new_season_date(self):
        post = elo.update_elo(1600.0, 1500.0, True)
        got = self.ratings(date(2026, 10, 20))
        self.assertAlmostEqual(got[1], post[0] * 0.75 + 1500 * 0.25)
        self.assertAlmostEqual(got[2], post[1] * 0.75 + 1500 * 0.25)

    def test_not_reverted_mid_season(self):
        post = elo.update_elo(1600.0, 1500.0, True)
        got = self.ratings(date(2026, 4, 20))
        self.assertAlmostEqual(got[1], post[0])
        self.assertAlmostEqual(got[2], post[1])

    def test_not_reverted_twice_after_team_has_new_season_game(self):
        # Teams 1 and 3 already played a 2026-27 game (elo rebuilt, so the stored pre-game
        # rating is already reverted); team 2 has not and still needs exactly one reversion.
        rows = ELO_ROWS + [{"GAME_ID": "G2", "GAME_DATE": "2026-10-20", "HOME_TEAM_ID": 1, "AWAY_TEAM_ID": 3,
                            "HOME_ELO": 1575.0, "AWAY_ELO": 1500.0}]
        games = GAMES_ROWS + [{"GAME_ID": "G2", "TEAM_ID": 1, "MATCHUP": "AAA vs. CCC", "WL": "W"},
                              {"GAME_ID": "G2", "TEAM_ID": 3, "MATCHUP": "CCC @ AAA", "WL": "L"}]
        with patch.object(elo, "select_rows", fake_select(rows, games)):
            got = elo.get_current_ratings(today=date(2026, 10, 21))
        post1, post3 = elo.update_elo(1575.0, 1500.0, True)
        self.assertAlmostEqual(got[1], post1)
        self.assertAlmostEqual(got[3], post3)
        post2 = elo.update_elo(1600.0, 1500.0, True)[1]
        self.assertAlmostEqual(got[2], post2 * 0.75 + 1500 * 0.25)

    def test_empty_elo_table(self):
        self.assertEqual(self.ratings(date(2026, 10, 20), elo_rows=[]), {})

    def test_revert_stale_ratings_is_pure(self):
        ratings = {1: 1700.0}
        out = elo.revert_stale_ratings(ratings, {1: "2026-04-12"}, date(2026, 10, 20))
        self.assertEqual(ratings, {1: 1700.0})
        self.assertAlmostEqual(out[1], 1650.0)


class TodaysGamesTests(unittest.TestCase):
    @staticmethod
    def board(games, teams):
        class B:
            def get_data_frames(self):
                return [pd.DataFrame(), games, teams]
        return B()

    def test_home_away_order_and_empty_slate(self):
        import predict
        # ScoreboardV3 lists the away team first and the home team second for each game.
        teams = pd.DataFrame([
            {"gameId": "G1", "teamId": 10, "teamTricode": "AWY"},
            {"gameId": "G1", "teamId": 20, "teamTricode": "HOM"},
        ])
        games = pd.DataFrame([{"gameId": "G1"}])
        with patch.object(predict.scoreboardv3, "ScoreboardV3", return_value=self.board(games, teams)):
            out = predict.get_todays_games()
        self.assertEqual(out.iloc[0]["HOME_TEAM_ID"], 20)
        self.assertEqual(out.iloc[0]["VISITOR_TEAM_ID"], 10)
        empty_games = pd.DataFrame(columns=["gameId"])
        empty_teams = pd.DataFrame(columns=["gameId", "teamId", "teamTricode"])
        with patch.object(predict.scoreboardv3, "ScoreboardV3",
                          return_value=self.board(empty_games, empty_teams)):
            self.assertEqual(len(predict.get_todays_games()), 0)


if __name__ == "__main__":
    unittest.main()
