"""scripts/market_vs_model.py on synthetic data, an empty archive and a tiny archive (no crash, honest n/a)."""
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

import config  # noqa: E402
import odds_archive  # noqa: E402

spec = importlib.util.spec_from_file_location("market_vs_model", os.path.join(ROOT, "scripts", "market_vs_model.py"))
mvm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mvm)

PAIRS = [("ATL", "BOS"), ("MIA", "ORL"), ("DEN", "LAL"), ("NYK", "PHI"), ("MIL", "CHI"), ("GSW", "SAC")]


def ev(eid, home, away, tip, hp, ap):
    return {"id": eid, "commence_time": tip.strftime("%Y-%m-%dT%H:%M:%SZ"), "home_team": mvm.ABBR_NAMES[home],
            "away_team": mvm.ABBR_NAMES[away],
            "bookmakers": [{"key": b, "title": b, "markets": [{"key": "h2h", "outcomes": [
                {"name": mvm.ABBR_NAMES[home], "price": hp + d}, {"name": mvm.ABBR_NAMES[away], "price": ap - d}]}]}
                for b, d in (("draftkings", 0), ("fanduel", 4), ("betmgm", -3))]}


def am(p):
    """american price for probability p (with ~4.5% margin split evenly)."""
    q = min(max(p * 1.0225, 0.02), 0.98)
    return int(round(-100 * q / (1 - q))) if q >= 0.5 else int(round(100 * (1 - q) / q))


class SyntheticMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.arch = os.path.join(self.tmp.name, "odds_history", "odds_history.sqlite")
        self.inj = os.path.join(self.tmp.name, "inj.sqlite")
        rng = np.random.default_rng(4)
        arch = odds_archive.connect(self.arch)
        base = datetime(2026, 11, 3, 0, 30, tzinfo=timezone.utc)
        self.preds, self.n = [], 90
        conn = sqlite3.connect(self.inj)
        conn.execute("create table injury_snapshots (game_id text, team_id integer, player_id integer, player_name_raw text, "
                     "report_time text, status text)")
        for i in range(self.n):
            home, away = PAIRS[i % len(PAIRS)]
            tip = base + timedelta(days=i // 6, minutes=30 * (i % 3))
            true_p = float(rng.uniform(0.25, 0.75))
            open_p = float(np.clip(true_p + rng.normal(0, 0.03), 0.1, 0.9))
            injured_home = i % 4 == 0                        # home star newly out between pricing and close
            close_p = float(np.clip(open_p - (0.04 if injured_home else 0.0) + rng.normal(0, 0.005), 0.1, 0.9))
            gid = f"00226{i:05d}"
            t_open, t_close = tip - timedelta(minutes=65), tip - timedelta(minutes=8)
            for t, p, purpose in ((t_open, open_p, "pricing"), (t_close, close_p, "closing")):
                odds_archive.archive_response([ev(f"e{i}", home, away, tip, am(p), am(1 - p))], {"x-requests-remaining": "400"},
                                              t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), purpose=purpose, conn=arch)
            if i % 2 == 0:                                      # half get the NBA id, the rest rely on the team-pair match
                games = pd.DataFrame([{"gameId": gid, "HOME_TEAM_ABBREVIATION": home, "VISITOR_TEAM_ABBREVIATION": away,
                                       "TIP_UTC": tip.strftime("%Y-%m-%dT%H:%M:%SZ")}])
                odds_archive.link_game_ids(games, conn=arch)
            home_win = rng.random() < true_p
            model_p = float(np.clip(true_p + rng.normal(0, 0.04), 0.05, 0.95))
            self.preds.append({"game_id": gid, "game_date": (tip - timedelta(hours=8)).strftime("%Y-%m-%d"),
                               "home_team": home, "away_team": away, "home_win_prob": model_p,
                               "predicted_winner": home if model_p > 0.5 else away, "bet_placed": None,
                               "actual_winner": home if home_win else away, "tip_time_utc": tip.isoformat(),
                               "predicted_at": (t_open + timedelta(minutes=2)).isoformat()})
            hid = config.TEAM_IDS[home]
            conn.execute("insert into injury_snapshots values (?,?,?,?,?,?)", (gid, hid, 11, "Star, Home",
                                                                                (t_open - timedelta(hours=1)).isoformat(), "probable"))
            if injured_home:
                conn.execute("insert into injury_snapshots values (?,?,?,?,?,?)", (gid, hid, 11, "Star, Home",
                                                                                    (tip - timedelta(minutes=20)).isoformat(), "out"))
        conn.commit()
        conn.close()
        arch.close()
        self.csv = os.path.join(self.tmp.name, "preds.csv")
        pd.DataFrame(self.preds).to_csv(self.csv, index=False)

    def run_main(self, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = mvm.main(["--archive", self.arch, "--predictions", self.csv, "--injuries", self.inj, *extra])
        return rc, buf.getvalue()

    def test_full_report_on_synthetic_data(self):
        snaps, calls = mvm.load_archive(self.arch)
        out = mvm.analyse(mvm.load_predictions(self.csv), snaps, calls, self.inj)
        self.assertEqual(out["n_games_with_pricing_snapshot"], self.n)
        self.assertEqual(out["n_games_with_close"], self.n)
        self.assertEqual(out["n_matched_to_predictions"], self.n)
        self.assertEqual(out["requests_remaining_last"], 400)
        self.assertEqual(set(out["calibration"]), {"model", "pricing_market", "close_market"})
        self.assertAlmostEqual(out["median_minutes_to_tip_open"], 65, delta=0.1)
        self.assertAlmostEqual(out["median_minutes_to_tip_close"], 8, delta=0.1)
        # injured games (every 4th) move the home price down ~4 points: big moves coincide with the injury change
        self.assertGreaterEqual(out["n_big_moves"], self.n // 4 - 2)
        self.assertGreater(out["share_injury_change_big_moves"], out["share_injury_change_small_moves"])
        self.assertLess(out["corr_move_vs_home_injury_score"], -0.5)      # a home player out: home prob falls
        m, lo, hi, n = out["model_minus_market_mean"]
        self.assertTrue(lo <= m <= hi)
        self.assertEqual(n, self.n)

    def test_cli_prints_a_report_and_the_sample_size_warning(self):
        rc, text = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("games with a pricing snapshot: 90", text)
        self.assertIn("CLV of the priced side", text)
        self.assertIn("NOTE: only 90 games have both snapshots", text)

    def test_json_and_out_dir(self):
        out_dir = os.path.join(self.tmp.name, "out")
        rc, text = self.run_main("--json", "--out-dir", out_dir)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(os.path.join(out_dir, "market_vs_model_games.csv")))
        import json
        self.assertEqual(json.loads(text)["n_games_with_close"], self.n)

    def test_no_vig_and_name_map(self):
        self.assertAlmostEqual(mvm.no_vig_home(-110, -110), 0.5)
        self.assertAlmostEqual(mvm.no_vig_home(-200, 170), 0.6667 / (0.6667 + 0.3704), places=3)
        import odds
        self.assertEqual(mvm.ABBR_NAMES, odds.ABBR_MAP)


class DegenerateInputTests(unittest.TestCase):
    def test_missing_files_and_empty_archive_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = mvm.main(["--archive", os.path.join(tmp, "nope.sqlite"), "--predictions", os.path.join(tmp, "nope.csv"),
                               "--injuries", os.path.join(tmp, "nope2.sqlite")])
            self.assertEqual(rc, 0)
            self.assertIn("no usable games", buf.getvalue())
            empty = os.path.join(tmp, "empty.sqlite")
            odds_archive.connect(empty).close()                             # schema only
            with redirect_stdout(io.StringIO()):
                self.assertEqual(mvm.main(["--archive", empty, "--json"]), 0)

    def test_tiny_archive_one_game_no_close_no_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            arch = os.path.join(tmp, "a.sqlite")
            tip = datetime(2026, 11, 3, 0, 30, tzinfo=timezone.utc)
            conn = odds_archive.connect(arch)
            odds_archive.archive_response([ev("e1", "ATL", "BOS", tip, -150, 130)], {}, (tip - timedelta(minutes=65)).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"), conn=conn)
            conn.close()
            csv = os.path.join(tmp, "p.csv")
            pd.DataFrame([{"game_id": "0022600001", "game_date": "2026-11-02", "home_team": "ATL", "away_team": "BOS",
                           "home_win_prob": 58.0}]).to_csv(csv, index=False)          # percent, no outcome
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = mvm.main(["--archive", arch, "--predictions", csv, "--injuries", os.path.join(tmp, "none.sqlite")])
            self.assertEqual(rc, 0)
            self.assertIn("with a close snapshot: 0", buf.getvalue())
            self.assertIn("NOTE: only 0 games have both snapshots", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
