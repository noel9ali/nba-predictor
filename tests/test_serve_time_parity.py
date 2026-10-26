"""Serve-time features must be the features the model trained on (diagnostic 2026-10-25).

Regressions covered: rest days looked only at the team's last game in the SAME role (a team with no home game yet
this season got ~190 rest days, which pushed a logistic model to 92% 'edges'); rolling form skipped the newest game;
in-progress games (WL null) were read as home losses; neutral-site games ('@' in both rows) were dropped; odds from a
rematch or an in-play price could stand in for tonight's line. Fully offline.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import betting  # noqa: E402
import features  # noqa: E402
import odds  # noqa: E402
import predict  # noqa: E402


def row(game_id, date, team_id, matchup, wl="W", pts=100.0):
    return {"GAME_ID": game_id, "GAME_DATE": date, "TEAM_ID": team_id, "MATCHUP": matchup, "WL": wl, "PTS": pts,
            "FG_PCT": 0.45, "REB": 40.0, "AST": 25.0, "TOV": 12.0, "STL": 7.0, "BLK": 5.0}


class RestDaysTests(unittest.TestCase):
    def test_rest_uses_the_last_game_in_either_role(self):
        # last home game was last April; the team played AWAY yesterday
        team = pd.DataFrame([row("g1", "2026-04-10", 1, "AAA vs. BBB"), row("g2", "2026-10-24", 1, "AAA @ CCC")])
        self.assertEqual(features.rest_days_before(team, "2026-10-25"), 1)

    def test_rest_is_capped_and_none_without_a_prior_game(self):
        team = pd.DataFrame([row("g1", "2026-04-10", 1, "AAA vs. BBB")])
        self.assertEqual(features.rest_days_before(team, "2026-10-25"), features.REST_CAP)
        self.assertIsNone(features.rest_days_before(team, "2026-04-10"))      # nothing strictly before
        self.assertEqual(predict.get_rest_days(team.iloc[0:0], today="2026-10-25"), features.REST_CAP)

    def test_in_progress_game_does_not_count_as_the_previous_game(self):
        team = pd.DataFrame([row("g1", "2026-10-20", 1, "AAA vs. BBB"), row("g2", "2026-10-24", 1, "AAA @ CCC", wl=None)])
        self.assertEqual(features.rest_days_before(team, "2026-10-25"), 5)

    def test_training_rest_uses_the_same_cap(self):
        games = pd.DataFrame([
            {"GAME_ID": "g1", "GAME_DATE": "2026-04-01", "HOME_TEAM_ID": 1, "AWAY_TEAM_ID": 2},
            {"GAME_ID": "g2", "GAME_DATE": "2026-10-20", "HOME_TEAM_ID": 1, "AWAY_TEAM_ID": 2},
        ])
        out = features.add_rest_days(games).set_index("GAME_ID")
        self.assertEqual(out.loc["g2", "HOME_rest_days"], features.REST_CAP)
        self.assertEqual(out.loc["g2", "rest_diff"], 0)


class RollingFormTests(unittest.TestCase):
    def games(self, n=12):
        rows = [row(f"h{i}", f"2026-01-{i + 1:02d}", 1, "AAA vs. BBB", pts=100.0 + i) for i in range(n)]
        rows.append(row("a0", "2026-01-30", 1, "AAA @ CCC", pts=999.0))          # an away game: not in HOME form
        return pd.DataFrame(rows)

    def test_form_is_the_last_ten_games_in_the_role_including_the_newest(self):
        form = features.role_form(self.games(), "HOME")
        self.assertAlmostEqual(form["HOME_roll_PTS"], sum(100.0 + i for i in range(2, 12)) / 10)
        self.assertAlmostEqual(form["HOME_roll_STOCKS"], 12.0)

    def test_form_matches_the_training_definition(self):
        # training: the value for the NEXT game is the mean of the last 10 home games, with that game excluded
        # by shift(1); serving the next game must therefore equal the mean over the 10 latest games
        df = self.games()
        home = df[df["MATCHUP"].str.contains("vs.", regex=False)].sort_values("GAME_DATE")
        trained = home["PTS"].shift(0).rolling(10).mean().iloc[-1]
        self.assertAlmostEqual(features.role_form(df, "HOME")["HOME_roll_PTS"], trained)

    def test_form_is_none_until_the_window_is_full(self):
        self.assertIsNone(features.role_form(self.games(n=5), "HOME"))

    def test_in_progress_game_is_left_out_of_the_form(self):
        df = self.games()
        df.loc[df["GAME_ID"] == "h11", "WL"] = None
        self.assertAlmostEqual(features.role_form(df, "HOME")["HOME_roll_PTS"], sum(100.0 + i for i in range(1, 11)) / 10)


class HomeAwayLabelTests(unittest.TestCase):
    def test_neutral_site_game_gets_exactly_one_home_row(self):
        df = pd.DataFrame([
            row("n1", "2026-01-01", 5, "AAA @ BBB"), row("n1", "2026-01-01", 9, "BBB @ AAA"),     # neutral site
            row("r1", "2026-01-02", 5, "AAA vs. CCC"), row("r1", "2026-01-02", 7, "CCC @ AAA"),
        ])
        flags = features.home_flags(df).tolist()
        self.assertEqual(flags, [1, 0, 1, 0])

    def test_unfinished_games_are_filtered(self):
        df = pd.DataFrame([row("a", "2026-01-01", 1, "AAA vs. BBB"), row("b", "2026-01-01", 1, "AAA vs. BBB", wl=None)])
        self.assertEqual(list(features.completed_games(df)["GAME_ID"]), ["a"])


def event(eid, home, away, commence, price=-110):
    return {"id": eid, "commence_time": commence, "home_team": home, "away_team": away,
            "bookmakers": [{"title": "DraftKings", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": price}, {"name": away, "price": 100}]}]}]}


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class OddsMatchingTests(unittest.TestCase):
    def fetch(self, events):
        with patch.object(odds.requests, "get", return_value=FakeResponse(events)), \
             patch.object(odds, "_archive"), patch("market_odds.write_moneyline_rows"):
            return odds.get_tonights_odds()

    def test_started_game_is_not_a_pregame_line(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(self.fetch([event("e1", "Atlanta Hawks", "Boston Celtics", past)]), {})

    def test_the_next_game_of_a_repeated_pair_wins(self):
        soon = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        later = (datetime.now(timezone.utc) + timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
        got = self.fetch([event("e1", "Atlanta Hawks", "Boston Celtics", soon, price=-150),
                          event("e2", "Atlanta Hawks", "Boston Celtics", later, price=-300)])
        self.assertEqual(got[("Atlanta Hawks", "Boston Celtics")]["home_odds"], -150)

    def test_a_reversed_pair_is_never_used(self):
        reversed_game = {("Boston Celtics", "Atlanta Hawks"): {"home_odds": -200, "away_odds": 170,
                                                               "home_book": "x", "away_book": "y"}}
        self.assertIsNone(predict.match_odds("ATL", "BOS", reversed_game))


class StakePolicyTests(unittest.TestCase):
    def test_exposure_left_limits_the_stake(self):
        self.assertAlmostEqual(betting.stake(1000, 0.7, -110, exposure_left=12.0), 12.0)
        self.assertEqual(betting.stake(1000, 0.7, -110, exposure_left=0.0), 0.0)

    def test_policy_constants(self):
        import config
        self.assertEqual(config.MIN_EDGE, 0.03)
        self.assertEqual(config.NIGHTLY_STAKE_CAP, 0.15)


if __name__ == "__main__":
    unittest.main()
