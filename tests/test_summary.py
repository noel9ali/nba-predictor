import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import summary


class SummaryTests(unittest.TestCase):
    def test_summarize_database_reads_games_via_select_rows(self):
        fake_df = pd.DataFrame(
            [
                {"GAME_ID": "0022500001", "GAME_DATE": "2026-01-01", "PTS": 100},
                {"GAME_ID": "0022500002", "GAME_DATE": "2026-01-01", "PTS": 110},
            ]
        )
        with patch.object(summary, "select_rows", return_value=fake_df) as fake_select:
            result = summary.summarize_database("2026-01-01")

        self.assertEqual(fake_select.call_args.args[0], "games")
        self.assertEqual(
            fake_select.call_args.kwargs["filters"],
            [("GAME_DATE", "eq", "2026-01-01")],
        )
        self.assertAlmostEqual(result.loc["mean", "PTS"], 105.0)


if __name__ == "__main__":
    unittest.main()
