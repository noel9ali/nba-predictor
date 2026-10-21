"""Offline checks for the reusable props groundwork."""

import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import market_odds  # noqa: E402
import player_rates  # noqa: E402


class PlayerRatesTests(unittest.TestCase):
    def test_rates_exclude_games_on_or_after_as_of(self):
        games = pd.DataFrame([
            {"player_id": 1, "game_date": "2026-01-01", "minutes": 20, "pts": 10,
             "reb": 2, "ast": 2, "fg3m": 1, "stl": 1, "blk": 0, "tov": 1},
            {"player_id": 1, "game_date": "2026-01-10", "minutes": 20, "pts": 100,
             "reb": 2, "ast": 2, "fg3m": 1, "stl": 1, "blk": 0, "tov": 1},
        ])
        before = player_rates.compute(games, "2026-01-10")
        after = player_rates.compute(games, "2026-01-11")
        self.assertEqual(before.loc[before["stat"] == "pts", "minutes_basis"].iloc[0], 20)
        self.assertEqual(after.loc[after["stat"] == "pts", "minutes_basis"].iloc[0], 40)
        self.assertLess(before.loc[before["stat"] == "pts", "rate_per_min"].iloc[0],
                        after.loc[after["stat"] == "pts", "rate_per_min"].iloc[0])

    def test_empty_input_preserves_rate_schema(self):
        result = player_rates.compute(pd.DataFrame(), "2026-01-10")
        self.assertEqual(list(result.columns), [
            "player_id", "as_of", "stat", "rate_per_min", "minutes_basis", "version"])


class MarketOddsTests(unittest.TestCase):
    def test_moneyline_rows_are_normalized_and_deterministic(self):
        games = [{
            "id": "game-1", "home_odds": -105, "away_odds": 100,
            "home_book": "Book A", "away_book": "Book B",
        }]
        rows = market_odds.moneyline_rows(games, captured_at="2026-01-01T00:00:00+00:00")
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["selection"] for row in rows}, {"home", "away"})
        self.assertEqual(rows, market_odds.moneyline_rows(
            games, captured_at="2026-01-01T00:00:00+00:00"))

