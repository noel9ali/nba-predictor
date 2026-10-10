"""Central configuration for the player-data work (thresholds, maps, paths).

Spec rule "config over constants": every tunable used by the player-data modules lives here.
Values are plain Python so tests and the pipeline import them directly.
"""

from __future__ import annotations

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")

# ---------------------------------------------------------------------------
# nba_api access
# ---------------------------------------------------------------------------
NBA_API_MIN_INTERVAL_SECONDS = 0.6   # at least this long between nba_api calls
NBA_API_RETRIES = 3
NBA_API_BACKOFF_SECONDS = 2.0        # doubled per retry
NBA_API_TIMEOUT_SECONDS = 60

# ---------------------------------------------------------------------------
# Injury reports (phase 2)
# ---------------------------------------------------------------------------
INJURY_SOURCE = "nba_official_pdf"
INJURY_REPORT_URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{slot}.pdf"
INJURY_REPORT_TZ = "America/New_York"          # slot names and PDF header times are ET
INJURY_RAW_DIR = os.path.join(RAW_DIR, "injury_reports")      # irreplaceable PDF archive (git-ignored)
INJURY_LOCAL_DIR = os.path.join(DATA_DIR, "injuries")          # local sink + reports (git-ignored)
INJURY_LOCAL_DB = os.path.join(INJURY_LOCAL_DIR, "injury_snapshots.sqlite")
INJURY_UNMATCHED_CSV = os.path.join(INJURY_LOCAL_DIR, "injury_unmatched.csv")
INJURY_HTTP_TIMEOUT_SECONDS = 30
INJURY_HTTP_MIN_INTERVAL_SECONDS = 0.4
# A --snapshot run probes 15-minute slots from now back this far, newest first, and archives the newest
# report it finds ("latest"), or every report in the window it does not have yet ("all").
# "latest" keeps volume to one report per scheduler tick (~200 rows each); missed slots can be
# backfilled later because nba.com keeps the archive (back to at least Dec 2020).
INJURY_SNAPSHOT_LOOKBACK_HOURS = 3
INJURY_SNAPSHOT_MODE = "latest"
# Reports moved from hourly ("_05PM") to 15-minute ("_05_00PM") slots in late December 2025.
INJURY_15MIN_SLOTS_FROM = "2025-12-21"
# Backfill: which slot(s) per day to fetch. One pre-tip snapshot per day keeps the backfill cheap.
INJURY_BACKFILL_SLOTS_ET = ("05PM",)  # hourly-era name; 15-minute era uses "05_00PM"

# Raw status strings (lower-cased, whitespace-collapsed) -> normalized status.
# Unknown strings are logged and mapped by INJURY_STATUS_FALLBACK.
INJURY_STATUS_MAP = {
    "out": "out",
    "out for season": "out",
    "out for the season": "out",
    "out indefinitely": "out",
    "inactive": "out",
    "suspended": "out",
    "not with team": "out",
    "doubtful": "doubtful",
    "questionable": "questionable",
    "gtd": "questionable",
    "game time decision": "questionable",
    "game-time decision": "questionable",
    "day-to-day": "questionable",
    "day to day": "questionable",
    "dtd": "questionable",
    "probable": "probable",
    "available": "available",
    "active": "available",
}
INJURY_STATUS_FALLBACK = "questionable"   # unknown strings: uncertain, logged for review
INJURY_STATUSES = ("out", "doubtful", "questionable", "probable", "available")

# Status -> probability the player plays (phase 3 uses this; defined here so phase 2 can expose it).
STATUS_TO_P_PLAY = {
    "out": 0.0,
    "doubtful": 0.05,
    "questionable": 0.5,
    "probable": 0.9,
    "available": 1.0,
    None: 1.0,          # no report entry
}

# ---------------------------------------------------------------------------
# Player data foundation (phase 1)
# ---------------------------------------------------------------------------
PLAYER_FIRST_SEASON = "2019-20"
ABSENCE_MIN_TYPICAL_MINUTES = 15.0
ABSENCE_LOOKBACK_GAMES = 10
ABSENCE_MIN_APPEARANCES = 5
