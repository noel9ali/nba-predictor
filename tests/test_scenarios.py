"""Phase 6: scenario blending, uncertainty gate, status-change flag."""

import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import scenarios  # noqa: E402


def roster(rows):
    return pd.DataFrame(rows, columns=["player_id", "p_play", "rating", "min_if_play"])


class ScenarioTests(unittest.TestCase):
    def test_weights_sum_to_one_and_cap_players(self):
        r = roster([(1, 0.5, 6, 34), (2, 0.3, 2, 30), (3, 0.8, 1, 20), (4, 0.6, 0.5, 10), (5, 1.0, 9, 36),
                    (6, 0.05, 5, 30)])
        unc = scenarios.uncertain_players(r)
        self.assertEqual(list(unc["player_id"]), [1, 2, 3])          # top 3 by impact, p in (0.1, 0.9)
        scen = scenarios.enumerate_scenarios(unc)
        self.assertEqual(len(scen), 8)
        self.assertAlmostEqual(sum(s.weight for s in scen), 1.0)
        all_in = next(s for s in scen if s.key == "1=1|2=1|3=1")
        self.assertAlmostEqual(all_in.weight, 0.5 * 0.3 * 0.8)

    def test_no_uncertain_players_gives_one_base_scenario(self):
        scen = scenarios.enumerate_scenarios(scenarios.uncertain_players(roster([(1, 1.0, 3, 30)])))
        self.assertEqual([(s.key, s.weight) for s in scen], [("base", 1.0)])

    def test_half_probability_player_blends_between_scenarios(self):
        unc = scenarios.uncertain_players(roster([(7, 0.5, 8, 35)]))
        scen = scenarios.enumerate_scenarios(unc, names={7: "Star"})
        score = lambda o: 0.62 if o.get(7) == 1.0 else 0.50  # noqa: E731
        blended, low, high, scored = scenarios.blend(scen, score)
        self.assertAlmostEqual(blended, 0.56)
        self.assertTrue(low < blended < high)
        self.assertEqual((low, high), (0.50, 0.62))
        self.assertEqual({s.label for s in scored}, {"Star plays", "Star out"})

    def test_gate(self):
        self.assertEqual(scenarios.apply_gate(40.0, 0.50, 0.62, gate=False), (40.0, None))
        self.assertEqual(scenarios.apply_gate(40.0, 0.50, 0.62, gate=True, action="halve"), (20.0, None))
        self.assertEqual(scenarios.apply_gate(40.0, 0.50, 0.62, gate=True, action="skip"),
                         (0.0, "availability_uncertain"))
        self.assertEqual(scenarios.apply_gate(40.0, 0.50, 0.55, gate=True, action="skip"), (40.0, None))
        self.assertEqual(scenarios.apply_gate(0.0, 0.40, 0.70, gate=True, action="skip"), (0.0, None))
        with self.assertRaises(ValueError):
            scenarios.apply_gate(40.0, 0.4, 0.7, gate=True, action="double")

    def test_status_changed(self):
        before = {1: "questionable", 2: "out"}
        self.assertFalse(scenarios.status_changed(before, dict(before), [1, 2, 3]))
        self.assertTrue(scenarios.status_changed(before, {1: "out", 2: "out"}, [1, 2]))
        self.assertTrue(scenarios.status_changed(before, {2: "out"}, [1]))          # removed from report
        self.assertFalse(scenarios.status_changed(before, {1: "questionable", 2: "out", 9: "out"}, [1, 2]))


if __name__ == "__main__":
    unittest.main()
