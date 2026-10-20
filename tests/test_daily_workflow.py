import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import daily_workflow  # noqa: E402  (daily_workflow.py adds src/ to sys.path itself)
from database import DatabaseError, MissingTableError  # noqa: E402

TWILIO_VARS = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_API_SID", "TWILIO_CLIENT_SECRET",
               "TWILIO_FROM", "TWILIO_TO")


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

    def run_stage(self, stage, rc=0):
        calls = []
        self.envs = {}

        def fake_bat(path, timeout=None, extra_env=None):
            calls.append(os.path.basename(path))
            self.envs[os.path.basename(path)] = extra_env
            return rc, "out\nSaved 1 prediction(s).\n" if "predict" in path else "out\n"

        with patch.object(daily_workflow, "run_bat", side_effect=fake_bat), \
                patch.object(daily_workflow, "insert_rows") as insert_rows, \
                contextlib.redirect_stdout(io.StringIO()):
            result = daily_workflow.run_workflow(send_text=False, trigger="schedule", stage=stage)
        return result, calls, insert_rows.call_args.args[1][0]

    def test_morning_stage_runs_the_pipeline_then_temporary_predictions_and_logs_kind_morning(self):
        result, calls, row = self.run_stage("morning")
        self.assertEqual(calls, ["run_pipeline.bat", "run_predict.bat"])
        self.assertEqual(self.envs["run_predict.bat"], {"NBA_PREDICT_PROVISIONAL": "1"})
        self.assertEqual((result["status"], row["kind"]), ("success", "morning"))
        self.assertIn("morning stage", row["notes"])

    def test_a_failed_temporary_step_does_not_fail_the_morning_stage(self):
        calls = []

        def fake_bat(path, timeout=None, extra_env=None):
            calls.append(os.path.basename(path))
            return (1, "boom\n") if calls[-1] == "run_predict.bat" else (0, "out\n")

        with patch.object(daily_workflow, "run_bat", side_effect=fake_bat), \
                patch.object(daily_workflow, "insert_rows") as insert_rows, \
                contextlib.redirect_stdout(io.StringIO()):
            result = daily_workflow.run_workflow(send_text=False, trigger="schedule", stage="morning")
        row = insert_rows.call_args.args[1][0]
        self.assertEqual((result["status"], row["status"]), ("success", "success"))
        self.assertIn("temporary predictions failed", row["notes"])

    def test_the_picks_sms_check_ignores_temporary_predictions(self):
        self.assertEqual(daily_workflow.saved_predictions("Saved 3 temporary prediction(s).\n"), 0)

    def test_predict_stage_runs_only_predictions_and_logs_kind_predict(self):
        result, calls, row = self.run_stage("predict")
        self.assertEqual(calls, ["run_predict.bat"])
        self.assertEqual((result["status"], row["kind"]), ("success", "predict"))

    def test_predict_stage_sets_the_window_for_the_child_only(self):
        self.run_stage("predict")
        self.assertEqual(self.envs["run_predict.bat"],
                         {"NBA_PREDICT_WINDOW_MINUTES": str(daily_workflow.PREDICT_WINDOW_MINUTES)})
        self.assertNotIn("NBA_PREDICT_WINDOW_MINUTES", os.environ)       # no leak into this process
        self.run_stage("full")
        self.assertIsNone(self.envs["run_predict.bat"])                  # Run now still prices everything

    def test_a_failed_single_step_stage_is_failed_not_partial(self):
        for stage in ("morning", "predict"):
            result, _, row = self.run_stage(stage, rc=1)
            self.assertEqual((result["status"], row["status"]), ("failed", "failed"))

    def test_full_stage_is_unchanged(self):
        result, calls, row = self.run_stage("full")
        self.assertEqual(calls, ["run_pipeline.bat", "run_predict.bat"])
        self.assertEqual(row["kind"], "manual")

    def test_predict_tick_with_nothing_saved_sends_no_sms_and_logs_nothing(self):
        for out in ("No games today.\n", "No games inside the prediction window.\n", "Saved 0 prediction(s).\n",
                    "Odds request budget for today (12 calls) is used up; no odds fetched.\n", ""):
            with self.subTest(out=out), \
                    patch.object(daily_workflow, "run_bat", return_value=(0, out)), \
                    patch.object(daily_workflow, "insert_rows") as insert_rows, \
                    patch.object(daily_workflow, "send_sms") as send_sms, \
                    contextlib.redirect_stdout(io.StringIO()):
                result = daily_workflow.run_workflow(send_text=True, stage="predict")
            self.assertTrue(result["noop"])
            insert_rows.assert_not_called()
            send_sms.assert_not_called()

    def test_predict_tick_that_saved_a_prediction_logs_and_texts(self):
        with patch.object(daily_workflow, "run_bat", return_value=(0, "LAL @ DEN\nSaved 2 prediction(s).\n")), \
                patch.object(daily_workflow, "insert_rows") as insert_rows, \
                patch.object(daily_workflow, "get_todays_predictions", return_value=[]), \
                patch.object(daily_workflow, "get_overall_stats", return_value={}), \
                patch.object(daily_workflow, "send_sms", return_value=True) as send_sms, \
                contextlib.redirect_stdout(io.StringIO()):
            result = daily_workflow.run_workflow(send_text=True, stage="predict")
        self.assertNotIn("noop", result)
        insert_rows.assert_called_once()
        send_sms.assert_called_once()

    def test_saved_predictions_counts_the_line(self):
        self.assertEqual(daily_workflow.saved_predictions("x\nSaved 3 prediction(s).\n"), 3)
        self.assertEqual(daily_workflow.saved_predictions("Saved 0 prediction(s)."), 0)
        self.assertEqual(daily_workflow.saved_predictions(""), 0)
        self.assertEqual(daily_workflow.saved_predictions(None), 0)

    def test_unknown_stage_is_rejected(self):
        with self.assertRaises(ValueError):
            daily_workflow.run_workflow(send_text=False, stage="evening")

    def test_stage_sms_texts(self):
        picks = [{"home_team": "LAL", "away_team": "BOS", "home_win_prob": 0.62, "away_win_prob": 0.38,
                  "predicted_winner": "LAL", "bet_placed": None, "bet_amount": 0, "odds": None}]
        morning = daily_workflow.format_sms([], picks, {}, include_today=False)
        self.assertIn("Today's picks follow later", morning)
        self.assertNotIn("LAL", morning)
        evening = daily_workflow.format_sms([], picks, {}, include_yesterday=False)
        self.assertIn("NBA Picks", evening)
        self.assertNotIn("Yesterday", evening)
        self.assertIn("BOS @ LAL", evening)


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

    def test_send_sms_prefers_the_api_key_over_the_auth_token(self):
        env = {"TWILIO_ACCOUNT_SID": "AC" + "0" * 32, "TWILIO_AUTH_TOKEN": "token",
               "TWILIO_API_SID": "SK" + "0" * 32, "TWILIO_CLIENT_SECRET": "secret",
               "TWILIO_FROM": "+15550100000", "TWILIO_TO": "+15550100001"}
        made = {}

        class FakeClient:
            def __init__(self, username, password, account_sid):
                made["auth"] = (username, password, account_sid)
                self.messages = self

            def create(self, **kw):
                made["sent"] = kw
                return type("M", (), {"sid": "SMfake"})()

        with patch.dict(os.environ, env), patch.dict(sys.modules, {
                "twilio": type(sys)("twilio"), "twilio.rest": type(sys)("twilio.rest")}),                 contextlib.redirect_stdout(io.StringIO()):
            sys.modules["twilio.rest"].Client = FakeClient
            self.assertTrue(daily_workflow.send_sms("hello"))
        self.assertEqual(made["auth"], ("SK" + "0" * 32, "secret", "AC" + "0" * 32))
        self.assertEqual(made["sent"]["body"], "hello")

    def test_redact_secrets_scrubs_twilio_identifiers(self):
        # Obviously-fake values -- never read from .env.
        fake = {
            "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
            "TWILIO_FROM": "+15550100000",
            "TWILIO_TO": "+15550100001",
        }
        with patch.dict(os.environ, fake):
            text = daily_workflow.redact_secrets(
                f"sid={fake['TWILIO_ACCOUNT_SID']} from={fake['TWILIO_FROM']} to={fake['TWILIO_TO']}"
            )
        for value in fake.values():
            self.assertNotIn(value, text)
        self.assertEqual(text, "sid=<TWILIO_ACCOUNT_SID> from=<TWILIO_FROM> to=<TWILIO_TO>")


