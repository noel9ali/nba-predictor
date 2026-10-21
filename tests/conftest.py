"""Test-suite defaults, applied before any test module imports the app.

The app hides pre-launch (beta) results unless HIDE_BETA=0 (app.hide_beta). Most fixtures here are
dated before LIVE_START_DATE, so the suite runs with the beta visible; the tests that exercise the
hiding set HIDE_BETA themselves (tests/test_app.py).
"""
import os

os.environ.setdefault("HIDE_BETA", "0")
