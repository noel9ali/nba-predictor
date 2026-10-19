"""Regression: predict.get_todays_games() must take home/away from the scoreboard's homeTeam/awayTeam.

ScoreboardV3's LineScore frame lists the HOME team first; the old groupby().first()=away / .last()=home logic
therefore swapped every game, so the model, the odds lookup and the edge all described the wrong venue
(e.g. BKN at TOR +4000 priced as if BKN were the home side). Fully offline.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import predict  # noqa: E402


def board_dict():
    """Shape of ScoreboardV3.get_dict() for 2026-04-12: BOS hosts ORL, CLE hosts WAS (home listed first)."""
    def game(gid, home, away):
        return {"gameId": gid,
                "homeTeam": {"teamId": home[0], "teamTricode": home[1]},
                "awayTeam": {"teamId": away[0], "teamTricode": away[1]}}
    return {"scoreboard": {"games": [
        game("0022501186", (1610612738, "BOS"), (1610612753, "ORL")),
        game("0022501187", (1610612739, "CLE"), (1610612764, "WAS")),
    ]}}


class FakeBoard:
    def get_dict(self):
        return board_dict()

    def get_data_frames(self):
        raise AssertionError("positional LineScore frames must not be used to decide home/away")


class HomeAwayTests(unittest.TestCase):
    def test_home_and_away_come_from_explicit_fields(self):
        with patch.object(predict.scoreboardv3, "ScoreboardV3", return_value=FakeBoard()):
            games = predict.get_todays_games().set_index("gameId")
        row = games.loc["0022501186"]
        self.assertEqual((row["HOME_TEAM_ABBREVIATION"], row["VISITOR_TEAM_ABBREVIATION"]), ("BOS", "ORL"))
        self.assertEqual((row["HOME_TEAM_ID"], row["VISITOR_TEAM_ID"]), (1610612738, 1610612753))
        row = games.loc["0022501187"]
        self.assertEqual((row["HOME_TEAM_ABBREVIATION"], row["VISITOR_TEAM_ABBREVIATION"]), ("CLE", "WAS"))

    def test_odds_follow_the_real_home_team(self):
        odds = {("Boston Celtics", "Orlando Magic"): {
            "home_odds": -3000, "away_odds": 1500, "home_book": "DraftKings", "away_book": "FanDuel"}}
        with patch.object(predict.scoreboardv3, "ScoreboardV3", return_value=FakeBoard()):
            game = predict.get_todays_games().iloc[0]
        matched = predict.match_odds(game["HOME_TEAM_ABBREVIATION"], game["VISITOR_TEAM_ABBREVIATION"], odds)
        self.assertEqual(matched["home_odds"], -3000)
        self.assertEqual(matched["away_odds"], 1500)

    def test_empty_or_incomplete_scoreboard(self):
        self.assertEqual(len(predict.games_from_scoreboard({})), 0)
        self.assertEqual(len(predict.games_from_scoreboard({"scoreboard": {"games": [{"gameId": "x"}]}})), 0)


if __name__ == "__main__":
    unittest.main()
