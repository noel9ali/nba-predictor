"""public/sample/*.json (sample mode, ?sample=1): every file is shaped exactly like its 04
response, and the numbers follow DESIGN_STATE sec1 "Sample data fixes": the season ends at
$1,111.67 with $4,275.40 staked, bets 54-41 and picks 124-65, and the rail, the night
recaps and Performance all agree. Regenerate with scripts/build_sample_data.py.
"""
import glob
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from contract_shapes import (  # noqa: E402
    DAYS, FEATURED_PICK, GAME_DETAIL, LIVE_SCORES, MODEL, PERFORMANCE, PREDICTIONS, SLATE,
    WORKFLOW_STATUS, check,
)

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "public", "sample")


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load(name):
    return read_json(os.path.join(SAMPLE_DIR, f"{name}.json"))


def shape_for(name):
    if name.startswith("slate-"):
        return SLATE
    if name.startswith("game-"):
        return GAME_DETAIL
    if name.startswith("live-"):
        return LIVE_SCORES
    if name.startswith("performance"):
        return PERFORMANCE
    if name.startswith("predictions"):
        return PREDICTIONS
    if name.startswith("workflow-status"):
        return WORKFLOW_STATUS
    return {"days": DAYS, "model": MODEL, "featured-pick": FEATURED_PICK}[name]


class SampleShapeTests(unittest.TestCase):
    def test_every_sample_file_matches_its_contract_shape(self):
        names = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(SAMPLE_DIR, "*.json")))
        self.assertGreater(len(names), 200)
        for name in names:
            with self.subTest(file=name):
                errors = check(load(name), shape_for(name))
                self.assertEqual(errors, [], "\n".join(errors[:10]))

    def test_file_names_are_the_ones_the_page_can_ask_for(self):
        for path in glob.glob(os.path.join(SAMPLE_DIR, "*")):
            self.assertRegex(os.path.basename(path), r"^[a-z0-9-]+\.json$")

    def test_every_game_the_page_links_to_has_a_drawer_file(self):
        ids = {g["game_id"] for p in glob.glob(os.path.join(SAMPLE_DIR, "slate-*.json"))
               for g in read_json(p)["games"] if g["pick"] is not None}
        ids |= {r["game_id"] for r in load("predictions")["rows"]}
        for gid in ids:
            with self.subTest(game=gid):
                self.assertTrue(os.path.isfile(os.path.join(SAMPLE_DIR, f"game-{gid}.json")))


class SampleSeasonTests(unittest.TestCase):
    def setUp(self):
        self.perf = load("performance")
        self.days = {d["date"]: d for d in load("days")["days"]}

    def test_season_totals_match_the_design(self):
        k = self.perf["kpis"]
        self.assertEqual(k["bankroll"], 1111.67)
        self.assertEqual(k["staked"], 4275.40)
        self.assertEqual(k["bets"], "54-41")
        self.assertEqual(k["picks"], "124-65")
        self.assertEqual(k["net_pl"], 111.67)
        self.assertEqual(k["max_drawdown"],
                         {"amount": 91.67, "peak_date": "2026-11-05", "trough_date": "2026-11-15"})
        settled = [p for p in self.perf["series"] if p["pending"] == 0 and p["picks"] != "0-0"]
        self.assertEqual((settled[0]["date"], settled[-1]["date"]), ("2026-10-21", "2026-11-16"))

    def test_rail_nights_match_the_canvas(self):
        rail = {"2026-11-10": ("4-2", 12.10), "2026-11-11": ("6-5", -15.60),
                "2026-11-12": ("2-1", 8.95), "2026-11-13": ("5-3", 18.40),
                "2026-11-14": ("7-4", -22.15), "2026-11-15": ("3-3", -9.80),
                "2026-11-16": ("3-1", 25.47)}
        for day, (picks, net) in rail.items():
            with self.subTest(day=day):
                self.assertEqual(self.days[day]["picks"], picks)
                self.assertAlmostEqual(self.days[day]["net_pl"], net, places=2)

    def test_rail_recaps_and_performance_agree(self):
        series = {p["date"]: p for p in self.perf["series"]}
        balance = 1000.0
        for day in sorted(d for d in self.days if d <= "2026-11-16"):
            slate = load(f"slate-{day}")
            recap = slate["recap"]
            with self.subTest(day=day):
                self.assertAlmostEqual(recap["net_pl"], self.days[day]["net_pl"], places=2)
                self.assertAlmostEqual(recap["net_pl"], series[day]["nightly_pl"], places=2)
                self.assertEqual(recap["picks"], self.days[day]["picks"])
                self.assertEqual(recap["bets"], self.days[day]["bets"])
                self.assertAlmostEqual(recap["bankroll_before"], balance, places=2)
                self.assertAlmostEqual(recap["bankroll_after"], series[day]["bankroll"], places=2)
                balance = recap["bankroll_after"]
        self.assertAlmostEqual(balance, 1111.67, places=2)

    def test_last_night_is_the_draft_with_the_tor_fix(self):
        games = {g["pick"]: g for g in load("slate-2026-11-16")["games"]}
        tor = games["TOR"]
        self.assertIsNone(tor["bet"])
        self.assertEqual(tor["odds"], -150)
        self.assertAlmostEqual(tor["edge"], -0.02, places=4)
        self.assertEqual(games["PHI"]["bet"]["profit_loss"], 28.30)
        self.assertEqual(games["OKC"]["bet"]["profit_loss"], 19.57)
        self.assertEqual(games["ATL"]["bet"]["profit_loss"], -22.40)
        recap = load("slate-2026-11-16")["recap"]
        self.assertEqual((recap["bankroll_before"], recap["bankroll_after"]), (1086.20, 1111.67))


