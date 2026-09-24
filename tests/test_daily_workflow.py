import contextlib
import io
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import daily_workflow  # noqa: E402  (daily_workflow.py adds src/ to sys.path itself)
from database import DatabaseError, MissingTableError  # noqa: E402

TWILIO_VARS = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_TO")


class LogRunTests(unittest.TestCase):
    def test_log_run_inserts_one_structured_row(self):
        tail = "x" * 5000 + " key=sb_" "secret_TESTVALUE"  # split so secret scanners skip it
        with patch.dict(os.environ, {"SUPABASE_SECRET_KEY": "sb_" "secret_TESTVALUE"}), \
                patch.object(daily_workflow, "insert_rows") as insert_rows:
            daily_workflow.log_run(
                "2026-09-23", "2026-09-23T06:00:00-04:00", "2026-09-23T06:02:00-04:00",
                "partial", True, False, 1, "predict failed", trigger="manual", log_tail=tail,
            )

        table, rows = insert_rows.call_args.args
        self.assertEqual(table, "workflow_log")
        row = rows[0]
        self.assertEqual(
            set(row),
            {"run_date", "kind", "trigger", "started_at", "finished_at", "status",
             "pipeline_ok", "predict_ok", "sms_sent", "notes", "log_tail"},
        )
        self.assertEqual((row["kind"], row["trigger"], row["status"]), ("manual", "manual", "partial"))
        self.assertIs(row["pipeline_ok"], True)
        self.assertIs(row["predict_ok"], False)
        self.assertIs(row["sms_sent"], True)
        self.assertEqual(len(row["log_tail"]), daily_workflow.LOG_TAIL_CHARS)
        self.assertNotIn("TESTVALUE", row["log_tail"])
        self.assertTrue(row["log_tail"].endswith("key=<SUPABASE_SECRET_KEY>"))

    def test_missing_workflow_log_table_does_not_raise(self):
        for error in (MissingTableError("table is missing"), DatabaseError("Inserting rows failed")):
            with self.subTest(error=type(error).__name__):
                output = io.StringIO()
                with patch.object(daily_workflow, "insert_rows", side_effect=error), \
                        contextlib.redirect_stdout(output):
                    daily_workflow.log_run("2026-09-23", "s", "f", "failed", False, False, False)
                self.assertIn("20260923000500", output.getvalue())

    def test_run_workflow_logs_trigger_and_output(self):
        with patch.object(daily_workflow, "run_bat", return_value=(0, "step output\n")), \
                patch.object(daily_workflow, "insert_rows") as insert_rows, \
                contextlib.redirect_stdout(io.StringIO()):
            result = daily_workflow.run_workflow(send_text=False, trigger="manual")

        self.assertEqual(result["status"], "success")
        row = insert_rows.call_args.args[1][0]
        self.assertEqual((row["kind"], row["trigger"]), ("manual", "manual"))
        self.assertEqual(row["log_tail"], "step output\nstep output\n")
        self.assertRegex(row["started_at"], r"[+-]\d{2}:\d{2}$")  # timestamptz needs an offset


class QueryAndSmsTests(unittest.TestCase):
    def test_format_sms_with_text_probabilities_and_odds(self):
        rows = pd.DataFrame([
            {"home_team": "LAL", "away_team": "BOS", "home_win_prob": "0.62", "away_win_prob": "0.38",
             "predicted_winner": "LAL", "bet_placed": "LAL", "bet_amount": 25.0, "odds": "150"},
            {"home_team": "DEN", "away_team": "PHX", "home_win_prob": "0.45", "away_win_prob": "0.55",
             "predicted_winner": "PHX", "bet_placed": None, "bet_amount": None, "odds": None},
        ])
        with patch.object(daily_workflow, "select_rows", return_value=rows) as select_rows:
            predictions = daily_workflow.get_todays_predictions()

        self.assertIn(("game_date", "eq", daily_workflow.date.today().strftime("%Y-%m-%d")),
                      select_rows.call_args.kwargs["filters"])
        sms = daily_workflow.format_sms([], predictions, {})
        self.assertIn("BOS @ LAL — LAL (62%) | Bet: $25.00 @ +150", sms)
        self.assertIn("PHX @ DEN — PHX (55%)", sms)

    def test_yesterdays_results_handle_missing_profit_loss(self):
        rows = pd.DataFrame([
            {"home_team": "LAL", "away_team": "BOS", "predicted_winner": "LAL", "actual_winner": "LAL",
             "correct": 1, "bet_placed": None, "bet_amount": 0.0, "odds": None, "profit_loss": None},
        ])
        with patch.object(daily_workflow, "select_rows", return_value=rows):
            results = daily_workflow.get_yesterdays_results()
        sms = daily_workflow.format_sms(results, [], {})
        self.assertIn("✓ BOS @ LAL — predicted LAL, actual LAL, P/L: +$0.00", sms)

    def test_overall_stats_fall_back_to_1000_without_bankroll_table(self):
        preds = pd.DataFrame([{"correct": 1, "profit_loss": 37.5}, {"correct": 0, "profit_loss": -20.0}])

        def fake_select(table, **kwargs):
            if table == "bankroll":
                raise MissingTableError("Reading bankroll failed: table is missing")
            return preds

        with patch.object(daily_workflow, "select_rows", side_effect=fake_select):
            stats = daily_workflow.get_overall_stats()
        self.assertEqual(stats["bankroll"], 1000.0)
        self.assertEqual((stats["total"], stats["correct"], stats["total_pl"]), (2, 1, 17.5))

    def test_send_sms_skips_without_credentials(self):
        env = {name: "" for name in TWILIO_VARS}
        with patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(daily_workflow.send_sms("hello"))
        self.assertIn("SMS skipped", output.getvalue())


if __name__ == "__main__":
    unittest.main()
