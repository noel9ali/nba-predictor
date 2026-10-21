"""Phase 6: factor contributions reconcile with the stored probability."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import factors  # noqa: E402


class FactorTests(unittest.TestCase):
    def test_contributions_plus_base_equal_probability(self):
        feats = ["ELO_DIFF", "HOME_roll_PTS", "rest_diff", "rapm:value_out_diff", "rapm:home_star_out"]
        coef = np.array([0.8, 0.1, 0.05, -0.3, -0.2])
        z = np.array([1.2, -0.5, 0.3, 1.5, 1.0])
        prob = 0.613
        rows = factors.contributions(coef, z, feats, prob, 0.55)
        total = 55.0 + sum(r["prob_points"] for r in rows)
        self.assertAlmostEqual(total, 61.3, places=6)
        self.assertEqual(rows[-1]["factor_key"], "other")
        self.assertEqual({r["group"] for r in rows}, {"base", "form", "rest", "availability"})
        self.assertEqual([r["sort_order"] for r in rows], list(range(len(rows))))
        elo = next(r for r in rows if r["factor_key"] == "ELO_DIFF")
        self.assertAlmostEqual(elo["prob_points"], round(0.8 * 1.2 * prob * (1 - prob) * 100, 2))

    def test_availability_split_labels_players(self):
        feats = ["ELO_DIFF", "rapm:value_out_diff"]
        rows = factors.contributions(np.array([0.5, -0.4]), np.array([0.0, 2.0]), feats, 0.45, 0.55,
                                     availability_split=[("Jokić out", 3.0), ("Murray questionable", 1.0)])
        avail = [r for r in rows if r["group"] == "availability"]
        self.assertEqual(len(avail), 2)
        self.assertTrue(avail[0]["label"].startswith("Jokić out: -"))
        self.assertAlmostEqual(avail[0]["prob_points"] / avail[1]["prob_points"], 3.0, places=1)
        self.assertAlmostEqual(55.0 + sum(r["prob_points"] for r in rows), 45.0, places=6)

    def test_coefficients_from_calibrated_logistic(self):
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        rng = np.random.default_rng(0)
        X = rng.normal(size=(400, 2))
        y = (X[:, 0] + rng.normal(scale=0.5, size=400) > 0).astype(int)
        model = CalibratedClassifierCV(LogisticRegression(), cv=3, method="isotonic").fit(X, y)
        coef = factors.linear_coefficients(model)
        self.assertEqual(coef.shape, (2,))
        self.assertGreater(coef[0], abs(coef[1]))
        scaler = StandardScaler().fit(X)
        prob = float(model.predict_proba(X[:1])[0, 1])
        rows = factors.explain(model, scaler, X[0], ["ELO_DIFF", "HOME_ELO"], prob, 0.55)
        self.assertAlmostEqual(55.0 + sum(r["prob_points"] for r in rows), prob * 100, delta=0.006)  # within rounding


if __name__ == "__main__":
    unittest.main()