class SampleTonightTests(unittest.TestCase):
    def setUp(self):
        self.slate = load("slate-2026-11-17")
        self.games = {g["pick"]: g for g in self.slate["games"]}

    def test_sac_bet_is_quarter_kelly_capped_at_five_percent(self):
        sac = self.games["SAC"]
        bet = sac["bet"]
        self.assertEqual(bet["amount"], 55.58)
        self.assertEqual(bet["bankroll_at_bet"], 1111.67)
        self.assertEqual(bet["kelly_fraction"], 0.25)
        quarter = bet["kelly_full"] * bet["kelly_fraction"]
        self.assertAlmostEqual(quarter, 0.05, places=3)  # quarter-Kelly 5.0% ...
        self.assertEqual(round(min(quarter, 0.05) * 1111.67, 2), 55.58)  # ... capped at 5%
        self.assertEqual(round(55.58 * 100 / 105, 2), 52.93)  # the hit pays +$52.93
        self.assertEqual(sac["odds"], -105)
        self.assertEqual(sac["bookmaker"], "FanDuel")

    def test_every_bet_tonight_is_quarter_kelly_capped_at_five_percent(self):
        for game in self.slate["games"]:
            bet = game["bet"]
            if not bet:
                continue
            with self.subTest(pick=game["pick"]):
                quarter = bet["kelly_full"] * bet["kelly_fraction"]
                # kelly_full is stored to 4 decimals, so allow a one-cent rounding difference.
                self.assertAlmostEqual(bet["amount"], min(quarter, 0.05) * bet["bankroll_at_bet"], delta=0.011)

    def test_tonight_is_the_games_draft_slate(self):
        self.assertEqual(self.slate["phase"], "picks_posted")
        self.assertEqual(self.slate["summary"]["bets_placed"], 5)
        self.assertEqual(self.slate["summary"]["staked"], 218.27)
        self.assertEqual(self.slate["last_slate_date"], "2026-11-16")
        expected_edges = {"MIA": 0.122, "NYK": 0.039, "MIN": 0.084, "CLE": 0.06, "LAL": -0.033, "SAC": 0.098}
        for pick, edge in expected_edges.items():
            with self.subTest(pick=pick):
                self.assertAlmostEqual(self.games[pick]["edge"], edge, delta=0.001)
        self.assertIsNone(self.games["LAL"]["bet"])

    def test_live_scenes_reference_tonights_games(self):
        ids = {g["game_id"] for g in self.slate["games"]}
        for path in glob.glob(os.path.join(SAMPLE_DIR, "live-*.json")):
            name = os.path.basename(path)
            if name == "live-edges.json":
                ids_here = {g["game_id"] for g in load("slate-2026-11-17-edges")["games"]}
            else:
                ids_here = ids
            with self.subTest(file=name):
                self.assertTrue({g["game_id"] for g in read_json(path)["games"]} <= ids_here)

    def test_offseason_scene_is_the_real_offseason_state(self):
        off = load("slate-2026-11-17-offseason")
        self.assertEqual(off["phase"], "no_games")
        self.assertTrue(off["offseason"])
        self.assertEqual(off["last_slate_date"], "2026-11-16")


