"""Phase 6: market-agnostic betting module."""

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import betting  # noqa: E402
import track  # noqa: E402


class BettingTests(unittest.TestCase):
    def test_worked_example(self):
        # bankroll 1,111.67, probability 0.61, price -105: quarter Kelly 55.72 is capped at 5% = 55.58
        self.assertAlmostEqual(betting.stake(1111.67, 0.61, -105), 55.5835, places=4)
        self.assertAlmostEqual(track.kelly_bet(0.61, -105, 1111.67), 55.5835, places=4)

    def test_implied_prob_edge_and_kelly(self):
        self.assertAlmostEqual(betting.implied_prob(-105), 105 / 205)
        self.assertAlmostEqual(betting.implied_prob(150), 0.4)
        self.assertAlmostEqual(betting.edge(0.5, 150), 0.1)
        self.assertAlmostEqual(betting.american_to_decimal(150), 2.5)
        self.assertAlmostEqual(betting.kelly_fraction(0.5, 150), (0.5 * 2.5 - 1) / 1.5)
        self.assertEqual(betting.kelly_fraction(0.3, 150), 0.0)

    def test_no_bet_without_edge_or_beyond_max_odds(self):
        self.assertEqual(betting.stake(1000, 0.5, -200), 0.0)
        self.assertEqual(betting.stake(1000, 0.3, 450), 0.0)          # decimal 5.5 > 5.0
        self.assertEqual(track.kelly_bet(0.3, 450, 1000), 0)

    def test_uncapped_quarter_kelly_and_exposure_hook(self):
        amount = betting.stake(1000, 0.55, 100)
        self.assertAlmostEqual(amount, 0.1 * 0.25 * 1000)              # full Kelly 0.10
        self.assertAlmostEqual(betting.stake(1000, 0.55, 100, exposure_left=10), 10.0)
        self.assertEqual(betting.stake(1000, 0.55, 100, exposure_left=-5), 0.0)
        self.assertAlmostEqual(betting.stake(1000, 0.55, 100, fraction=0.125), 12.5)

    def test_no_game_specific_names(self):
        for name, fn in inspect.getmembers(betting, inspect.isfunction):
            self.assertNotIn("game", name)
            for param in inspect.signature(fn).parameters:
                self.assertNotIn("game", param)
                self.assertNotIn("home", param)


if __name__ == "__main__":
    unittest.main()
