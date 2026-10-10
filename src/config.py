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
PLAYER_LOCAL_DB = os.path.join(DATA_DIR, "player_data", "player_data.sqlite")   # local mirror (git-ignored)

# ---------------------------------------------------------------------------
# Ratings and minutes projections (phase 3)
# ---------------------------------------------------------------------------
RATING_VERSION = "2026-10-10"
RATING_WINDOW_DAYS = 730                 # trailing window (about 2 seasons of games)
RATING_HALF_LIFE_DAYS = 365              # exponential down-weighting of older games
RATING_RIDGE_ALPHAS = (10.0,)   # pooled forward validation, 19 windows 2020-2026: 3:191.4 10:185.2 30:185.9 100:189.3 1000:196.9 (MSE, margin per 100); box prior alone 199.4. Give several values to re-enable per-refit CV.
RATING_CV_HOLDOUT_FRACTION = 0.2         # last 20% of the window (by date) validates alpha
RATING_MIN_GAMES = 300                   # do not fit before this many games are in the window
RATING_BACKFILL_EVERY_DAYS = 7           # historical refit cadence (weekly)
RATING_BACKFILL_START = "2019-11-18"
RATING_PRIMARY = "rapm_lite_v1"
RATING_FALLBACK = "box_value_v1"
RATING_MIN_MINUTES_FOR_PRIMARY = 500     # below this rapm minutes_basis, use box_value_v1
BOX_PRIOR_MINUTES = 400                  # empirical-Bayes shrinkage strength for box_value_v1 (minutes)

MINUTES_VERSION = "minutes_v1"
MINUTES_HALF_LIFE_GAMES = 10             # EWMA half-life over games played
MINUTES_ROSTER_LOOKBACK_GAMES = 20       # roster = players seen in the team's last N games
MINUTES_QUANTILE_GAMES = 30              # games played used for p10/p90
MINUTES_PLAYER_CAP = 40.0
MINUTES_TEAM_TOTAL = 240.0
MINUTES_ROTATION_MIN = 10.0              # base minutes for 'rotation' role

# Provider names that the normalizer cannot match (nicknames, legal-name changes). Keyed by
# player_names.normalize_name(raw name) -> nba_api player_id. Add entries from data/injuries/injury_unmatched.csv.
PLAYER_NAME_OVERRIDES = {
    "nicolas claxton": 1629651,      # Nic Claxton
    "nene hilario": 2403,            # Nene
    "charles brown": 1629718,        # Charlie Brown Jr.
    "enes kanter": 202683,           # Enes Freedom
    "marcos louzada silva": 1629712, # Didi Louzada
    "cameron reynolds": 1629244,     # Cam Reynolds
    "rj nembhard": 1630612,          # Ruben Nembhard Jr.
}

# ---------------------------------------------------------------------------
# Availability features (phase 4)
# ---------------------------------------------------------------------------
AVAILABILITY_FEATURE_VERSION = "avail_v1"
AVAILABILITY_AS_OF_MINUTES_BEFORE_TIP = 60
AVAILABILITY_KEY_MIN_BASE_MINUTES = 15.0   # only players with this many base minutes can be "top" players
AVAILABILITY_RATING_TYPES = ("rapm_lite_v1", "box_value_v1")
RATING_UNRATED_VALUE = -1.0                # players without any rating yet (just debuted): a little below average
REST_DAYS_CAP = 7                          # season opener and long breaks (All-Star) are capped here

# ---------------------------------------------------------------------------
# Betting (phase 6; src/betting.py). Same values as the original track.kelly_bet.
# ---------------------------------------------------------------------------
KELLY_FRACTION = 0.25
KELLY_CAP = 0.05                 # max stake as a fraction of bankroll
MAX_DECIMAL_ODDS = 5.0           # never bet longer prices than this

# ---------------------------------------------------------------------------
# Predict-time availability (phase 6)
# ---------------------------------------------------------------------------
MAX_SCENARIO_PLAYERS = 3         # per team: uncertain players (0.1 < p_play < 0.9) enumerated as present/absent
SCENARIO_P_LOW = 0.1
SCENARIO_P_HIGH = 0.9
AVAILABILITY_GATE = False        # shipped off
UNCERTAINTY_RANGE = 0.06         # prob_range_high - prob_range_low above this triggers the gate
AVAILABILITY_GATE_ACTION = "halve"   # 'halve' the Kelly fraction or 'skip' (skip_reason 'availability_uncertain')
STATUS_CHANGE_KEY_PLAYERS = 5    # top N by impact compared for status_changed_after_pred

# Team tricode -> nba_api team_id (static; used by the API, which must not import nba_api at request time).
TEAM_IDS = {"ATL": 1610612737, "BKN": 1610612751, "BOS": 1610612738, "CHA": 1610612766, "CHI": 1610612741, "CLE": 1610612739, "DAL": 1610612742, "DEN": 1610612743, "DET": 1610612765, "GSW": 1610612744, "HOU": 1610612745, "IND": 1610612754, "LAC": 1610612746, "LAL": 1610612747, "MEM": 1610612763, "MIA": 1610612748, "MIL": 1610612749, "MIN": 1610612750, "NOP": 1610612740, "NYK": 1610612752, "OKC": 1610612760, "ORL": 1610612753, "PHI": 1610612755, "PHX": 1610612756, "POR": 1610612757, "SAC": 1610612758, "SAS": 1610612759, "TOR": 1610612761, "UTA": 1610612762, "WAS": 1610612764}
