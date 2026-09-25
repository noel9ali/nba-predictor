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
    DAYS, GAME_DETAIL, LIVE_SCORES, MODEL, PERFORMANCE, PREDICTIONS, SLATE, WORKFLOW_STATUS, check,
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
    return {"days": DAYS, "model": MODEL}[name]


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

    def test_tonight_is_the_games_draft_slate(self):
        self.assertEqual(self.slate["phase"], "picks_posted")
        self.assertEqual(self.slate["summary"]["bets_placed"], 5)
        self.assertEqual(self.slate["summary"]["staked"], 240.36)
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


class SampleHygieneTests(unittest.TestCase):
    def test_no_secret_or_env_names_in_sample_data(self):
        pattern = re.compile(r"SUPABASE|sb_secret|sb_publishable|eyJhbGci|dummy", re.I)
        for path in glob.glob(os.path.join(SAMPLE_DIR, "*.json")):
            with open(path, encoding="utf-8") as fh:
                self.assertIsNone(pattern.search(fh.read()), path)


if __name__ == "__main__":
    unittest.main()