class SampleLiveReplayTests(unittest.TestCase):
    """live-replay-0..6 follow handoff/components/live-feed.md sec3.8 (the scripted night)."""

    def games(self, name):
        return {g["game_id"]: g for g in load(name)["games"]}

    def test_replay_files_are_full_sample_responses_on_the_scripted_clock(self):
        stamps = ["02:05", "02:31", "02:52", "03:16", "03:33", "04:58", "05:41"]
        for i, hhmm in enumerate(stamps):
            with self.subTest(file=i):
                body = load(f"live-replay-{i}")
                self.assertEqual(body["fetched_at"], f"2026-11-18T{hhmm}:00Z")
                self.assertEqual((body["source"], body["stale"]), ("sample", False))
                self.assertEqual(len(body["games"]), 6)

    def test_replay_0_is_the_9_05_pm_state(self):
        self.assertEqual(load("live-replay-0")["games"], load("live-live")["games"])
        g = self.games("live-replay-0")
        self.assertEqual((g["0022600190"]["status"], g["0022600190"]["away_score"],
                          g["0022600190"]["home_score"], g["0022600190"]["clock"]), ("final", 112, 104, "Final"))
        self.assertEqual((g["0022600191"]["home_score"], g["0022600191"]["away_score"],
                          g["0022600191"]["clock"], g["0022600191"]["period"]), (76, 71, "Q3 4:40", 3))
        self.assertEqual((g["0022600192"]["home_score"], g["0022600192"]["away_score"]), (44, 48))
        self.assertEqual((g["0022600193"]["home_score"], g["0022600193"]["away_score"]), (47, 45))
        self.assertEqual((g["0022600194"]["status"], g["0022600195"]["status"]), ("scheduled", "scheduled"))

    def test_scripted_steps(self):
        def row(i, gid):
            g = self.games(f"live-replay-{i}")[gid]
            return (g["status"], g["period"], g["clock"], g["home_score"], g["away_score"])

        self.assertEqual(row(1, "0022600191"), ("live", 3, "Q3 1:12", 81, 73))
        self.assertEqual(row(1, "0022600192"), ("live", 3, "Q3 2:05", 70, 71))
        self.assertEqual(row(1, "0022600193"), ("live", 3, "Q3 0:40", 66, 74))
        self.assertEqual(row(2, "0022600191"), ("final", 4, "Final", 109, 101))
        self.assertEqual(row(3, "0022600194"), ("live", 1, "Q1 11:21", 2, 0))
        self.assertEqual(row(3, "0022600192"), ("final", 4, "Final", 103, 110))
        self.assertEqual(row(3, "0022600193"), ("final", 4, "Final", 109, 118))
        self.assertEqual(row(4, "0022600195"), ("live", 1, "Q1 11:02", 0, 3))
        self.assertEqual(row(4, "0022600194"), ("live", 1, "Q1 0:48", 30, 26))
        self.assertEqual(row(5, "0022600194"), ("live", 5, "OT 1:30", 115, 113))
        self.assertEqual(row(5, "0022600195"), ("live", 3, "Q3 5:10", 88, 84))
        self.assertEqual(row(6, "0022600194"), ("final", 5, "Final/OT", 121, 115))
        self.assertEqual(row(6, "0022600195"), ("final", 4, "Final", 118, 110))
        self.assertEqual([g["status"] for g in load("live-replay-6")["games"]], ["final"] * 6)

    def test_final_scene_is_the_end_of_the_replay(self):
        self.assertEqual(load("live-final")["games"], load("live-replay-6")["games"])

    def test_sofar_scene_agrees_with_the_script(self):
        g = self.games("live-sofar")
        self.assertEqual((g["0022600191"]["status"], g["0022600191"]["home_score"]), ("final", 109))
        self.assertEqual((g["0022600193"]["status"], g["0022600193"]["home_score"]), ("final", 109))
        self.assertEqual(g["0022600192"]["status"], "live")

    def test_end_of_night_settles_117_01_on_four_wins_and_a_loss(self):
        slate = {g["game_id"]: g for g in load("slate-2026-11-17")["games"]}
        final = self.games("live-replay-6")
        total, record, pl = 0.0, [0, 0], {}
        for gid, game in slate.items():
            bet = game["bet"]
            if not bet:
                continue
            live = final[gid]
            leader = "home" if live["home_score"] > live["away_score"] else "away"
            picked = "home" if game["pick"] == game["home"]["tricode"] else "away"
            odds = game["odds"]
            payout = bet["amount"] * (odds / 100 if odds > 0 else 100 / -odds)
            hit = leader == picked
            pl[game["pick"]] = payout if hit else -bet["amount"]
            total += pl[game["pick"]]
            record[0 if hit else 1] += 1
        self.assertEqual(record, [4, 1])
        self.assertAlmostEqual(total, 117.007, places=2)
        self.assertEqual(round(total, 2), 117.01)
        for pick, want in {"MIA": 58.36, "NYK": 19.88, "MIN": -41.96, "CLE": 27.79, "SAC": 52.93}.items():
            self.assertAlmostEqual(pl[pick], want, places=2, msg=pick)
        # LAL (no bet) was the one wrong pick: picks 4-2 overall
        lal = slate["0022600194"]
        self.assertIsNone(lal["bet"])
        self.assertLess(final["0022600194"]["away_score"], final["0022600194"]["home_score"])  # pick (away) lost


