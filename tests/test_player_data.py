"""Phase 1: player data foundation (offline, local SQLite store, hand-built fixtures)."""

import os
import sqlite3
import sys
import unittest
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import absences  # noqa: E402
import collect_players as cp  # noqa: E402
import player_store  # noqa: E402
from player_names import NameResolver  # noqa: E402

T1, T2, T3 = 1610612737, 1610612738, 1610612739


class MinutesTests(unittest.TestCase):
    def test_parse_minutes(self):
        self.assertEqual(cp.parse_minutes("34:12"), 34.2)
        self.assertEqual(cp.parse_minutes("PT34M12.00S"), 34.2)
        self.assertEqual(cp.parse_minutes("PT05M"), 5.0)
        self.assertEqual(cp.parse_minutes(28), 28.0)
        self.assertEqual(cp.parse_minutes(28.5), 28.5)
        self.assertEqual(cp.parse_minutes("31"), 31.0)
        self.assertIsNone(cp.parse_minutes(""))
        self.assertIsNone(cp.parse_minutes(None))
        self.assertIsNone(cp.parse_minutes(float("nan")))
        self.assertIsNone(cp.parse_minutes("DNP"))

    def test_seasons_through(self):
        self.assertEqual(cp.seasons_through(date(2026, 10, 10))[0], "2019-20")
        self.assertEqual(cp.seasons_through(date(2026, 10, 10))[-1], "2026-27")
        self.assertEqual(cp.seasons_through(date(2026, 4, 1))[-1], "2025-26")


def gamelog_frame():
    return pd.DataFrame([
        {"GAME_ID": "0022500001", "PLAYER_ID": 1, "TEAM_ID": T1, "GAME_DATE": "2025-10-21",
         "MATCHUP": "ATL vs. BOS", "MIN": 34, "PTS": 20, "REB": 5, "OREB": 1, "DREB": 4, "AST": 3, "STL": 1,
         "BLK": 0, "TOV": 2, "PF": 3, "FGM": 8, "FGA": 15, "FG3M": 2, "FG3A": 5, "FTM": 2, "FTA": 2,
         "PLUS_MINUS": 7},
        {"GAME_ID": "0022500001", "PLAYER_ID": 2, "TEAM_ID": T2, "GAME_DATE": "2025-10-21",
         "MATCHUP": "BOS @ ATL", "MIN": "12:30", "PTS": 4, "REB": None, "OREB": 0, "DREB": 0, "AST": 0, "STL": 0,
         "BLK": 0, "TOV": 0, "PF": 1, "FGM": 2, "FGA": 3, "FG3M": 0, "FG3A": 1, "FTM": 0, "FTA": 0,
         "PLUS_MINUS": -7},
    ])


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_rows_keep_zero_padded_ids_and_home_flag(self):
        rows = cp.gamelog_to_rows(gamelog_frame(), "2025-26")
        self.assertEqual(rows[0]["game_id"], "0022500001")
        self.assertEqual((rows[0]["is_home"], rows[1]["is_home"]), (1, 0))
        self.assertEqual(rows[1]["minutes"], 12.5)
        self.assertIsNone(rows[1]["reb"])
        player_store.upsert("player_games", rows, conn=self.conn)
        stored = player_store.read("player_games", order_by="player_id", conn=self.conn)
        self.assertEqual(stored["game_id"].tolist(), ["0022500001", "0022500001"])
        rows_int = cp.gamelog_to_rows(gamelog_frame().assign(GAME_ID=[22500001, 22500001]), "2025-26")
        self.assertEqual(rows_int[0]["game_id"], "0022500001")

    def test_upsert_is_idempotent(self):
        rows = cp.gamelog_to_rows(gamelog_frame(), "2025-26")
        player_store.upsert("player_games", rows, conn=self.conn)
        player_store.upsert("player_games", rows, conn=self.conn)
        self.assertEqual(player_store.count("player_games", conn=self.conn), 2)
        changed = [dict(rows[0], pts=99)]
        player_store.upsert("player_games", changed, conn=self.conn)
        self.assertEqual(player_store.count("player_games", conn=self.conn), 2)
        self.assertEqual(player_store.read("player_games", filters=[("player_id", "eq", 1)],
                                           conn=self.conn)["pts"].iloc[0], 99)

    def test_players_and_aliases(self):
        df = pd.DataFrame([
            {"PERSON_ID": 10, "DISPLAY_FIRST_LAST": "Chris Johnson", "DISPLAY_LAST_COMMA_FIRST": "Johnson, Chris",
             "ROSTERSTATUS": 0, "TO_YEAR": "2012"},
            {"PERSON_ID": 11, "DISPLAY_FIRST_LAST": "Chris Johnson", "DISPLAY_LAST_COMMA_FIRST": "Johnson, Chris",
             "ROSTERSTATUS": 0, "TO_YEAR": "2016"},
            {"PERSON_ID": 12, "DISPLAY_FIRST_LAST": "Nikola Jokić", "DISPLAY_LAST_COMMA_FIRST": "Jokić, Nikola",
             "ROSTERSTATUS": 1, "TO_YEAR": "2026"},
        ])
        players, aliases = cp.players_from_common_all(df)
        self.assertEqual(len(players), 3)
        alias = {(a["provider"], a["provider_name"]): a["player_id"] for a in aliases}
        self.assertEqual(alias[("nba_api", "Chris Johnson")], 11)        # most recent wins the clash
        self.assertEqual(alias[("normalized", "nikola jokic")], 12)
        jokic = next(p for p in players if p["player_id"] == 12)
        self.assertEqual((jokic["first_name"], jokic["last_name"], jokic["is_active"]), ("Nikola", "Jokić", 1))
        player_store.upsert("players", players, conn=self.conn)
        player_store.upsert("player_aliases", aliases, conn=self.conn)
        cp.record_alias("nba_injury_report", "Jokic, Nikola Jr.", 12, conn=self.conn)
        resolver = NameResolver.from_rows(cp.resolver_rows(conn=self.conn))
        self.assertEqual(resolver.resolve("Jokic, Nikola").player_id, 12)


