"""Phase 2: injury snapshot ingestion (offline: fixtures and fakes, no network)."""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
import injuries  # noqa: E402
import injury_report_pdf as irp  # noqa: E402
from nba_client import frames_from_json, frames_to_json, season_for_date  # noqa: E402
from player_names import Candidate, NameResolver, normalize_name  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "injury_reports")
try:
    import pdfplumber  # noqa: F401

    HAVE_PDFPLUMBER = True
except ImportError:  # pragma: no cover
    HAVE_PDFPLUMBER = False

ATL, CLE, DEN, NOP, BKN, CHA = 1610612737, 1610612739, 1610612743, 1610612740, 1610612751, 1610612766


def w(text, x0, top):
    return {"text": text, "x0": float(x0), "x1": float(x0) + 5 * len(text), "top": float(top),
            "bottom": float(top) + 8}


HEADER = [w("Game", 23, 100), w("Date", 53, 100), w("Game", 119, 100), w("Time", 149, 100),
          w("Matchup", 200, 100), w("Team", 264, 100), w("Player", 425, 100), w("Name", 457, 100),
          w("Current", 585, 100), w("Status", 624, 100), w("Reason", 666, 100)]
TITLE = [w("Injury", 289, 45), w("Report:", 355, 45), w("10/21/26", 438, 45), w("05:00", 539, 45), w("PM", 602, 45)]


def fake_matchers(schedule_rows=None):
    resolver = NameResolver([
        Candidate("Nikola Jokić", 203999, DEN),
        Candidate("Jarrett Allen", 1628386, CLE),
        Candidate("Wendell Moore Jr.", 1631111, CLE),
        Candidate("Trae Young", 1629027, ATL),
    ])
    by_nick, by_tri = injuries.team_lookup()
    rows = schedule_rows if schedule_rows is not None else [
        {"game_id": "0022600001", "game_date": "2026-10-21", "home_team_id": ATL, "away_team_id": CLE},
    ]
    return injuries.Matchers(resolver, by_nick, by_tri,
                             schedule_loader=lambda season: pd.DataFrame(rows))


def parsed_report(report_et, players):
    """players: list of (team, player, status, reason)."""
    rep = irp.ParsedReport(report_time_et=report_et)
    for team, player, status, reason in players:
        rep.rows.append({"game_date": "10/21/2026", "game_time": "07:30 (ET)", "matchup": "CLE@ATL",
                         "team": team, "player": player, "status": status, "reason": reason})
    return rep


