import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import database
import collect


class FakeGameFinder:
    def __init__(self, df):
        self._df = df

    def get_data_frames(self):
        return [self._df]


class CollectTests(unittest.TestCase):
    def test_save_to_db_upserts_on_composite_key_with_normalized_ids(self):
        df = pd.DataFrame(
            [
                {"GAME_ID": 22501186, "TEAM_ID": 7, "SEASON": "2025-26"},
                {"GAME_ID": "22501186", "TEAM_ID": 8, "SEASON": "2025-26"},
            ]
        )
        captured = {}

        def fake_upsert_rows(table, rows, *, conflict_columns):
            captured["table"] = table
            captured["rows"] = rows
            captured["conflict_columns"] = conflict_columns
            return rows

        with patch.object(collect, "upsert_rows", side_effect=fake_upsert_rows):
            collect.save_to_db(df)

        self.assertEqual(captured["table"], "games")
        self.assertEqual(captured["conflict_columns"], ["GAME_ID", "TEAM_ID"])
        self.assertEqual(collect.GAMES_CONFLICT_COLUMNS, ["GAME_ID", "TEAM_ID"])
        ids = [row["GAME_ID"] for row in captured["rows"]]
        self.assertEqual(ids, ["0022501186", "0022501186"])
        self.assertTrue(all(len(game_id) == 10 for game_id in ids))

    def test_run_surfaces_composite_pk_hint_on_conflict_target_error(self):
        df = pd.DataFrame([{"GAME_ID": "0022501186", "TEAM_ID": 7, "SEASON": "2025-26"}])

        with patch.object(collect, "fetch_season", return_value=df), \
             patch.object(
                 collect,
                 "upsert_rows",
                 side_effect=database.DatabaseError(
                     "Upserting rows into games failed: configured upsert conflict "
                     "target is not backed by a database unique constraint"
                 ),
             ):
            with self.assertRaises(database.DatabaseError) as raised:
                collect.run()

        self.assertIn("20260923000200_games_composite_pk.sql", str(raised.exception))

    def test_fetch_season_never_touches_the_network(self):
        df = pd.DataFrame([{"GAME_ID": "0022501186", "TEAM_ID": 7}])
        with patch.object(
            collect.leaguegamefinder, "LeagueGameFinder", return_value=FakeGameFinder(df)
        ) as fake_finder:
            result = collect.fetch_season("2025-26")

        fake_finder.assert_called_once()
        self.assertEqual(result["SEASON"].iloc[0], "2025-26")


if __name__ == "__main__":
    unittest.main()
