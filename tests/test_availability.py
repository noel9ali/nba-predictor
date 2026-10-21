"""Phase 4: availability features and rest days (offline)."""

import os
import sys
import unittest
import unittest.mock
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import availability_features as af  # noqa: E402
import config  # noqa: E402

T1, T2 = 1, 2


def roster(ratings, p, base=None):
    base = base or [40.0] * len(ratings)
    return pd.DataFrame({"player_id": range(1, len(ratings) + 1), "base_min": base, "p_play": p,
                         "rating": ratings})


class TeamFeatureTests(unittest.TestCase):
    def test_hand_computed_example(self):
        ratings = [6.0, 3.0, 0.0, 0.0, -3.0, -6.0]
        healthy = af.team_features(roster(ratings, [1, 1, 1, 1, 1, 1]))
        self.assertAlmostEqual(healthy["rating_baseline"], 0.0)          # 40/240 x sum(ratings) = 0
        self.assertAlmostEqual(healthy["rating_expected"], 0.0)
        self.assertEqual(healthy["star_out"], 0)
        star_out = af.team_features(roster(ratings, [0, 1, 1, 1, 1, 1]))
        # The other five are capped at 40, so expected = 40/240 x (3 + 0 + 0 - 3 - 6) = -1.0
        self.assertAlmostEqual(star_out["rating_expected"], -1.0)
        self.assertAlmostEqual(star_out["value_out"], 1.0)
        self.assertEqual(star_out["star_out"], 1)
        self.assertAlmostEqual(star_out["top3_avail"], round(2 / 3, 4))
        self.assertAlmostEqual(star_out["minutes_lost"], 40.0)
        self.assertEqual(star_out["n_key_uncertain"], 0)

    def test_three_players_redistribution(self):
        # Three players with known ratings and room under the cap: the out player's minutes flow to the others.
        r = roster([4.0, 1.0, -2.0], [1, 1, 0], base=[30.0, 30.0, 20.0])
        with unittest.mock.patch.object(config, "MINUTES_TEAM_TOTAL", 80.0), \
                unittest.mock.patch.object(config, "AVAILABILITY_KEY_MIN_BASE_MINUTES", 0.0):
            f = af.team_features(r)
        # healthy: 30/80*4 + 30/80*1 + 20/80*-2 = 1.375; expected: 40/80*4 + 40/80*1 = 2.5
        self.assertAlmostEqual(f["rating_baseline"], 1.375)
        self.assertAlmostEqual(f["rating_expected"], 2.5)
        self.assertAlmostEqual(f["value_out"], -1.125)                   # losing a negative player helps
        self.assertEqual(f["star_out"], 0)

    def test_star_out_boundary_at_one_half(self):
        ratings = [6.0, 3.0, 0.0, 0.0, -3.0, -6.0]
        self.assertEqual(af.team_features(roster(ratings, [0.5, 1, 1, 1, 1, 1]))["star_out"], 0)
        self.assertEqual(af.team_features(roster(ratings, [0.49, 1, 1, 1, 1, 1]))["star_out"], 1)
        self.assertEqual(af.team_features(roster(ratings, [1, 0.49, 1, 1, 1, 1]))["star_out"], 1)
        self.assertEqual(af.team_features(roster(ratings, [1, 1, 0.0, 1, 1, 1]))["star_out"], 0)  # 3rd best
        self.assertEqual(af.team_features(roster(ratings, [0.5, 1, 1, 1, 1, 1]))["n_key_uncertain"], 1)

    def test_low_minute_player_is_not_a_star(self):
        r = roster([12.0, 3.0, 0.0, 0.0, -3.0, -6.0], [0, 1, 1, 1, 1, 1], base=[5, 40, 40, 40, 40, 40])
        self.assertEqual(af.team_features(r)["star_out"], 0)

    def test_empty_roster(self):
        self.assertIsNone(af.team_features(None)["rating_baseline"])