class StatusNormalizationTests(unittest.TestCase):
    def test_status_table(self):
        cases = {
            "Out": "out", "OUT": "out", "Out for season": "out", "Out For Season": "out",
            "Doubtful": "doubtful", "Questionable": "questionable", "GTD": "questionable",
            "Game Time Decision": "questionable", "Day-To-Day": "questionable", "day to day": "questionable",
            "Probable": "probable", "Available": "available", "  questionable  ": "questionable",
            "Out (Season)": "out",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                status, known = injuries.normalize_status(raw)
                self.assertEqual(status, expected)
                self.assertTrue(known)

    def test_unknown_status_falls_back_and_is_flagged(self):
        status, known = injuries.normalize_status("Expected to sit")
        self.assertEqual(status, config.INJURY_STATUS_FALLBACK)
        self.assertFalse(known)

    def test_every_mapped_status_is_valid(self):
        self.assertTrue(set(config.INJURY_STATUS_MAP.values()) <= set(config.INJURY_STATUSES))
        for status in config.INJURY_STATUSES:
            self.assertIn(status, config.STATUS_TO_P_PLAY)


class NameMatchingTests(unittest.TestCase):
    def test_normalizer(self):
        self.assertEqual(normalize_name("Jokić, Nikola"), "nikola jokic")
        self.assertEqual(normalize_name("Moore Jr., Wendell"), "wendell moore")
        self.assertEqual(normalize_name("Wendell Moore Jr."), "wendell moore")
        self.assertEqual(normalize_name("Gary Payton II"), "gary payton")
        self.assertEqual(normalize_name("Payton II, Gary"), "gary payton")
        self.assertEqual(normalize_name("Warren, T.J."), "tj warren")
        self.assertEqual(normalize_name("Hunter, De'Andre"), "deandre hunter")
        self.assertEqual(normalize_name("Jonas Valančiūnas"), "jonas valanciunas")
        self.assertEqual(normalize_name("Jackson-Davis, Trayce"), "trayce jackson davis")
        self.assertEqual(normalize_name("Kristaps Porziņģis"), "kristaps porzingis")
        self.assertEqual(normalize_name(None), "")

    def test_resolver_suffixes_accents_and_teams(self):
        r = NameResolver([
            Candidate("Nikola Jokić", 1, DEN),
            Candidate("Wendell Moore Jr.", 2, CLE),
            Candidate("Marcus Morris Sr.", 3, CLE),
            Candidate("Jalen Williams", 4, 1610612760),
            Candidate("Jaylin Williams", 5, 1610612760),
            Candidate("Kevin Martin", 6, ATL, is_active=False),
            Candidate("Kevin Martin", 7, NOP, is_active=True),
        ])
        self.assertEqual(r.resolve("Jokic, Nikola").player_id, 1)
        self.assertEqual(r.resolve("Moore, Wendell").player_id, 2)
        self.assertEqual(r.resolve("Moore Jr., Wendell").player_id, 2)
        self.assertEqual(r.resolve("Morris, Marcus").player_id, 3)
        self.assertEqual(r.resolve("Williams, Jalen").player_id, 4)
        self.assertEqual(r.resolve("Martin, Kevin", ATL).player_id, 6)     # team breaks the tie
        self.assertEqual(r.resolve("Martin, Kevin").player_id, 7)          # else the active player
        self.assertIsNone(r.resolve("Nobody, Some").player_id)
        self.assertEqual(r.resolve("Nobody, Some").method, "unmatched")

    def test_initial_and_team_fallback(self):
        r = NameResolver([Candidate("Nicolas Claxton", 9, BKN)])
        self.assertEqual(r.resolve("Claxton, Nic", BKN).player_id, 9)
        self.assertIsNone(r.resolve("Claxton, Nic", ATL).player_id)

    def test_team_name_resolution_prefers_longest_nickname(self):
        by_nick, _ = injuries.team_lookup()
        self.assertEqual(injuries.resolve_team("Charlotte Hornets", by_nick), CHA)
        self.assertEqual(injuries.resolve_team("Brooklyn Nets", by_nick), BKN)
        self.assertEqual(injuries.resolve_team("LA Clippers", by_nick), 1610612746)
        self.assertEqual(injuries.resolve_team("Portland Trail Blazers", by_nick), 1610612757)
        self.assertIsNone(injuries.resolve_team("Seattle Supersonics", by_nick))


class ParserTests(unittest.TestCase):
    def test_wrapped_reason_carry_forward_and_page_break(self):
        page1 = TITLE + HEADER + [
            w("Injury/Illness", 667, 129), w("-", 721, 129), w("Right", 727, 129), w("Knee;", 750, 129),
            w("10/21/2026", 24, 136), w("07:30", 120, 136), w("(ET)", 145, 136), w("CLE@ATL", 201, 136),
            w("Cleveland", 265, 136), w("Cavaliers", 307, 136), w("Allen,", 426, 136), w("Jarrett", 451, 136),
            w("Out", 586, 136), w("Sprain", 667, 143),
            w("Moore", 426, 165), w("Jr.,", 455, 165), w("Wendell", 470, 165), w("Questionable", 586, 165),
            w("Illness", 667, 165),
            w("Page", 400, 570), w("1", 420, 570), w("of", 425, 570), w("2", 435, 570),
        ]
        page2 = TITLE + [
            w("Atlanta", 265, 120), w("Hawks", 297, 120), w("Young,", 426, 120), w("Trae", 455, 120),
            w("Probable", 586, 120), w("Rest", 667, 120),
            w("10/21/2026", 24, 150), w("10:00", 120, 150), w("(ET)", 145, 150), w("DEN@LAL", 201, 150),
            w("Denver", 265, 150), w("Nuggets", 297, 150), w("NOT", 667, 150), w("YET", 690, 150),
            w("SUBMITTED", 710, 150),
        ]
        rep = irp.parse_pages([page1, page2])
        self.assertEqual(rep.report_time_et, datetime(2026, 10, 21, 17, 0))
        self.assertEqual([r["player"] for r in rep.rows], ["Allen, Jarrett", "Moore Jr., Wendell", "Young, Trae"])
        allen, moore, young = rep.rows
        self.assertEqual(allen["reason"], "Injury/Illness - Right Knee; Sprain")
        self.assertEqual(moore["matchup"], "CLE@ATL")
        self.assertEqual(moore["team"], "Cleveland Cavaliers")
        self.assertEqual(young["team"], "Atlanta Hawks")             # carried across the page break
        self.assertEqual(young["game_time"], "07:30 (ET)")
        self.assertEqual(rep.not_submitted, [{"game_date": "10/21/2026", "game_time": "10:00 (ET)",
                                              "matchup": "DEN@LAL", "team": "Denver Nuggets"}])

    def test_missing_header_raises(self):
        with self.assertRaises(irp.InjuryReportParseError):
            irp.parse_pages([[w("hello", 10, 10)]])

    def test_slot_names_both_eras(self):
        self.assertEqual(irp.slot_names(datetime(2025, 1, 15, 17, 0)), ["2025-01-15_05PM"])
        self.assertEqual(irp.slot_names(datetime(2025, 1, 15, 17, 15)), [])
        self.assertEqual(irp.slot_names(datetime(2026, 4, 10, 17, 15)), ["2026-04-10_05_15PM"])
        self.assertEqual(irp.slot_names(datetime(2026, 10, 21, 0, 45)), ["2026-10-21_12_45AM"])
        self.assertEqual(irp.slot_names(datetime(2026, 10, 21, 12, 0)), ["2026-10-21_12_00PM"])
        self.assertEqual(set(irp.slot_names(datetime(2025, 12, 22, 17, 0))),
                         {"2025-12-22_05_00PM", "2025-12-22_05PM"})          # switch window: try both
        self.assertEqual(irp.slot_time_from_name("2026-04-10_05_15PM"), datetime(2026, 4, 10, 17, 15))
        self.assertEqual(irp.slot_time_from_name("2021-12-01_05PM"), datetime(2021, 12, 1, 17, 0))

    @unittest.skipUnless(HAVE_PDFPLUMBER, "pdfplumber not installed")
    def test_real_report_15_minute_layout(self):
        rep = irp.parse_pdf(os.path.join(FIXTURES, "Injury-Report_2026-04-10_05_00PM.pdf"))
        self.assertEqual(rep.report_time_et, datetime(2026, 4, 10, 17, 0))
        self.assertEqual(len(rep.rows), 206)
        self.assertEqual(rep.warnings, [])
        first = rep.rows[0]
        self.assertEqual((first["matchup"], first["team"], first["player"], first["status"]),
                         ("CLE@ATL", "Cleveland Cavaliers", "Allen, Jarrett", "Out"))
        self.assertEqual(first["reason"], "Injury/Illness - Right Knee; Injury Management")
        tyson = next(r for r in rep.rows if r["player"] == "Tyson, Jaylon")
        self.assertEqual(tyson["reason"], "Injury/Illness - Left Great Toe; Bone Bruise")
        self.assertEqual(len({r["team"] for r in rep.rows}), 30)

    @unittest.skipUnless(HAVE_PDFPLUMBER, "pdfplumber not installed")
    def test_real_report_hourly_layout(self):
        rep = irp.parse_pdf(os.path.join(FIXTURES, "Injury-Report_2021-12-01_05PM.pdf"))
        self.assertEqual(rep.report_time_et, datetime(2021, 12, 1, 17, 30))   # header beats the slot name
        self.assertEqual(len(rep.rows), 102)
        self.assertEqual(len(rep.not_submitted), 6)
        hunter = next(r for r in rep.rows if r["player"] == "Hunter, De'Andre")
        self.assertEqual(hunter["reason"], "Injury/Illness - Right Wrist; Tendon Surgery")


class SinkTests(unittest.TestCase):
    def setUp(self):
        self.conn = injuries.connect(":memory:")

    def ingest(self, rep):
        rows, unmatched, unknown = injuries.build_rows(
            rep, raw_file="x.pdf", captured_at=datetime(2026, 10, 21, 22, tzinfo=timezone.utc),
            matchers=self.matchers)
        return injuries.store_rows(self.conn, rows, unmatched), rows, unmatched, unknown

    def setUpMatchers(self):
        self.matchers = fake_matchers()

    def test_build_rows_matches_and_keeps_zero_padded_game_id(self):
        self.setUpMatchers()
        rep = parsed_report(datetime(2026, 10, 21, 13, 0), [
            ("Cleveland Cavaliers", "Allen, Jarrett", "Out", "Knee"),
            ("Cleveland Cavaliers", "Moore Jr., Wendell", "GTD", None),
            ("Atlanta Hawks", "Unknown, Guy", "Mystery", None),
        ])
        inserted, rows, unmatched, unknown = self.ingest(rep)
        self.assertEqual(inserted, 3)
        self.assertEqual(rows[0]["game_id"], "0022600001")
        self.assertEqual(rows[0]["report_time"], "2026-10-21T17:00:00+00:00")   # 1 PM EDT
        self.assertEqual(rows[0]["player_id"], 1628386)
        self.assertEqual(rows[1]["player_id"], 1631111)
        self.assertEqual(rows[1]["status"], "questionable")
        self.assertEqual(unknown, ["Mystery"])
        self.assertEqual([u["player_name_raw"] for u in unmatched if u["kind"] == "player"], ["Unknown, Guy"])
        stored = self.conn.execute("select game_id from injury_snapshots").fetchall()
        self.assertTrue(all(r[0] == "0022600001" for r in stored))

    def test_store_is_idempotent_per_report_time(self):
        self.setUpMatchers()
        rep = parsed_report(datetime(2026, 10, 21, 13, 0), [("Cleveland Cavaliers", "Allen, Jarrett", "Out", None)])
        self.assertEqual(self.ingest(rep)[0], 1)
        self.assertEqual(self.ingest(rep)[0], 0)
        self.assertEqual(self.conn.execute("select count(*) from injury_snapshots").fetchone()[0], 1)

    def test_unmatched_report_file(self):
        self.setUpMatchers()
        rep = parsed_report(datetime(2026, 10, 21, 13, 0), [("Atlanta Hawks", "Unknown, Guy", "Out", None)])
        self.ingest(rep)
        with tempfile.TemporaryDirectory() as tmp:
            path = injuries.write_unmatched_report(self.conn, os.path.join(tmp, "u.csv"))
            text = open(path, encoding="utf-8").read()
        self.assertIn("Unknown, Guy", text)
        self.assertIn("player", text)


class LatestStatusTests(unittest.TestCase):
    def setUp(self):
        self.conn = injuries.connect(":memory:")
        self.matchers = fake_matchers()
        for report_et, players in [
            (datetime(2026, 10, 21, 13, 0), [("Cleveland Cavaliers", "Allen, Jarrett", "Questionable", None),
                                              ("Cleveland Cavaliers", "Moore Jr., Wendell", "Out", None),
                                              ("Atlanta Hawks", "Young, Trae", "Probable", None)]),
            (datetime(2026, 10, 21, 17, 0), [("Cleveland Cavaliers", "Allen, Jarrett", "Out", None)]),
        ]:
            rows, unmatched, _ = injuries.build_rows(
                parsed_report(report_et, players), raw_file="x.pdf",
                captured_at=datetime(2026, 10, 21, 23, tzinfo=timezone.utc), matchers=self.matchers)
            injuries.store_rows(self.conn, rows, unmatched)

    def status_of(self, as_of):
        df = injuries.latest_status("22600001", as_of, conn=self.conn)
        return dict(zip(df["player_name_raw"], df["status"])) if not df.empty else {}

    def test_later_snapshot_does_not_leak_into_earlier_as_of(self):
        self.assertEqual(self.status_of("2026-10-21T15:00:00-04:00"),
                         {"Allen, Jarrett": "questionable", "Moore Jr., Wendell": "out", "Young, Trae": "probable"})

    def test_newest_row_wins_after_later_report(self):
        after = self.status_of("2026-10-21T18:00:00-04:00")
        self.assertEqual(after["Allen, Jarrett"], "out")
        self.assertNotIn("Moore Jr., Wendell", after)           # dropped from the newer CLE report
        self.assertEqual(after["Young, Trae"], "probable")       # ATL not re-listed: last listing stands

    def test_boundary_is_inclusive_and_nothing_before_first_report(self):
        self.assertEqual(self.status_of("2026-10-21T17:00:00-04:00")["Allen, Jarrett"], "out")
        self.assertEqual(self.status_of("2026-10-21T16:59:59-04:00")["Allen, Jarrett"], "questionable")
        self.assertEqual(self.status_of("2026-10-21T12:59:00-04:00"), {})

    def test_naive_as_of_is_eastern(self):
        self.assertEqual(self.status_of("2026-10-21T16:59:59")["Allen, Jarrett"], "questionable")
        self.assertEqual(self.status_of(datetime(2026, 10, 21, 21, 0, tzinfo=timezone.utc))["Allen, Jarrett"], "out")


class BackendSelectionTests(unittest.TestCase):
    def test_player_store_supabase_mode_selects_remote_snapshots_by_default(self):
        with patch.dict(os.environ, {"NBA_PLAYER_STORE": "supabase"}):
            with patch("database.select_rows", return_value=pd.DataFrame()) as select:
                injuries.latest_status("0022600001", datetime(2026, 10, 21, tzinfo=timezone.utc))
        select.assert_called_once()


class FakeResponse:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class FakeSession:
    def __init__(self, available):
        self.available, self.calls = available, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        slot = url.rsplit("Injury-Report_", 1)[1][:-4]
        if slot in self.available:
            with open(self.available[slot], "rb") as fh:
                return FakeResponse(200, fh.read())
        return FakeResponse(403, b"<html>denied</html>")


@unittest.skipUnless(HAVE_PDFPLUMBER, "pdfplumber not installed")
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = os.path.join(self.tmp.name, "raw")
        self.conn = injuries.connect(os.path.join(self.tmp.name, "sink.sqlite"))
        p = patch.object(config, "INJURY_RAW_DIR", self.raw)
        p.start()
        self.addCleanup(p.stop)
        q = patch.object(config, "INJURY_HTTP_MIN_INTERVAL_SECONDS", 0)
        q.start()
        self.addCleanup(q.stop)
        self.matchers = fake_matchers(schedule_rows=[])

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_snapshot_archives_pdf_and_is_idempotent(self):
        session = FakeSession({"2026-04-10_05_00PM": os.path.join(FIXTURES, "Injury-Report_2026-04-10_05_00PM.pdf")})
        now = datetime(2026, 4, 10, 17, 20, tzinfo=injuries.ET)
        first = injuries.snapshot(now=now, conn=self.conn, matchers=self.matchers, session=session,
                                  lookback_hours=1)
        self.assertEqual(first["slots"], {"missing": 1, "fetched": 1})     # 05:15 missing, 05:00 found
        self.assertTrue(os.path.exists(os.path.join(self.raw, "Injury-Report_2026-04-10_05_00PM.pdf")))
        n = self.conn.execute("select count(*) from injury_snapshots").fetchone()[0]
        self.assertEqual(n, 206)
        second = injuries.snapshot(now=now, conn=self.conn, matchers=self.matchers, session=session,
                                   lookback_hours=1)
        self.assertEqual(second["ingested"], [])
        self.assertEqual(self.conn.execute("select count(*) from injury_snapshots").fetchone()[0], n)
        # reparse of the archive adds nothing either
        injuries.reparse(conn=self.conn, matchers=self.matchers, raw_dir=self.raw)
        self.assertEqual(self.conn.execute("select count(*) from injury_snapshots").fetchone()[0], n)

    def test_cli_snapshot_never_fails_the_pipeline(self):
        with patch.object(injuries, "snapshot", side_effect=RuntimeError("boom")):
            self.assertEqual(injuries.main(["--snapshot", "--db", os.path.join(self.tmp.name, "s2.sqlite")]), 0)
            self.assertEqual(injuries.main(["--snapshot", "--strict",
                                            "--db", os.path.join(self.tmp.name, "s2.sqlite")]), 1)

    def test_backfill_remembers_misses_and_skips_cached(self):
        session = FakeSession({"2021-12-01_05PM": os.path.join(FIXTURES, "Injury-Report_2021-12-01_05PM.pdf")})
        counts = injuries.backfill(date(2021, 11, 30), date(2021, 12, 1), conn=self.conn,
                                   matchers=self.matchers, session=session)
        self.assertEqual((counts["fetched"], counts["missing"], counts["ingested"]), (1, 1, 1))
        again = injuries.backfill(date(2021, 11, 30), date(2021, 12, 1), conn=self.conn,
                                  matchers=self.matchers, session=session)
        self.assertEqual((again["known_missing"], again["cached"], again["ingested"]), (1, 1, 0))
        self.assertEqual(len(session.calls), 2)


class PushAndCacheTests(unittest.TestCase):
    def test_push_dry_run_writes_nothing_and_real_push_ignores_duplicates(self):
        conn = injuries.connect(":memory:")
        rows, unmatched, _ = injuries.build_rows(
            parsed_report(datetime(2026, 10, 21, 13, 0), [("Cleveland Cavaliers", "Allen, Jarrett", "Out", None)]),
            raw_file="x.pdf", captured_at=datetime(2026, 10, 21, 22, tzinfo=timezone.utc), matchers=fake_matchers())
        injuries.store_rows(conn, rows, unmatched)
        with patch("database.upsert_rows") as upsert:
            self.assertEqual(injuries.push_to_supabase(conn=conn, dry_run=True), 0)
            upsert.assert_not_called()
            self.assertEqual(injuries.push_to_supabase(conn=conn, dry_run=False), 1)
            _, kwargs = upsert.call_args
            self.assertEqual(kwargs["conflict_columns"], injuries.CONFLICT_COLUMNS)
            self.assertTrue(kwargs["ignore_duplicates"])
            pushed = upsert.call_args[0][1][0]
            self.assertEqual(pushed["game_id"], "0022600001")
            self.assertNotIn("snapshot_id", pushed)

    def test_frame_cache_roundtrip_keeps_zero_padded_ids(self):
        df = pd.DataFrame({"GAME_ID": ["0022500001", "0022500002"], "PLAYER_ID": [1, 2], "MIN": [34, None]})
        back = frames_from_json(frames_to_json([df]))[0]
        self.assertEqual(back["GAME_ID"].tolist(), ["0022500001", "0022500002"])
        self.assertEqual(back["PLAYER_ID"].tolist(), [1, 2])

    def test_season_for_date(self):
        self.assertEqual(season_for_date(date(2026, 10, 21)), "2026-27")
        self.assertEqual(season_for_date(date(2026, 4, 12)), "2025-26")


if __name__ == "__main__":
    unittest.main()


class LaterFixesTests(unittest.TestCase):
    def test_2019_layout_with_category_column(self):
        header = [w("Game", 21, 58), w("Date", 40, 58), w("Game", 73, 58), w("Time", 92, 58),
                  w("Matchup", 126, 58), w("Team", 179, 58), w("Player", 269, 58), w("Name", 290, 58),
                  w("Category", 382, 58), w("Reason", 495, 58), w("Current", 607, 58), w("Status", 630, 58),
                  w("Previous", 720, 58), w("Status", 745, 58)]
        title = [w("Injury", 314, 11), w("Report:", 340, 11), w("10/22/19", 370, 11), w("05:30", 410, 11),
                 w("PM", 440, 11)]
        rows = [w("10/22/2019", 20, 77), w("08:00", 72, 77), w("(ET)", 95, 77), w("NOP@TOR", 125, 77),
                w("New", 178, 77), w("Orleans", 195, 77), w("Pelicans", 225, 77), w("Miller,", 268, 77),
                w("Darius", 300, 77), w("Injury/Illness", 381, 77), w("Right", 494, 77), w("Achilles", 515, 77),
                w("Surgery", 545, 77), w("Out", 606, 77), w("-", 719, 77),
                w("Gray,", 268, 95), w("Josh", 290, 95), w("G", 381, 95), w("League", 388, 95), w("-", 420, 95),
                w("Two-Way", 428, 95), w("-", 494, 95), w("Out", 606, 95), w("-", 719, 95)]
        rep = irp.parse_pages([title + header + rows])
        self.assertEqual(rep.report_time_et, datetime(2019, 10, 22, 17, 30))
        self.assertEqual([(r["player"], r["status"], r["reason"]) for r in rep.rows], [
            ("Miller, Darius", "Out", "Injury/Illness - Right Achilles Surgery"),
            ("Gray, Josh", "Out", "G League - Two-Way")])

    def test_overrides_and_rematch_fill_only_missing_keys(self):
        conn = injuries.connect(":memory:")
        m = fake_matchers()
        m.resolver.overrides = {}
        rows, unmatched, _ = injuries.build_rows(
            parsed_report(datetime(2026, 10, 21, 13, 0), [("Cleveland Cavaliers", "Allen, Bob", "Out", None),
                                                          ("Atlanta Hawks", "Young, Trae", "Out", None)]),
            raw_file="x.pdf", captured_at=datetime(2026, 10, 21, 22, tzinfo=timezone.utc), matchers=m)
        injuries.store_rows(conn, rows, unmatched)
        self.assertIsNone(conn.execute("select player_id from injury_snapshots where player_name_raw = 'Allen, Bob'")
                          .fetchone()[0])
        m.resolver.overrides = {"bob allen": 1628386}
        with tempfile.TemporaryDirectory() as tmp, patch.object(injuries, "_unmatched_path_for",
                                                                return_value=os.path.join(tmp, "u.csv")):
            filled = injuries.rematch(conn=conn, matchers=m)
        self.assertEqual(filled, {"player_id": 1, "game_id": 0})
        got = dict(conn.execute("select player_name_raw, player_id from injury_snapshots").fetchall())
        self.assertEqual(got, {"Allen, Bob": 1628386, "Young, Trae": 1629027})
        self.assertEqual(conn.execute("select count(*) from injury_unmatched where kind='player'").fetchone()[0], 0)
        self.assertEqual(conn.execute("select status from injury_snapshots where player_name_raw='Allen, Bob'")
                         .fetchone()[0], "out")

    def test_override_wins(self):
        r = NameResolver([Candidate("Nic Claxton", 1629651, BKN)], overrides={"nicolas claxton": 1629651})
        self.assertEqual(r.resolve("Claxton, Nicolas").method, "override")
        self.assertEqual(r.resolve("Claxton, Nicolas").player_id, 1629651)
