"""Live scores for /api/live-scores: a cached server-side proxy to the NBA live scoreboard.

The browser never calls NBA hosts (the CSP is connect-src 'self'); app.py serves this
module's snapshot. One snapshot is shared by every request: an upstream fetch happens at
most once per CACHE_SECONDS, and concurrent requests wait for that one fetch instead of
starting their own. When a fetch fails, the last good snapshot is served as stale.

Upstream text is only matched against, never echoed: every field this module emits is an
int, None, a bool, a validated game id or a clock string built here from numbers.
"""
import re
import threading
import time
from datetime import date, datetime, timezone

import requests

SCOREBOARD_PATH = "liveData/scoreboard/todaysScoreboard_00.json"
# (source label, URL). cdn.nba.com is the public CDN; Akamai refuses some networks, so the
# S3 bucket behind it (same JSON) is the fallback. Whichever answered last is tried first.
UPSTREAMS = (
    ("nba-cdn", "https://cdn.nba.com/static/json/" + SCOREBOARD_PATH),
    ("nba-origin", "https://nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/NBA/" + SCOREBOARD_PATH),
)
REQUEST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"),
}
TIMEOUT_SECONDS = 4
CACHE_SECONDS = 15
REGULATION_PERIODS = 4

GAME_ID_PATTERN = re.compile(r"^\d{10}$")
ISO_CLOCK_PATTERN = re.compile(r"^PT(\d+)M(\d+(?:\.\d+)?)S$")
POSTPONED_PATTERN = re.compile(r"\b(ppd|postponed|cancell?ed)\b", re.I)


class UpstreamError(Exception):
    """No upstream returned a usable scoreboard."""


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def period_label(period):
    if period <= REGULATION_PERIODS:
        return f"Q{period}"
    extra = period - REGULATION_PERIODS
    return "OT" if extra == 1 else f"{extra}OT"


def final_label(period):
    if period is None or period <= REGULATION_PERIODS:
        return "Final"
    return "Final/" + period_label(period)


def live_clock(period, iso_clock, status_text):
    """'Q3 4:40', 'OT 1:30', 'Half'; just the period when the clock is missing."""
    if status_text.lower().startswith("half"):
        return "Half"
    if not period:
        return None
    label = period_label(period)
    match = ISO_CLOCK_PATTERN.match(iso_clock.strip()) if isinstance(iso_clock, str) else None
    if not match:
        return label
    minutes, seconds = int(match.group(1)), int(float(match.group(2)))
    return f"{label} {minutes}:{seconds:02d}"


def map_game(raw):
    """One upstream game as a LIVE_SCORES game, or None when it has no valid id."""
    if not isinstance(raw, dict):
        return None
    game_id = str(raw.get("gameId") or "")
    if not GAME_ID_PATTERN.match(game_id):
        return None
    status_code = _int(raw.get("gameStatus"))
    status_text = str(raw.get("gameStatusText") or "").strip()
    period = _int(raw.get("period")) or None
    home, away = raw.get("homeTeam") or {}, raw.get("awayTeam") or {}
    game = {"game_id": game_id, "status": "scheduled", "period": None, "clock": None,
            "home_score": None, "away_score": None, "postponed": False}

    if POSTPONED_PATTERN.search(status_text):
        game.update(status="postponed", postponed=True)
    elif status_code == 3:
        game.update(status="final", period=period, clock=final_label(period))
    elif status_code == 2:
        game.update(status="live", period=period,
                    clock=live_clock(period, raw.get("gameClock"), status_text))
    if game["status"] in ("live", "final"):
        game["home_score"] = _int(home.get("score") if isinstance(home, dict) else None)
        game["away_score"] = _int(away.get("score") if isinstance(away, dict) else None)
    return game


def parse_scoreboard(data):
    """The upstream JSON as {"game_date": "YYYY-MM-DD", "games": [...]}; ValueError if malformed."""
    board = data.get("scoreboard") if isinstance(data, dict) else None
    if not isinstance(board, dict) or not isinstance(board.get("games"), list):
        raise ValueError("no scoreboard.games")
    game_date = date.fromisoformat(str(board.get("gameDate") or "")[:10]).isoformat()
    games = [g for g in (map_game(raw) for raw in board["games"]) if g is not None]
    return {"game_date": game_date, "games": games}


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LiveScoreboard:
    """The shared, cached scoreboard snapshot.

    get() returns (snapshot, stale). snapshot is {"game_date", "games", "fetched_at",
    "source"} from the last successful fetch, or None if none has succeeded yet; stale is
    True when the latest fetch attempt failed.
    """

    def __init__(self, upstreams=UPSTREAMS, http_get=None, clock=time.monotonic,
                 cache_seconds=CACHE_SECONDS, timeout=TIMEOUT_SECONDS):
        self._upstreams = list(upstreams)
        self._http_get = http_get or requests.get
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._timeout = timeout
        self._lock = threading.Lock()
        self._snapshot = None
        self._failed = False
        self._checked_at = None

    def get(self):
        with self._lock:
            now = self._clock()
            if self._checked_at is None or now - self._checked_at >= self._cache_seconds:
                try:
                    self._snapshot = self._fetch()
                    self._failed = False
                except UpstreamError:
                    self._failed = True
                # Failures are cached too, so a dead upstream costs one timeout per window.
                self._checked_at = self._clock()
            return self._snapshot, self._failed

    def _fetch(self):
        for index, (source, url) in enumerate(self._upstreams):
            try:
                response = self._http_get(url, headers=REQUEST_HEADERS, timeout=self._timeout)
                if response.status_code != 200:
                    continue
                board = parse_scoreboard(response.json())
            except (requests.RequestException, ValueError, TypeError, AttributeError):
                continue
            if index:  # remember the host that answered
                self._upstreams.insert(0, self._upstreams.pop(index))
            return dict(board, fetched_at=utc_now_iso(), source=source)
        raise UpstreamError("no live scoreboard upstream answered")
