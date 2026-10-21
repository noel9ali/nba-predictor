"""Phase 3: ratings and minutes projections (offline, synthetic data)."""

import os
import sys
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
import minutes  # noqa: E402
import ratings  # noqa: E402


def synthetic_player_games(n_games=1500, n_players=30, seed=7, start=date(2024, 10, 22), effects=None):
    """Two teams of 5 drawn at random each game; each player plays 48 minutes; home margin per 100 =
    sum(home effects) - sum(away effects) + 2 + noise. Box stats are constant so only margins matter."""
    rng = np.random.default_rng(seed)
    effects = effects if effects is not None else rng.normal(0, 4, n_players)
    rows = []
    for g in range(n_games):
        players = rng.choice(n_players, 10, replace=False)
        home, away = players[:5], players[5:]
        margin = effects[home].sum() - effects[away].sum() + 2.0 + rng.normal(0, 3)
        gid = f"00224{g:05d}"
        gdate = (start + timedelta(days=g // 8)).isoformat()
        # 100 possessions per team: fga 90, oreb 10, tov 15, fta 11.36 -> 100.0
        for side, team, pts in ((1, 1, 100 + margin / 2), (0, 2, 100 - margin / 2)):
            for k, pid in enumerate(home if side else away):
                rows.append({"game_id": gid, "player_id": int(pid) + 1, "team_id": team, "game_date": gdate,
                             "season": "2024-25", "is_home": side, "minutes": 48.0,
                             "pts": pts / 5, "oreb": 2, "dreb": 6, "ast": 4, "stl": 1, "blk": 1, "tov": 3,
                             "pf": 2, "fgm": 8, "fga": 18, "ftm": 2, "fta": 11.36 / 5})
    return pd.DataFrame(rows), effects


class RapmTests(unittest.TestCase):
    def test_ridge_recovers_known_effects(self):
        pg, effects = synthetic_player_games()
        games = ratings.game_table(pg).sort_values(["game_date", "game_id"]).reset_index(drop=True)
        self.assertAlmostEqual(float(games["poss"].iloc[0]), 100.0, places=2)
        X, players = ratings.design(pg, games)
        w = np.ones(len(games))
        coef, intercept, alpha, se = ratings.fit_rapm(X, games["y"].to_numpy(), w, np.zeros(len(players)),
                                                      alphas=(1.0,))
        truth = effects[players - 1]
        truth_centered = truth - truth.mean()
        est_centered = coef - coef.mean()
        self.assertGreater(np.corrcoef(est_centered, truth_centered)[0, 1], 0.98)
        self.assertLess(np.mean(np.abs(est_centered - truth_centered)), 0.6)
        self.assertAlmostEqual(intercept, 2.0, delta=0.5)
        self.assertTrue(np.all(se > 0))

    def test_prior_pulls_toward_prior_when_penalty_is_large(self):
        pg, _ = synthetic_player_games(n_games=200)
        games = ratings.game_table(pg).sort_values(["game_date", "game_id"]).reset_index(drop=True)
        X, players = ratings.design(pg, games)
        prior = np.full(len(players), 3.0)
        coef, *_ = ratings.fit_rapm(X, games["y"].to_numpy(), np.ones(len(games)), prior, alphas=(1e7,))
        self.assertTrue(np.allclose(coef, 3.0, atol=0.05))

    def test_ratings_use_no_games_on_or_after_as_of(self):
        pg, _ = synthetic_player_games(n_games=400)
        as_of = date.fromisoformat(pg["game_date"].max()) - timedelta(days=5)
        with patch.object(config, "RATING_MIN_GAMES", 10):
            base = ratings.compute(pg, as_of)
            # Blow up every game on/after as_of: ratings must not move.
            later = pg["game_date"] >= as_of.isoformat()
            tampered = pg.copy()
            tampered.loc[later & (tampered["is_home"] == 1), "pts"] += 500
            tampered.loc[later, "minutes"] = 1.0
            again = ratings.compute(tampered, as_of)
        pd.testing.assert_frame_equal(base.reset_index(drop=True), again.reset_index(drop=True))
        self.assertEqual(set(base["rating_type"]), {"rapm_lite_v1", "box_value_v1"})
        self.assertTrue((base["as_of"] == as_of.isoformat()).all())

    def test_box_value_is_centered_and_shrunk(self):
        pg, _ = synthetic_player_games(n_games=300)
        pg.loc[pg["player_id"] == 1, "pts"] += 10           # player 1 scores more
        games = ratings.game_table(pg)
        wbg = dict(zip(games["game_id"], np.ones(len(games))))
        box = ratings.box_values(pg, games, wbg).set_index("player_id")
        self.assertEqual(box["value"].idxmax(), 1)


class MinutesTests(unittest.TestCase):
    def test_redistribution_conserves_total_and_respects_cap(self):
        base = np.array([36, 34, 32, 30, 28, 20, 18, 15, 12, 10, 5], dtype=float)
        p = np.array([0, 1, 1, 0.5, 1, 1, 1, 1, 1, 1, 1], dtype=float)
        m, exp, s = minutes.redistribute(base, p)
        self.assertAlmostEqual(exp.sum(), 240.0, places=4)
        self.assertTrue(np.all(m <= config.MINUTES_PLAYER_CAP + 1e-9))
        self.assertEqual(exp[0], 0.0)                      # out -> 0 expected minutes
        self.assertGreater(s, 1.0)                         # minutes flowed to the others
        self.assertAlmostEqual(exp[3], 0.5 * m[3])

    def test_cap_binds(self):
        base = np.array([40, 40, 40, 40, 40, 2], dtype=float)
        m, exp, s = minutes.redistribute(base, np.array([1, 1, 1, 0, 0, 1], dtype=float))
        self.assertTrue(np.all(m <= 40.0 + 1e-9))
        self.assertAlmostEqual(exp.sum(), min(240.0, 40 * 4), places=4)

    def test_status_map(self):
        self.assertEqual(minutes.p_play_for_status("out"), 0.0)
        self.assertEqual(minutes.p_play_for_status("doubtful"), 0.05)
        self.assertEqual(minutes.p_play_for_status("questionable"), 0.5)
        self.assertEqual(minutes.p_play_for_status("probable"), 0.9)
        self.assertEqual(minutes.p_play_for_status("available"), 1.0)
        self.assertEqual(minutes.p_play_for_status(None), 1.0)

    def test_project_game_out_player_and_leakage(self):
        rows = []
        start = date(2025, 10, 21)
        for g in range(12):
            gdate = (start + timedelta(days=2 * g)).isoformat()
            for team, home in ((1, 1), (2, 0)):
                for k in range(9):
                    pid = team * 100 + k
                    rows.append({"game_id": f"00225{g:05d}", "player_id": pid, "team_id": team,
                                 "game_date": gdate, "season": "2025-26", "is_home": home,
                                 "minutes": [36, 34, 32, 30, 28, 30, 20, 18, 12][k]})
        pg = pd.DataFrame(rows)
        game_date = (start + timedelta(days=30)).isoformat()
        as_of = datetime(2025, 11, 20, 18, 0)
        # add a future game with silly minutes: must not affect the projection
        future = pg[pg["game_id"] == "0022500011"].assign(game_id="0022509999", game_date=game_date, minutes=1)
        out = minutes.project_game("0022500100", game_date, 1, 2, as_of, pg_all=pd.concat([pg, future]),
                                   p_play={100: 0.0, 101: 0.5})
        clean = minutes.project_game("0022500100", game_date, 1, 2, as_of, pg_all=pg, p_play={100: 0.0, 101: 0.5})
        pd.testing.assert_frame_equal(out, clean)
        t1 = out[out["team_id"] == 1].set_index("player_id")
        self.assertEqual(t1.loc[100, "exp_min"], 0.0)
        self.assertEqual(t1.loc[100, "role"], "inactive")
        self.assertAlmostEqual(t1["exp_min"].sum(), 240.0, places=3)
        self.assertAlmostEqual(out[out["team_id"] == 2]["exp_min"].sum(), 240.0, places=3)
        self.assertEqual((t1["role"] == "starter").sum(), 5)
        self.assertTrue((t1["min_p10"] <= t1["min_p90"]).all())
        self.assertEqual(out["game_id"].iloc[0], "0022500100")


if __name__ == "__main__":
    unittest.main()