class ExceptionLoggingTests(unittest.TestCase):
    """DP-F5: the three bare `except Exception` fallbacks must log only the
    exception type name (no message, no secrets), not swallow silently."""

    class Boom(Exception):
        pass

    def test_get_yesterdays_results_logs_the_exception_type_name(self):
        with patch.object(daily_workflow, "select_rows", side_effect=self.Boom("secret detail")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = daily_workflow.get_yesterdays_results()
        self.assertEqual(result, [])
        self.assertIn("Boom", output.getvalue())
        self.assertNotIn("secret detail", output.getvalue())

    def test_get_todays_predictions_logs_the_exception_type_name(self):
        with patch.object(daily_workflow, "select_rows", side_effect=self.Boom("secret detail")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = daily_workflow.get_todays_predictions()
        self.assertEqual(result, [])
        self.assertIn("Boom", output.getvalue())
        self.assertNotIn("secret detail", output.getvalue())

    def test_get_overall_stats_logs_the_exception_type_name(self):
        with patch.object(daily_workflow, "select_rows", side_effect=self.Boom("secret detail")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = daily_workflow.get_overall_stats()
        self.assertEqual(result, {})
        self.assertIn("Boom", output.getvalue())
        self.assertNotIn("secret detail", output.getvalue())


class ExitCodeTests(unittest.TestCase):
    """DP-F4: __main__ must exit nonzero when any step failed, so Task
    Scheduler's retry policy actually fires."""

    def test_exit_code_is_zero_only_on_full_success(self):
        self.assertEqual(daily_workflow._exit_code({"status": "success"}), 0)
        self.assertEqual(daily_workflow._exit_code({"status": "partial"}), 1)
        self.assertEqual(daily_workflow._exit_code({"status": "failed"}), 1)


class RunBatTimeoutTests(unittest.TestCase):
    """DP-F6 / SEC-F6: subprocess steps must have a bounded, configurable
    timeout. run_bat() uses Popen()+communicate() (not subprocess.run), so
    these fakes patch Popen -- never leave a real Popen call unmocked here,
    it would launch the real run_pipeline.bat (network + live DB)."""

    def test_run_bat_treats_a_timeout_as_a_failed_step(self):
        class FakeProc:
            pid = 4242
            returncode = 1

            def __init__(self):
                self.calls = 0

            def communicate(self, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired(cmd="run_pipeline.bat", timeout=timeout)
                return "", ""

        fake_proc = FakeProc()
        with patch.object(daily_workflow.subprocess, "Popen", return_value=fake_proc), \
                patch.object(daily_workflow, "_kill_process_tree") as fake_kill:
            rc, output = daily_workflow.run_bat(
                os.path.join(daily_workflow.REPO_ROOT, "run_pipeline.bat"), timeout=1
            )
        self.assertEqual(rc, 1)
        self.assertIn("timed out", output.lower())
        fake_kill.assert_called_once_with(fake_proc)

    def test_run_bat_passes_a_configurable_timeout_and_a_utf8_child_env(self):
        captured_popen_kwargs = {}
        captured_communicate = {}

        class FakeProc:
            pid = 1234
            returncode = 0

            def communicate(self, timeout=None):
                captured_communicate["timeout"] = timeout
                return "", ""

        def fake_popen(cmd, **kwargs):
            captured_popen_kwargs.update(kwargs)
            return FakeProc()

        with patch.dict(os.environ, {"WORKFLOW_STEP_TIMEOUT_SECONDS": "45"}), \
                patch.object(daily_workflow.subprocess, "Popen", side_effect=fake_popen):
            daily_workflow.run_bat(os.path.join(daily_workflow.REPO_ROOT, "run_pipeline.bat"))

        self.assertEqual(captured_communicate.get("timeout"), 45)
        self.assertEqual(captured_popen_kwargs.get("env", {}).get("PYTHONIOENCODING"), "utf-8")
        self.assertEqual(captured_popen_kwargs.get("encoding"), "utf-8")
        self.assertEqual(captured_popen_kwargs.get("errors"), "replace")


class RunBatProcessTreeTimeoutTests(unittest.TestCase):
    """DP-F6 / SEC-F6 follow-up: a timed-out step must kill the WHOLE process
    tree (cmd.exe and any grandchild it spawned, e.g. python.exe), not just
    cmd.exe -- otherwise a held stdout/stderr pipe handle blocks run_bat's
    own cleanup past the timeout and the workflow lock is never released.
    Uses the real behaviour (a real cmd.exe -> python.exe child tree), not a
    fake -- the child is a plain `time.sleep`, never a pipeline script."""

    def setUp(self):
        self.SCRATCH_DIR = tempfile.mkdtemp(prefix="nba_predictor_test_")
        self.addCleanup(shutil.rmtree, self.SCRATCH_DIR, ignore_errors=True)

    def test_a_timed_out_step_kills_the_grandchild_process_too(self):
        pidfile = os.path.join(self.SCRATCH_DIR, "rb_sleeper.pid")
        batfile = os.path.join(self.SCRATCH_DIR, "rb_sleeper.bat")

        # The grandchild just sleeps -- never a real pipeline script -- and
        # writes its own PID so the test can confirm it was actually killed.
        child_script = (
            "import os,sys,time;"
            f"open(r'{pidfile}','w').write(str(os.getpid()));"
            "sys.stdout.flush();"
            "time.sleep(20)"
        )
        with open(batfile, "w") as f:
            f.write("@echo off\r\n")
            f.write(f'"{sys.executable}" -c "{child_script}"\r\n')

        start = time.monotonic()
        rc, output = daily_workflow.run_bat(batfile, timeout=2)
        elapsed = time.monotonic() - start

        self.assertEqual(rc, 1)
        self.assertIn("timed out", output.lower())
        self.assertLess(elapsed, 15, f"run_bat took {elapsed:.1f}s -- the grandchild likely blocked cleanup")

        pid = None
        for _ in range(20):
            if os.path.exists(pidfile):
                with open(pidfile) as f:
                    pid = f.read().strip()
                break
            time.sleep(0.1)
        self.assertIsNotNone(pid, "the sleeper never started -- test setup problem, not a real result")

        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        self.assertNotIn(pid, result.stdout, f"sleeper PID {pid} is still alive after the timeout")


class ConsoleEncodingTests(unittest.TestCase):
    """DP-F2: stdout/stderr must survive a non-UTF-8 console/log-redirect
    encoding instead of crashing with UnicodeEncodeError."""

    def test_force_utf8_stdio_survives_a_cp1252_console_encoding(self):
        src_dir = os.path.join(daily_workflow.REPO_ROOT, "src")
        script = (
            "import sys; sys.path.insert(0, r'%s'); "
            "from console import force_utf8_stdio; force_utf8_stdio(); "
            "print(u'✓')" % src_dir
        )
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "cp1252"
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=child_env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class WorkflowLockTests(unittest.TestCase):
    """TH-F22: run_workflow_async()/workflow_is_running()'s real threading
    lock -- the actual double-start guard behind /api/run-workflow's 409 --
    was never exercised by any test; every other test mocks both functions
    away entirely. Patch only run_workflow itself (not run_workflow_async or
    workflow_is_running) to a slow stub gated on a threading.Event."""

    def test_a_concurrent_start_is_rejected_while_the_first_run_is_in_progress(self):
        started = threading.Event()
        release = threading.Event()

        def slow_run_workflow(*args, **kwargs):
            started.set()
            release.wait(timeout=5)
            return {"status": "success"}

        with patch.object(daily_workflow, "run_workflow", side_effect=slow_run_workflow):
            ok1, msg1 = daily_workflow.run_workflow_async()
            self.assertTrue(started.wait(timeout=5), "background thread never started run_workflow")
            self.assertTrue(ok1)
            self.assertEqual(msg1, "Workflow started")
            self.assertTrue(daily_workflow.workflow_is_running())

            ok2, msg2 = daily_workflow.run_workflow_async()
            self.assertFalse(ok2)
            self.assertEqual(msg2, "Workflow already running")

            release.set()
            daily_workflow._workflow_thread.join(timeout=5)

        self.assertFalse(daily_workflow.workflow_is_running())


if __name__ == "__main__":
    unittest.main()