def team_games(team, season, start, n, opponent=T3, prefix="00225"):
    """n consecutive game dates for a team (one game every 2 days)."""
    return [(f"{prefix}{team % 1000:03d}{i:02d}", (start + timedelta(days=2 * i)).isoformat(), season)
            for i in range(n)]


def pg_rows(games, team, players_minutes):
    """players_minutes: {player_id: [minutes or None per game]}"""
    rows = []
    for idx, (gid, gdate, season) in enumerate(games):
        for pid, mins in players_minutes.items():
            if idx < len(mins) and mins[idx] is not None:
                rows.append({"game_id": gid, "player_id": pid, "team_id": team, "game_date": gdate,
                             "season": season, "minutes": mins[idx]})
    return rows


class AbsenceTests(unittest.TestCase):
    def setUp(self):
        start = date(2025, 10, 21)
        self.g1 = team_games(T1, "2025-26", start, 14)
        filler = {900 + k: [20] * 14 for k in range(5)}
        star = [30] * 12 + [None] + [30]          # star misses game 13 (index 12)
        bench = [5] * 12 + [None, 5]              # bench player also misses game 13
        traded = [28] * 8 + [None] * 6            # traded after game 8
        rows = pg_rows(self.g1, T1, {1: star, 2: bench, 3: traded, **filler})
        g2 = team_games(T2, "2025-26", start + timedelta(days=17), 5)
        rows += pg_rows(g2, T2, {3: [25] * 5})    # player 3 plays for T2 from day 17
        self.pg = pd.DataFrame(rows)

    def test_star_absent_bench_not_traded_not(self):
        out = absences.infer_absences(self.pg)
        keyed = {(r["game_id"], r["player_id"]): r for r in out.to_dict("records")}
        missed_gid = self.g1[12][0]
        self.assertIn((missed_gid, 1), keyed)
        self.assertEqual(keyed[(missed_gid, 1)]["basis"], "inferred")
        self.assertEqual(keyed[(missed_gid, 1)]["typical_minutes"], 30.0)
        self.assertEqual(keyed[(missed_gid, 1)]["team_id"], T1)
        self.assertNotIn((missed_gid, 2), keyed)                          # 5-minute bench player
        self.assertTrue(any(pid == 3 for (_g, pid) in keyed))            # no future roster data is consulted
        self.assertEqual(len(out), 2)
        self.assertTrue(all(len(g) == 10 for g, _ in keyed))

    def test_future_trade_rows_do_not_change_point_in_time_labels(self):
        before_trade = self.pg[self.pg["game_date"] < "2025-11-07"].copy()
        first = absences.infer_absences(before_trade)
        second = absences.infer_absences(self.pg)
        key = lambda df: {(r["game_id"], r["player_id"]) for r in df.to_dict("records")}
        self.assertTrue(key(first).issubset(key(second)))

    def test_long_absence_spell_stays_flagged(self):
        games = team_games(T1, "2025-26", date(2025, 10, 21), 30)
        star = [30] * 10 + [None] * 15 + [30] * 5          # out for 15 straight games
        rows = pg_rows(games, T1, {1: star, **{900 + k: [20] * 30 for k in range(5)}})
        out = absences.infer_absences(pd.DataFrame(rows))
        flagged = sorted(out[out["player_id"] == 1]["game_id"])
        self.assertEqual(flagged, sorted(g for g, _d, _s in games[10:25]))
        self.assertTrue((out["typical_minutes"] == 30.0).all())

    def test_needs_five_appearances(self):
        rows = pg_rows(self.g1[:5], T1, {1: [30, 30, 30, 30, None], **{900 + k: [20] * 5 for k in range(5)}})
        self.assertTrue(absences.infer_absences(pd.DataFrame(rows)).empty)    # only 4 prior appearances

    def test_not_carried_across_seasons(self):
        prev = team_games(T1, "2024-25", date(2025, 3, 1), 10, prefix="00224")
        nxt = team_games(T1, "2025-26", date(2025, 10, 21), 3)
        rows = pg_rows(prev, T1, {1: [30] * 10, 900: [20] * 10}) + pg_rows(nxt, T1, {1: [None, 30, 30], 900: [20] * 3})
        self.assertTrue(absences.infer_absences(pd.DataFrame(rows)).empty)

    def test_rebuild_is_idempotent(self):
        conn = sqlite3.connect(":memory:")
        player_store.upsert("player_games", self.pg.assign(is_home=1, started=None).to_dict("records"), conn=conn)
        self.assertEqual(absences.rebuild(conn=conn), 2)
        absences.rebuild(conn=conn)
        self.assertEqual(player_store.count("player_absences", conn=conn), 2)
        self.assertIn(self.g1[12][0], player_store.read("player_absences", conn=conn)["game_id"].tolist())
        conn.close()


if __name__ == "__main__":
    unittest.main()
