"""Run the unittest suite with all network access blocked (the 'network off' gate).

Usage (from a checkout root):  <venv python> run_offline_tests.py
Any attempt to resolve or connect raises NetworkBlocked, so a test that
touches the network fails loudly instead of passing by luck.
"""
import os
import re
import socket
import subprocess
import sys
import unittest


class NetworkBlocked(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkBlocked("network access attempted during the offline test run")


# Child processes don't inherit the socket patch below, so fence them too.
# load_dotenv() never overrides variables that are already set, so these dummy
# values win over the local dotenv file for this process AND every child it
# spawns: Supabase points at a dead local port; no real key, Odds or Twilio value.
for _name in ("SUPABASE_SECRET_KEY", "ODDS_API_KEY", "TWILIO_ACCOUNT_SID",
              "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_TO"):
    os.environ[_name] = "offline-test-dummy"
os.environ["SUPABASE_URL"] = "http://127.0.0.1:9"
os.environ.pop("ALLOW_RUN_WORKFLOW", None)

_PIPELINE = re.compile(r"run_pipeline|run_predict|run_daily|daily_workflow\.py|"
                       r"src[\\/](collect|elo|features|model|track|predict|odds)\.py", re.I)
_RealPopen = subprocess.Popen


class _GuardedPopen(_RealPopen):
    def __init__(self, args, *a, **kw):
        if _PIPELINE.search(str(args)):
            raise NetworkBlocked(f"offline test run tried to spawn a real pipeline step: {args!r}")
        super().__init__(args, *a, **kw)


subprocess.Popen = _GuardedPopen

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
socket.gethostbyname = _blocked

sys.path.insert(0, os.getcwd())
suite = unittest.defaultTestLoader.discover("tests")
result = unittest.TextTestRunner(verbosity=int(os.getenv("VERBOSITY", "2"))).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
