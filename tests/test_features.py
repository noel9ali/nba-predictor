import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import features


class RestDaysTests(unittest.TestCase):
    def test_rest_days_span_home_and_away_appearances(self):
        # Team 1 plays: away on Jan 1 (vs team 2), home on Jan 4 (vs team 3),
        # away on Jan 6 (vs team 4). True rest before the Jan 4 home game is
        # 3 days (Jan1 -> Jan4); true rest before the Jan 6 away game is
        # 2 days (Jan4 -> Jan6) -- both spanning a role change for team 1.
        df = pd.DataFrame(
            [
                {"GAME_ID": "G1", "GAME_DATE": "2026-01-01", "HOME_TEAM_ID": 2, "AWAY_TEAM_ID": 1},
                {"GAME_ID": "G2", "GAME_DATE": "2026-01-04", "HOME_TEAM_ID": 1, "AWAY_TEAM_ID": 3},
                {"GAME_ID": "G3", "GAME_DATE": "2026-01-06", "HOME_TEAM_ID": 4, "AWAY_TEAM_ID": 1},
            ]
        )

        result = features.add_rest_days(df)

        g2 = result[result["GAME_ID"] == "G2"].iloc[0]
        g3 = result[result["GAME_ID"] == "G3"].iloc[0]

        self.assertEqual(g2["HOME_rest_days"], 3.0)
        self.assertEqual(g3["AWAY_rest_days"], 2.0)
        # team 3's only prior appearance is its own first game (G2, as AWAY),
        # so its rest before G2 is undefined (NaN) -- not a role-crossing bug.
        self.assertTrue(pd.isna(g2["AWAY_rest_days"]))

    def test_duplicate_game_rows_do_not_multiply_output_rows(self):
        # A duplicated game row (e.g. an upstream dedup bug) must never
        # multiply rows through the merge -- output row count must always
        # equal input row count.
        df = pd.DataFrame(
            [
                {"GAME_ID": "G1", "GAME_DATE": "2026-01-01", "HOME_TEAM_ID": 2, "AWAY_TEAM_ID": 1},
                {"GAME_ID": "G2", "GAME_DATE": "2026-01-04", "HOME_TEAM_ID": 1, "AWAY_TEAM_ID": 3},
                {"GAME_ID": "G2", "GAME_DATE": "2026-01-04", "HOME_TEAM_ID": 1, "AWAY_TEAM_ID": 3},
            ]
        )

        result = features.add_rest_days(df)

        self.assertEqual(len(result), len(df))


if __name__ == "__main__":
    unittest.main()