class RestTests(unittest.TestCase):
    def test_opener_b2b_and_all_star_break(self):
        self.assertEqual(af.rest_features([], "2025-10-21"),
                         {"rest_days": config.REST_DAYS_CAP, "is_b2b": 0, "games_last_7": 0})
        self.assertEqual(af.rest_features(["2025-10-21"], "2025-10-22"),
                         {"rest_days": 1, "is_b2b": 1, "games_last_7": 1})
        self.assertEqual(af.rest_features(["2026-02-12"], "2026-02-19")["rest_days"], 7)   # All-Star break
        self.assertEqual(af.rest_features(["2026-02-12"], "2026-02-21")["rest_days"], config.REST_DAYS_CAP)
        self.assertEqual(af.rest_features(["2025-10-21", "2025-10-23", "2025-10-25", "2025-10-27"],
                                          "2025-10-28")["games_last_7"], 4)
        # later games are ignored (no leakage)
        self.assertEqual(af.rest_features(["2025-10-21", "2025-10-30"], "2025-10-23")["rest_days"], 2)


class FakeLookup:
    def __init__(self, by_day):
        self.by_day = by_day

    def for_day(self, day):
        return {p: v for (d, p), v in self.by_day.items() if d <= day}


def history(n_games=24, start=date(2025, 10, 21)):
    rows = []
    for g in range(n_games):
        gdate = (start + timedelta(days=2 * g)).isoformat()
        gid = f"00225{g:05d}"
        for team, home in ((T1, 1), (T2, 0)):
            for k in range(8):
                rows.append({"game_id": gid, "player_id": team * 100 + k, "team_id": team, "game_date": gdate,
                             "season": "2025-26", "minutes": [36, 34, 32, 30, 28, 30, 30, 20][k]})
    return pd.DataFrame(rows)


class HistoryLeakageTests(unittest.TestCase):
    def test_features_ignore_future_games_and_future_ratings(self):
        pg = history()
        target = "0022500015"
        target_date = pg[pg["game_id"] == target]["game_date"].iloc[0]
        ratings = {(target_date, p): 1.0 for p in pg["player_id"].unique()}
        ratings[(target_date, 100)] = 8.0
        absent = {(target, 100)}
        base = [r for r in af.historical_rows(pg, absent, {"rapm_lite_v1": FakeLookup(ratings)})
                if r["game_id"] == target]
        # Tamper with everything after the target date: minutes, absences and ratings.
        tampered = pg.copy()
        later = tampered["game_date"] > target_date
        tampered.loc[later, "minutes"] = 2.0
        future_ratings = dict(ratings)
        future_ratings.update({("2099-01-01", p): -50.0 for p in pg["player_id"].unique()})
        again = [r for r in af.historical_rows(tampered, absent | {("0022500020", 101)},
                                               {"rapm_lite_v1": FakeLookup(future_ratings)})
                 if r["game_id"] == target]
        self.assertEqual(base, again)
        t1 = next(r for r in base if r["team_id"] == T1)
        self.assertEqual(t1["star_out"], 1)
        self.assertGreater(t1["value_out"], 0)
        self.assertEqual(t1["basis"], "realized")
        self.assertEqual(t1["rest_days"], 2)
        self.assertEqual(t1["game_id"], target)

    def test_same_day_game_does_not_leak(self):
        pg = history()
        target = "0022500010"
        target_date = pg[pg["game_id"] == target]["game_date"].iloc[0]
        ratings = {(target_date, p): 0.0 for p in pg["player_id"].unique()}
        base = af.historical_rows(pg, set(), {"box_value_v1": FakeLookup(ratings)})
        changed = pg.copy()
        changed.loc[changed["game_id"] == target, "minutes"] = 48.0      # the game's own box score
        again = af.historical_rows(changed, set(), {"box_value_v1": FakeLookup(ratings)})
        pick = lambda rows: [r for r in rows if r["game_id"] == target]  # noqa: E731
        self.assertEqual(pick(base), pick(again))

    def test_as_of_is_an_hour_before_tip(self):
        self.assertEqual(af.as_of_for("0022500001", "2025-10-21", {"0022500001": "2025-10-21T23:30:00Z"}),
                         "2025-10-21T22:30:00+00:00")
        self.assertEqual(af.as_of_for("x", "2025-10-21", {}), "2025-10-21T22:00:00+00:00")   # 7 PM EDT default


if __name__ == "__main__":
    unittest.main()