class SampleHardwoodModelTests(unittest.TestCase):
    """The Model page's data (handoff/api-integration.md sec3, backend items B1-B4)."""

    def setUp(self):
        self.model = load("model")

    def test_hero_numbers_are_the_production_models_gradient_boosting(self):
        m = self.model
        self.assertEqual(m["production_model"], "gradient-boosting-gridsearch")
        self.assertEqual(m["trained_at"], "2026-10-07T05:09:34Z")
        self.assertEqual(m["cutoff_date"], "2025-02-25")
        self.assertEqual(m["test"], {"games": 1596, "accuracy": 0.6792, "brier": 0.2094,
                                     "log_loss": 0.6075, "roc_auc": 0.7295,
                                     "baseline_home_win_rate": 0.5501})

    def test_leaderboard_has_six_models_with_the_b1_extras(self):
        board = self.model["leaderboard"]
        self.assertEqual([r["model"] for r in board],
                         ["gradient-boosting", "calibrated-xgboost", "current-xgboost", "lstm",
                          "random-forest", "logistic"])
        want = {"gradient-boosting": (0.6792, 0.2094, 0.6075, 0.7295, 0.035),
                "calibrated-xgboost": (0.6779, 0.2099, 0.6085, 0.7250, 0.031),
                "current-xgboost": (0.6736, 0.2100, 0.6086, 0.7244, 0.026),
                "lstm": (0.6805, 0.2098, 0.6087, 0.7258, 0.027),
                "random-forest": (0.6817, 0.2102, 0.6092, 0.7285, 0.042),
                "logistic": (0.6811, 0.2091, 0.6325, 0.7293, 0.031)}
        for row in board:
            with self.subTest(model=row["model"]):
                got = (row["accuracy"], row["brier_score"], row["log_loss"], row["roc_auc"],
                       row["calibration_ece"])
                self.assertEqual(got, want[row["model"]])
                self.assertEqual(row["test_games"], 1596)
                self.assertEqual(row["is_production"], row["model"] == "gradient-boosting")
        # the production row's numbers are the headline test numbers
        prod = board[0]
        test = self.model["test"]
        self.assertEqual((prod["accuracy"], prod["brier_score"], prod["log_loss"], prod["roc_auc"]),
                         (test["accuracy"], test["brier"], test["log_loss"], test["roc_auc"]))

        # the bump chart's expectation: production ranks 4th on accuracy, 2nd on brier, 1st on log loss, 1st on auc
        def rank(key, reverse):
            return sorted(board, key=lambda r: r[key], reverse=reverse).index(prod) + 1

        self.assertEqual((rank("accuracy", True), rank("brier_score", False),
                          rank("log_loss", False), rank("roc_auc", True)), (4, 2, 1, 1))

    def test_feature_importance_adds_up(self):
        fi = self.model["feature_importance"]
        self.assertEqual([r["feature"] for r in fi],
                         ["ELO_DIFF", "HOME_ELO", "HOME_roll_PTS", "rest_diff", "AWAY_roll_TOV"])
        # Normalized from the raw importances
        self.assertAlmostEqual(sum(r["share"] for r in fi), 1.0, places=9)

    def test_training_block_adds_up(self):
        t = self.model["training"]
        self.assertEqual((t["first_game_date"], t["cutoff_date"], t["last_game_date"]),
                         ("2019-11-22", "2025-02-25", "2026-04-12"))
        self.assertEqual((t["games_total"], t["train_games"], t["test_games"]), (7979, 6383, 1596))
        self.assertEqual(t["games_total"], t["train_games"] + t["test_games"])
        self.assertEqual((t["home_win_rate"], t["rolling_window"]), (0.5501, 10))
        seasons = t["seasons"]
        self.assertEqual([s["season"] for s in seasons],
                         ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"])
        self.assertEqual(sum(s["games"] for s in seasons), t["games_total"])
        self.assertEqual(sum(s["train"] for s in seasons), t["train_games"])
        self.assertEqual(sum(s["test"] for s in seasons), t["test_games"])
        for s in seasons:
            self.assertEqual(s["games"], s["train"] + s["test"], s["season"])
        self.assertEqual((seasons[5]["train"], seasons[5]["test"]), (854, 371))
        self.assertEqual((seasons[0]["games"], seasons[6]["games"]), (759, 1225))

    def test_elo_constants(self):
        self.assertEqual(self.model["elo"],
                         {"k": 20, "home_advantage": 100, "mean_reversion": 0.25, "start": 1500})

    def test_the_contract_still_accepts_the_api_without_the_new_fields(self):
        old = {k: v for k, v in self.model.items() if k not in ("feature_importance", "training", "elo")}
        old["leaderboard"] = [{k: v for k, v in r.items()
                               if k not in ("roc_auc", "calibration_ece", "test_games", "is_production")}
                              for r in self.model["leaderboard"]]
        self.assertEqual(check(old, MODEL), [])
        bad = json.loads(json.dumps(self.model))
        bad["training"]["games_total"] = "7979"
        self.assertTrue(check(bad, MODEL))


class SampleFeaturedPickTests(unittest.TestCase):
    def test_featured_pick_is_the_settled_sac_game(self):
        fp = load("featured-pick")
        self.assertEqual(fp["game_id"], "0022600195")
        self.assertEqual(check(fp, FEATURED_PICK), [])
        self.assertEqual(check({**fp, "game_id": None}, FEATURED_PICK), [])  # the "no pick yet" shape

    def test_featured_game_detail_is_settled(self):
        d = load("game-0022600195")
        g = d["game"]
        self.assertEqual((g["status"], g["result"]), ("final", "hit"))
        self.assertEqual((g["home"]["tricode"], g["home"]["score"]), ("SAC", 118))
        self.assertEqual((g["away"]["tricode"], g["away"]["score"]), ("GSW", 110))
        self.assertEqual((g["pick"], g["odds"], g["bookmaker"], g["edge"]), ("SAC", -105, "FanDuel", 0.0978))
        bet = g["bet"]
        self.assertEqual((bet["result"], bet["profit_loss"], bet["amount"], bet["bankroll_at_bet"],
                          bet["kelly_full"], bet["kelly_fraction"]),
                         ("hit", 52.93, 55.58, 1111.67, 0.2005, 0.25))
        self.assertEqual(d["result"], {"winner": "SAC", "home_score": 118, "away_score": 110, "correct": 1})
        self.assertEqual(d["model_name"], "gradient-boosting-gridsearch")

    def test_featured_game_tape_is_the_walkthrough_example(self):
        tape = load("game-0022600195")["tape"]
        self.assertEqual(tape["home"], {"elo": 1561.0, "rest_days": 2.0, "roll_pts": 117.8,
                                        "roll_fg_pct": 0.483, "roll_reb": 44.6, "roll_ast": 26.4,
                                        "roll_tov": 13.1, "roll_stocks": 13.9})
        self.assertEqual(tape["away"], {"elo": 1528.0, "rest_days": 1.0, "roll_pts": 114.2,
                                        "roll_fg_pct": 0.461, "roll_reb": 43.0, "roll_ast": 28.9,
                                        "roll_tov": 14.8, "roll_stocks": 15.2})
        self.assertEqual(tape["better"], {
            "elo": "home", "rest_days": "home", "roll_pts": "home", "roll_fg_pct": "home",
            "roll_reb": "home", "roll_ast": "away", "roll_tov": "home", "roll_stocks": "away"})

    def test_tonights_slate_still_lists_that_game_as_scheduled(self):
        games = {g["game_id"]: g for g in load("slate-2026-11-17")["games"]}
        g = games["0022600195"]
        self.assertEqual((g["status"], g["result"], g["home"]["score"]), ("scheduled", None, None))
        self.assertIsNone(g["bet"]["result"])


class SamplePerformanceFilesTests(unittest.TestCase):
    def test_all_time_board_for_the_season_switcher(self):
        allp = load("performance-all")
        self.assertEqual(allp["season"], "all")
        self.assertEqual(allp["seasons"], ["2026-27"])
        k = allp["kpis"]
        self.assertEqual((k["picks"], k["bets"], k["staked"], k["net_pl"], k["bankroll"]),
                         ("124-65", "54-41", 4275.40, 111.67, 1111.67))
        self.assertAlmostEqual(k["accuracy"], 124 / 189, places=5)
        self.assertAlmostEqual(k["roi"], 0.02612, places=5)
        self.assertEqual(k["max_drawdown"]["amount"], 91.67)

    def test_one_file_per_listed_season(self):
        allp = load("performance-all")
        for season in allp["seasons"]:
            with self.subTest(season=season):
                body = load(f"performance-{season}")
                self.assertEqual(body["season"], season)
                self.assertEqual(body["kpis"], allp["kpis"])  # the sample has one season only
        self.assertEqual(load("performance")["kpis"], allp["kpis"])  # the existing file stays


class SamplePastNightTests(unittest.TestCase):
    """?sample=1&date=2026-11-16: the page's past-night scene is a real settled slate file."""

    def test_nov_16_is_a_settled_past_night_with_a_recap(self):
        s = load("slate-2026-11-16")
        self.assertTrue(s["is_past"])
        self.assertEqual(s["phase"], "all_final")
        self.assertEqual(len(s["games"]), 4)
        self.assertTrue(all(g["status"] == "final" for g in s["games"]))
        for g in s["games"]:
            if g["bet"]:
                self.assertIn(g["bet"]["result"], ("hit", "miss"))
                self.assertIsNotNone(g["bet"]["profit_loss"])
        self.assertEqual((s["recap"]["picks"], s["recap"]["bets"], s["recap"]["net_pl"]), ("3-1", "2-1", 25.47))


class SampleHygieneTests(unittest.TestCase):
    def test_no_secret_or_env_names_in_sample_data(self):
        pattern = re.compile(r"SUPABASE|sb_secret|sb_publishable|eyJhbGci|dummy", re.I)
        for path in glob.glob(os.path.join(SAMPLE_DIR, "*.json")):
            with open(path, encoding="utf-8") as fh:
                self.assertIsNone(pattern.search(fh.read()), path)


if __name__ == "__main__":
    unittest.main()
