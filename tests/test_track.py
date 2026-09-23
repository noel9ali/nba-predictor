import contextlib
import io
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import database
import track


class FakeScoreboard:
    def __init__(self, teams_df):
        self._teams_df = teams_df

    def get_data_frames(self):
        # ScoreboardV3.get_data_frames() returns several frames; teams is index 2.
        return [None, None, self._teams_df]


class TrackTests(unittest.TestCase):
    def test_missing_bankroll_raises_actionable_database_error(self):
        with patch.object(
            track,
            "select_rows",
            side_effect=database.MissingTableError("bankroll missing"),
        ):
            with self.assertRaises(database.DatabaseError) as raised:
                track.get_current_bankroll()
        self.assertIn("20260923000400", str(raised.exception))

        with patch.object(
            track,
            "select_rows",
            side_effect=database.MissingTableError("bankroll missing"),
        ):
            with self.assertRaises(database.DatabaseError) as raised:
                track.setup_tables()
        self.assertIn("20260923000400", str(raised.exception))

    def test_update_results_settles_loss_and_win_with_text_odds(self):
        pending = pd.DataFrame(
            [
                {
                    "game_id": "0022501195",
                    "game_date": "2026-04-12",
                    "home_team": "MIN",
                    "away_team": "NOP",
                    "predicted_winner": "NOP",
                    "bet_placed": "NOP",
                    "bet_amount": 21.04,
                    "odds": "188",
                },
                {
                    "game_id": "0022501196",
                    "game_date": "2026-04-12",
                    "home_team": "PHX",
                    "away_team": "OKC",
                    "predicted_winner": "PHX",
                    "bet_placed": "PHX",
                    "bet_amount": 40.0,
                    "odds": "-150",
                },
            ]
        )
        teams = pd.DataFrame(
            [
                {"gameId": "0022501195", "teamTricode": "MIN", "score": "110"},
                {"gameId": "0022501195", "teamTricode": "NOP", "score": "100"},
                {"gameId": "0022501196", "teamTricode": "PHX", "score": "112"},
                {"gameId": "0022501196", "teamTricode": "OKC", "score": "104"},
            ]
        )

        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            return []

        with patch.object(track, "select_rows", side_effect=self._select_rows_router(pending)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]), \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(len(updates), 2)
        loss_update = next(v for v, f in updates if ("game_id", "eq", "0022501195") in f)
        win_update = next(v for v, f in updates if ("game_id", "eq", "0022501196") in f)
        self.assertEqual(loss_update["profit_loss"], -21.04)
        self.assertAlmostEqual(win_update["profit_loss"], 40.0 * 100 / 150)

    def test_int_game_id_matches_zero_padded_scoreboard_id(self):
        pending = pd.DataFrame(
            [
                {
                    "game_id": 22501195,
                    "game_date": "2026-04-12",
                    "home_team": "MIN",
                    "away_team": "NOP",
                    "predicted_winner": "NOP",
                    "bet_placed": None,
                    "bet_amount": 0.0,
                    "odds": "188",
                }
            ]
        )
        teams = pd.DataFrame(
            [
                {"gameId": "0022501195", "teamTricode": "MIN", "score": "110"},
                {"gameId": "0022501195", "teamTricode": "NOP", "score": "100"},
            ]
        )
        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            return []

        with patch.object(track, "select_rows", side_effect=self._select_rows_router(pending)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]), \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(len(updates), 1)
        self.assertIn(("game_id", "eq", "0022501195"), updates[0][1])

    def test_max_decimal_odds_cutoff(self):
        self.assertEqual(track.kelly_bet(0.3, 450, 1000), 0)
        self.assertAlmostEqual(track.kelly_bet(0.61, -105, 1111.67), 55.5835)

    @staticmethod
    def _select_rows_router(pending):
        def router(table, **kwargs):
            if table == "predictions":
                filters = kwargs.get("filters", ())
                if any(f[0] == "profit_loss" for f in filters):
                    return pd.DataFrame(columns=["profit_loss"])
                return pending
            raise AssertionError(f"Unexpected table read: {table}")

        return router


if __name__ == "__main__":
    unittest.main()
