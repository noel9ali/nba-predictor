"""Results settled late and games that never got a pick must reach the user, not vanish (diagnostic 2026-10-25).

A missed morning run settled Oct 23 on Oct 25; the old summary only looked at 'yesterday', so Oct 23's results were
never pushed or emailed, and a day with no predictions at all went unmentioned. Fully offline.
"""

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import daily_workflow  # noqa: E402


def result(game_date, away="BOS", home="LAL", correct=1):
    return {"game_date": game_date, "home_team": home, "away_team": away, "predicted_winner": home,
            "actual_winner": home if correct else away, "correct": correct, "bet_amount": 0, "odds": None,
            "profit_loss": None}


def ok(channel="ntfy"):
    return {"channel": channel, "status": "sent", "detail": ""}


class LateResultsTests(unittest.TestCase):
    def setUp(self):
        self.yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.older = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")

    def test_each_date_is_pushed_once_and_marked_sent(self):
        sent = {}
        with patch.object(daily_workflow, "_load_sent", return_value=sent), \
             patch.object(daily_workflow, "_save_sent"), \
             patch.object(daily_workflow, "send_ntfy", return_value=ok()) as send:
            out = daily_workflow.push_results([result(self.older), result(self.yesterday)])
        self.assertEqual(len(out), 2)
        self.assertEqual(send.call_count, 2)
        self.assertIn(f"results|{self.older}", sent)
        self.assertIn(f"results|{self.yesterday}", sent)
        self.assertIn("(", send.call_args_list[0].args[0])        # the late date is labelled in its title

    def test_a_date_already_pushed_is_skipped(self):
        with patch.object(daily_workflow, "_load_sent", return_value={f"results|{self.older}": "x"}), \
             patch.object(daily_workflow, "_save_sent"), \
             patch.object(daily_workflow, "send_ntfy", return_value=ok()) as send:
            daily_workflow.push_results([result(self.older)])
        send.assert_not_called()

    def test_lookup_keeps_yesterday_and_unreported_older_dates_only(self):
        rows = pd.DataFrame([result(self.older), result(self.yesterday)])
        with patch.object(daily_workflow, "select_rows", return_value=rows), \
             patch.object(daily_workflow, "_load_sent", return_value={f"results|{self.older}": "x"}):
            kept = daily_workflow.get_yesterdays_results()
        self.assertEqual([g["game_date"] for g in kept], [self.yesterday])
        with patch.object(daily_workflow, "select_rows", return_value=rows), \
             patch.object(daily_workflow, "_load_sent", return_value={}):
            kept = daily_workflow.get_yesterdays_results()
        self.assertEqual([g["game_date"] for g in kept], [self.older, self.yesterday])

    def test_summary_labels_the_late_date(self):
        text = daily_workflow.format_summary([result(self.older), result(self.yesterday)], [], {})
        self.assertIn("settled late", text)
        self.assertIn("Yesterday's Results", text)


class MissedGamesTests(unittest.TestCase):
    def test_games_played_without_a_prediction_are_listed(self):
        played = pd.DataFrame([
            {"GAME_ID": "0022600010", "MATCHUP": "LAL vs. BOS"}, {"GAME_ID": "0022600010", "MATCHUP": "BOS @ LAL"},
            {"GAME_ID": "0022600011", "MATCHUP": "DEN vs. PHX"}, {"GAME_ID": "0022600011", "MATCHUP": "PHX @ DEN"},
        ])
        done = pd.DataFrame([{"game_id": "0022600010"}])

        def fake_select(table, **kwargs):
            return played if table == "games" else done

        with patch.object(daily_workflow, "select_rows", side_effect=fake_select):
            self.assertEqual(daily_workflow.get_missed_games("2026-10-24"), ["PHX @ DEN"])

    def test_a_failed_read_reports_nothing(self):
        with patch.object(daily_workflow, "select_rows", side_effect=RuntimeError("down")):
            self.assertEqual(daily_workflow.get_missed_games("2026-10-24"), [])

    def test_missed_push_is_sent_once_per_date(self):
        sent = {}
        with patch.object(daily_workflow, "_load_sent", return_value=sent), \
             patch.object(daily_workflow, "_save_sent"), \
             patch.object(daily_workflow, "send_ntfy", return_value=ok()) as send:
            daily_workflow.push_missed("2026-10-24", ["PHX @ DEN"])
            self.assertIn("missed|2026-10-24", sent)
            daily_workflow.push_missed("2026-10-24", ["PHX @ DEN"])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(daily_workflow.push_missed("2026-10-24", []), [])

    def test_late_morning_threshold(self):
        from datetime import datetime
        self.assertFalse(daily_workflow.morning_is_late(datetime(2026, 10, 25, 6, 5)))
        self.assertTrue(daily_workflow.morning_is_late(datetime(2026, 10, 25, 20, 22)))


if __name__ == "__main__":
    unittest.main()
