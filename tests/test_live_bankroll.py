import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import app as dashboard  # noqa: E402  (app.py adds src/ to sys.path itself)
import config  # noqa: E402
import track  # noqa: E402


def _rows(filters, rows):
    out = rows
    for column, op, value in filters:
        if op == "gte":
            out = [r for r in out if r[column] is not None and r[column] >= value]
        elif op == "not_is":
            out = [r for r in out if r[column] is not None]
    return pd.DataFrame(out)


class LiveBankrollTrackTests(unittest.TestCase):
    def test_recompute_starts_the_live_tally_at_the_starting_bankroll(self):
        # A big beta-season win must not leak into the live balance.
        predictions = [
            {"game_date": "2026-04-10", "profit_loss": 500.0},   # beta
            {"game_date": "2026-10-20", "profit_loss": -40.0},   # live
            {"game_date": "2026-10-21", "profit_loss": 25.0},    # live
        ]
        written = []
        with patch.object(track, "select_rows", side_effect=lambda t, **kw: _rows(kw.get("filters", []), predictions)), \
             patch.object(track, "upsert_rows", side_effect=lambda t, rows, **kw: written.extend(rows)):
            track._recompute_bankroll(["2026-04-10", "2026-10-20"])
        self.assertEqual(written, [
            {"date": "2026-10-20", "balance": 960.0},
            {"date": "2026-10-21", "balance": 985.0},
        ])

    def test_current_bankroll_reads_only_live_rows(self):
        seen = {}

        def fake_select(table, **kw):
            seen.update(kw)
            return pd.DataFrame([{"balance": 1000.0}])

        with patch.object(track, "select_rows", side_effect=fake_select):
            self.assertEqual(track.get_current_bankroll(), 1000.0)
        self.assertIn(("date", "gte", config.LIVE_START_DATE), seen["filters"])

    def test_setup_seeds_the_live_row_when_only_beta_rows_exist(self):
        upserts = []
        with patch.object(track, "select_rows", return_value=pd.DataFrame()), \
             patch.object(track, "upsert_rows", side_effect=lambda t, rows, **kw: upserts.append((t, rows))):
            track.setup_tables()
        self.assertEqual(upserts, [("bankroll", [{"date": config.LIVE_START_DATE, "balance": track.STARTING_BANKROLL}])])


class LiveSeasonAppTests(unittest.TestCase):
    def test_beta_seasons_are_those_before_the_live_launch(self):
        self.assertTrue(dashboard.is_beta_season("2025-26"))
        self.assertFalse(dashboard.is_beta_season("2026-27"))
        self.assertFalse(dashboard.is_beta_season("2027-28"))

    def test_all_means_live_only(self):
        self.assertEqual(
            dashboard.season_or_all_filters("game_date", "all"),
            [("game_date", "gte", config.LIVE_START_DATE)],
        )
        self.assertEqual(config.LIVE_START_DATE, dashboard.season_bounds(config.LIVE_FIRST_SEASON)[0])

    def test_live_start_date_is_the_first_day_of_the_first_live_season(self):
        self.assertEqual(config.LIVE_START_DATE, f"{config.LIVE_FIRST_SEASON[:4]}-09-01")


if __name__ == "__main__":
    unittest.main()
