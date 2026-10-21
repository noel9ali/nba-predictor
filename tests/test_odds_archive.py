"""Odds archive: every response is stored (all books, commence_time, quota headers), append-only and idempotent, never
fatal; closing-line capture is OFF by default and, when on, spends one call per due tip time within its budget."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import odds
import odds_archive
import predict


def _event(eid="e1", home="Atlanta Hawks", away="Boston Celtics", commence="2026-10-21T23:30:00Z",
           hprice=-150, aprice=130, books=("DraftKings", "FanDuel", "Bovada")):
    return {"id": eid, "commence_time": commence, "home_team": home, "away_team": away,
            "bookmakers": [{"key": b.lower(), "title": b, "last_update": "2026-10-21T22:00:00Z",
                            "markets": [{"key": "h2h", "last_update": "2026-10-21T22:00:05Z", "outcomes": [
                                {"name": home, "price": hprice}, {"name": away, "price": aprice}]}]} for b in books]}


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self.status_code, self._p, self.text = status, payload, ""
        self.headers = headers if headers is not None else {"x-requests-remaining": "480", "x-requests-used": "20",
                                                            "x-requests-last": "1"}

    def json(self):
        return self._p


class ArchiveBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "odds_history", "odds_history.sqlite")   # directory made on first use
        self.env = patch.dict(os.environ, {"NBA_ODDS_HISTORY_DB": self.db})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def rows(self, sql):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()


class ArchiveStorageTests(ArchiveBase):
    def test_every_bookmaker_commence_time_and_headers_are_kept(self):
        res = odds_archive.archive_response([_event()], {"x-requests-remaining": "480", "x-requests-used": "20"},
                                            "2026-10-21T22:50:00.123Z", purpose="pricing", sport="basketball_nba")
        self.assertEqual(res["rows"], 6)                                  # 3 books x 2 sides, not just preferred books
        self.assertTrue(os.path.isdir(os.path.dirname(self.db)))
        rows = self.rows("select bookmaker_title, selection, price_american, commence_time, home_team, away_team, "
                         "nba_game_id, market from odds_snapshots order by bookmaker_title, selection")
        self.assertIn(("Bovada", "away", 130, "2026-10-21T23:30:00Z", "Atlanta Hawks", "Boston Celtics", None, "h2h"), rows)
        self.assertIn(("DraftKings", "home", -150, "2026-10-21T23:30:00Z", "Atlanta Hawks", "Boston Celtics", None, "h2h"), rows)
        call = self.rows("select captured_at, purpose, http_status, n_events, requests_remaining, requests_used "
                         "from odds_calls")
        self.assertEqual(call, [("2026-10-21T22:50:00.123Z", "pricing", 200, 1, 480, 20)])

    def test_same_response_twice_is_a_no_op_and_a_later_call_is_a_new_time_series_row(self):
        stamp = "2026-10-21T22:50:00.123Z"
        odds_archive.archive_response([_event()], {}, stamp)
        again = odds_archive.archive_response([_event()], {}, stamp)
        self.assertEqual(again, {"calls": 0, "rows": 0})
        self.assertEqual(self.rows("select count(*) from odds_snapshots"), [(6,)])
        odds_archive.archive_response([_event(hprice=-170, aprice=145)], {}, "2026-10-21T23:20:00.001Z", purpose="closing")
        self.assertEqual(self.rows("select count(*) from odds_snapshots"), [(12,)])
        series = self.rows("select captured_at, price_american from odds_snapshots where bookmaker_key='draftkings' "
                           "and selection='home' order by captured_at")
        self.assertEqual(series, [("2026-10-21T22:50:00.123Z", -150), ("2026-10-21T23:20:00.001Z", -170)])
        self.assertEqual(self.rows("select purpose from odds_calls order by captured_at"), [("pricing",), ("closing",)])

    def test_garbage_payload_does_not_raise_and_empty_slate_still_logs_the_call(self):
        res = odds_archive.safe_archive({"message": "quota"}, {"x-requests-remaining": "0"}, "2026-10-21T10:00:00.000Z",
                                        http_status=401)
        self.assertEqual(res["rows"], 0)
        self.assertEqual(self.rows("select http_status, n_events, requests_remaining from odds_calls"), [(401, 0, 0)])

    def test_safe_archive_swallows_storage_errors(self):
        buf = io.StringIO()
        with patch.object(odds_archive, "connect", side_effect=sqlite3.OperationalError("disk full")), redirect_stdout(buf):
            self.assertIsNone(odds_archive.safe_archive([_event()], {}, "2026-10-21T10:00:00.000Z"))
        self.assertIn("ERROR: could not archive the odds response", buf.getvalue())

    def test_disabled_flag_stores_nothing(self):
        with patch.object(config, "ODDS_ARCHIVE_ENABLED", False):
            self.assertIsNone(odds_archive.safe_archive([_event()], {}, "2026-10-21T10:00:00.000Z"))
        self.assertFalse(os.path.exists(self.db))

    def test_link_game_ids_matches_team_pair_and_tip_and_leaves_others(self):
        odds_archive.archive_response([_event(), _event("e2", "Miami Heat", "Orlando Magic")], {}, "2026-10-21T22:50:00.000Z")
        games = pd.DataFrame([{"gameId": "0022600001", "HOME_TEAM_ABBREVIATION": "ATL", "VISITOR_TEAM_ABBREVIATION": "BOS",
                               "TIP_UTC": "2026-10-21T23:30:00Z"}])
        self.assertEqual(odds_archive.link_game_ids(games), 6)
        self.assertEqual(self.rows("select distinct nba_game_id, home_team from odds_snapshots order by home_team"),
                         [("0022600001", "Atlanta Hawks"), (None, "Miami Heat")])
        self.assertEqual(odds_archive.link_game_ids(games), 0)                 # idempotent


class GetTonightsOddsArchiveTests(ArchiveBase):
    def test_pricing_call_archives_all_books_and_returns_the_same_dict_as_before(self):
        payload = [_event()]
        with patch.object(odds.requests, "get", return_value=FakeResponse(payload)), \
             patch("market_odds.write_moneyline_rows"):
            result = odds.get_tonights_odds()
        self.assertEqual(result[("Atlanta Hawks", "Boston Celtics")]["home_odds"], -150)
        self.assertEqual(self.rows("select count(*) from odds_snapshots"), [(6,)])
        self.assertEqual(self.rows("select purpose, requests_remaining from odds_calls"), [("pricing", 480)])

    def test_two_calls_for_the_same_game_make_a_time_series(self):
        with patch.object(odds.requests, "get", side_effect=[FakeResponse([_event()]), FakeResponse([_event(hprice=-160)])]), \
             patch("market_odds.write_moneyline_rows"), patch.object(odds_archive, "now_utc_ms",
                                                                     side_effect=["2026-10-21T22:50:00.000Z", "2026-10-21T23:20:00.000Z"]):
            odds.get_tonights_odds()
            odds.get_tonights_odds(purpose="closing")
        self.assertEqual(self.rows("select count(distinct captured_at) from odds_snapshots"), [(2,)])
        self.assertEqual(self.rows("select purpose from odds_calls order by captured_at"), [("pricing",), ("closing",)])

    def test_archive_failure_is_loud_but_does_not_stop_the_odds_call(self):
        buf = io.StringIO()
        with patch.object(odds.requests, "get", return_value=FakeResponse([_event()])), \
             patch("market_odds.write_moneyline_rows"), \
             patch.object(odds_archive, "archive_response", side_effect=RuntimeError("boom")), redirect_stdout(buf):
            result = odds.get_tonights_odds()
        self.assertEqual(len(result), 1)
        self.assertIn("ERROR: could not archive the odds response", buf.getvalue())

    def test_failed_http_call_keeps_the_quota_headers(self):
        resp = FakeResponse({"message": "bad key"}, status=401, headers={"x-requests-remaining": "0"})
        with patch.object(odds.requests, "get", return_value=resp), redirect_stdout(io.StringIO()):
            self.assertEqual(odds.get_tonights_odds(), {})
        self.assertEqual(self.rows("select http_status, n_events, requests_remaining from odds_calls"), [(401, 0, 0)])

    def test_missing_headers_and_commence_time_do_not_crash(self):
        ev = _event()
        ev.pop("commence_time")
        resp = FakeResponse([ev], headers={})
        with patch.object(odds.requests, "get", return_value=resp), patch("market_odds.write_moneyline_rows"):
            odds.get_tonights_odds()
        self.assertEqual(self.rows("select requests_remaining, n_events from odds_calls"), [(None, 1)])


class ClosingCaptureTests(ArchiveBase):
    NOW = "2026-10-21T23:20:00Z"
    GAMES = pd.DataFrame([
        {"gameId": "g1", "TIP_UTC": "2026-10-21T23:30:00Z", "HOME_TEAM_ABBREVIATION": "ATL", "VISITOR_TEAM_ABBREVIATION": "BOS"},
        {"gameId": "g2", "TIP_UTC": "2026-10-21T23:30:00Z", "HOME_TEAM_ABBREVIATION": "MIA", "VISITOR_TEAM_ABBREVIATION": "ORL"},
        {"gameId": "g3", "TIP_UTC": "2026-10-22T02:00:00Z", "HOME_TEAM_ABBREVIATION": "LAL", "VISITOR_TEAM_ABBREVIATION": "DEN"},
    ])

    def test_flag_is_off_by_default_and_nothing_is_called(self):
        self.assertFalse(config.ODDS_CLOSING_CAPTURE)
        with patch.object(predict, "get_tonights_odds", side_effect=AssertionError("odds fetched")):
            self.assertFalse(predict.maybe_capture_closing(self.GAMES, self.NOW))

    def test_due_tips_are_in_window_and_deduplicated(self):
        self.assertEqual(odds_archive.due_closing_tips(self.GAMES, self.NOW), ["2026-10-21T23:30:00Z"])
        self.assertEqual(odds_archive.due_closing_tips(self.GAMES, "2026-10-21T23:00:00Z"), [])       # 30 min out
        self.assertEqual(odds_archive.due_closing_tips(self.GAMES, "2026-10-21T23:29:00Z"), [])       # 1 min: too late
        self.assertEqual(odds_archive.due_closing_tips(self.GAMES, "2026-10-21T23:13:00Z"), ["2026-10-21T23:30:00Z"])

    def test_one_call_per_tip_time_then_the_ledger_stops_repeats(self):
        budget = os.path.join(self.tmp.name, "budget.json")
        calls = []
        with patch.object(config, "ODDS_CLOSING_CAPTURE", True), \
             patch.object(predict, "_odds_budget_path", return_value=budget), \
             patch.object(predict, "get_tonights_odds", side_effect=lambda purpose="pricing": calls.append(purpose) or {}):
            self.assertTrue(predict.maybe_capture_closing(self.GAMES, self.NOW))
            self.assertFalse(predict.maybe_capture_closing(self.GAMES, "2026-10-21T23:21:00Z"))      # same tip: ledger
            self.assertTrue(predict.maybe_capture_closing(self.GAMES, "2026-10-22T01:50:00Z"))       # the 02:00Z tip
        self.assertEqual(calls, ["closing", "closing"])
        with open(budget, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["closing_calls"], 2)

    def test_daily_cap_and_monthly_reserve_block_the_call(self):
        budget = os.path.join(self.tmp.name, "budget.json")
        with open(budget, "w", encoding="utf-8") as fh:
            json.dump({"date": "2026-10-21", "calls": 3, "closing_calls": config.ODDS_CLOSING_DAILY_CALL_CAP}, fh)
        self.assertFalse(predict.closing_call_allowed("2026-10-21", budget))
        self.assertTrue(predict.closing_call_allowed("2026-10-22", budget))                        # new day
        self.assertFalse(predict.closing_call_allowed("2026-10-22", budget, remaining=config.ODDS_CLOSING_MONTHLY_RESERVE))
        self.assertTrue(predict.closing_call_allowed("2026-10-22", budget, remaining=config.ODDS_CLOSING_MONTHLY_RESERVE + 1))
        with open(budget, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        self.assertFalse(predict.closing_call_allowed("2026-10-22", budget))                       # unknown state: no call

    def test_pricing_counter_keeps_the_closing_counter(self):
        budget = os.path.join(self.tmp.name, "budget.json")
        predict.record_closing_call("2026-10-21", budget)
        self.assertEqual(predict.record_odds_call("2026-10-21", budget), 1)
        with open(budget, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"date": "2026-10-21", "calls": 1, "closing_calls": 1})
        self.assertTrue(predict.odds_call_allowed("2026-10-21", budget))

    def test_a_failing_closing_call_is_reported_not_raised_and_not_ledgered(self):
        budget = os.path.join(self.tmp.name, "budget.json")
        buf = io.StringIO()
        with patch.object(config, "ODDS_CLOSING_CAPTURE", True), \
             patch.object(predict, "_odds_budget_path", return_value=budget), \
             patch.object(predict, "get_tonights_odds", side_effect=RuntimeError("timeout")), redirect_stdout(buf):
            self.assertFalse(predict.maybe_capture_closing(self.GAMES, self.NOW))
        self.assertIn("Closing odds capture failed", buf.getvalue())
        self.assertEqual(odds_archive.due_closing_tips(self.GAMES, self.NOW), ["2026-10-21T23:30:00Z"])


if __name__ == "__main__":
    unittest.main()
