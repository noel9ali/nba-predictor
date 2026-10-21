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

    def test_seasons_include_current_season_automatically(self):
        from datetime import date
        self.assertEqual(collect.seasons_to_collect(date(2026, 10, 20))[-1], "2026-27")
        self.assertEqual(collect.seasons_to_collect(date(2027, 10, 20))[-1], "2027-28")
        self.assertEqual(collect.seasons_to_collect(date(2026, 3, 1)), collect.SEASONS)

    def test_empty_current_season_is_a_noop(self):
        from datetime import date
        hist = pd.DataFrame([{"GAME_ID": "0022501186", "TEAM_ID": 7}])

        def fake_fetch(season, retries=3):
            return pd.DataFrame() if season == "2026-27" else hist

        with patch.object(collect, "fetch_season", side_effect=fake_fetch), \
             patch.object(collect, "upsert_rows") as upsert:
            collect.run(today=date(2026, 10, 19))
        rows = upsert.call_args.args[1]
        self.assertEqual(len(rows), len(collect.SEASONS))

        with patch.object(collect, "fetch_season", return_value=pd.DataFrame()), \
             patch.object(collect, "upsert_rows") as upsert:
            collect.run(today=date(2026, 10, 19))
        upsert.assert_not_called()

    def test_failed_season_raises_after_saving_the_rest(self):
        from datetime import date
        hist = pd.DataFrame([{"GAME_ID": "0022501186", "TEAM_ID": 7}])

        def fake_fetch(season, retries=3):
            return None if season == "2026-27" else hist

        with patch.object(collect, "fetch_season", side_effect=fake_fetch), \
             patch.object(collect, "upsert_rows") as upsert:
            with self.assertRaises(RuntimeError) as raised:
                collect.run(today=date(2026, 10, 19))
        self.assertIn("2026-27", str(raised.exception))
        upsert.assert_called_once()

    def test_fetch_season_returns_none_when_all_retries_fail(self):
        with patch.object(collect.leaguegamefinder, "LeagueGameFinder", side_effect=OSError("boom")), \
             patch.object(collect.time, "sleep"):
            self.assertIsNone(collect.fetch_season("2026-27", retries=2))


if __name__ == "__main__":
    unittest.main()
