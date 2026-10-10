"""Official NBA injury report snapshots: fetch, archive, parse, match, store, query.

CLI (run from the repo root):
    python -m src.injuries --snapshot                 # scheduler tick: archive every new report of the last few hours
    python -m src.injuries --backfill-from 2025-10-21 [--to 2026-04-12] [--slots 05PM 01PM]
    python -m src.injuries --reparse                  # re-ingest every cached PDF (after a parser fix)
    python -m src.injuries --rematch                  # fill missing player_id/game_id (after alias fixes)
    python -m src.injuries --ingest-file PATH.pdf     # ingest one PDF (fixtures, manual checks)
    python -m src.injuries --latest GAME_ID --as-of 2026-10-21T19:00-04:00
    python -m src.injuries --push-supabase [--yes]    # copy local rows to Supabase (dry run without --yes)

Storage. Until migrations/0001_injury_snapshots.sql is applied, rows go to a local append-only SQLite sink
(data/injuries/injury_snapshots.sqlite, git-ignored) with the same columns and unique key as the Supabase
table. Every downloaded PDF is cached in data/raw/injury_reports/ (git-ignored): that cache is the
irreplaceable archive, and every other table can be rebuilt from it with --reparse.

A failed snapshot never fails the pipeline: --snapshot logs the error and exits 0 (use --strict to get
a nonzero exit code when debugging).
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

if __package__ in (None, "", "src"):
    # `python -m src.injuries` and `python src/injuries.py`: the src modules import each other flat.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

import config  # noqa: E402
from injury_report_pdf import (  # noqa: E402
    InjuryReportParseError,
    parse_game_date,
    parse_pdf,
    slot_names,
    slot_time_from_name,
)
from player_names import NameResolver, normalize_name  # noqa: E402

ET = ZoneInfo(config.INJURY_REPORT_TZ)
SNAPSHOT_COLUMNS = [
    "captured_at", "report_time", "game_id", "game_date", "game_time_et", "matchup", "team_id",
    "player_id", "player_name_raw", "status_raw", "status", "reason", "source", "raw_file",
]
CONFLICT_COLUMNS = ["source", "report_time", "team_id", "player_name_raw"]
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) nba-predictor injury archiver"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def utc_iso(dt: datetime) -> str:
    """Canonical timestamp text: UTC, seconds precision, '+00:00' suffix (sorts lexicographically)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_as_of(value) -> datetime:
    """datetime or ISO text; naive values are read as US Eastern wall time (the report's zone)."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt


def normalize_status(raw: str | None) -> tuple[str, bool]:
    """Map a raw status string to (normalized status, known?). Unknown strings use the fallback."""
    text = " ".join(str(raw or "").replace("–", "-").split()).strip(" .:;").lower()
    if text in config.INJURY_STATUS_MAP:
        return config.INJURY_STATUS_MAP[text], True
    for key in sorted(config.INJURY_STATUS_MAP, key=len, reverse=True):
        if text.startswith(key + " ") or text.startswith(key + "(") or text.startswith(key + " -"):
            return config.INJURY_STATUS_MAP[key], True
    return config.INJURY_STATUS_FALLBACK, False


# ---------------------------------------------------------------------------
# Teams, schedule, players
# ---------------------------------------------------------------------------

def _teams():
    from nba_api.stats.static import teams

    return teams.get_teams()


def team_lookup():
    """(by_nickname_key, by_tricode) maps to team_id, built from nba_api's bundled static team list."""
    by_nick, by_tri = {}, {}
    for t in _teams():
        by_nick[normalize_name(t["nickname"]).replace(" ", "")] = int(t["id"])
        by_tri[t["abbreviation"].upper()] = int(t["id"])
    return by_nick, by_tri


def resolve_team(team_name: str | None, by_nick: dict) -> int | None:
    """Team id from a printed team name by its nickname suffix; the longest suffix wins (Hornets, not Nets)."""
    key = normalize_name(team_name or "").replace(" ", "")
    hits = sorted((nick for nick in by_nick if key and key.endswith(nick)), key=len, reverse=True)
    return by_nick[hits[0]] if hits else None


def _cache_is_fresh(path: str, max_age_hours: float) -> bool:
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_hours * 3600


def _schedule_from_v2(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "game_id": df["gameId"].astype(str).str.zfill(10),
        "game_date": df["gameDateEst"].astype(str).str[:10],
        "home_team_id": pd.to_numeric(df["homeTeam_teamId"], errors="coerce"),
        "away_team_id": pd.to_numeric(df["awayTeam_teamId"], errors="coerce"),
        "tip_utc": df["gameDateTimeUTC"].astype(str) if "gameDateTimeUTC" in df else None,
    }).dropna(subset=["home_team_id", "away_team_id"])


def _schedule_from_gamelog(df: pd.DataFrame) -> pd.DataFrame:
    """LeagueGameLog (team mode) rows -> one row per game; MATCHUP 'BOS vs. NYK' marks the home row."""
    df = df.copy()
    df["game_id"] = df["GAME_ID"].astype(str).str.zfill(10)
    home = df[df["MATCHUP"].str.contains("vs.", regex=False)][["game_id", "GAME_DATE", "TEAM_ID"]]
    away = df[df["MATCHUP"].str.contains("@", regex=False)][["game_id", "TEAM_ID"]]
    out = home.merge(away, on="game_id", suffixes=("_home", "_away"))
    return pd.DataFrame({"game_id": out["game_id"], "game_date": out["GAME_DATE"].astype(str).str[:10],
                         "home_team_id": out["TEAM_ID_home"], "away_team_id": out["TEAM_ID_away"]})


def load_schedule(season: str, *, refresh_hours: float = 24.0) -> pd.DataFrame:
    """Season schedule (game_id zero-padded text, ET game_date, home/away team ids), cached in data/raw/.

    ScheduleLeagueV2 covers future games (live snapshots); LeagueGameLog (team mode, regular season and
    playoffs) is the fallback for past seasons. Cache refreshes after refresh_hours; a failed refresh
    falls back to the stale cache.
    """
    from nba_client import call_frames

    base = os.path.join(config.RAW_DIR, "nba_api")
    v2_path = os.path.join(base, f"schedule_{season}.json")
    try:
        from nba_api.stats.endpoints import scheduleleaguev2

        frames = call_frames(
            lambda: scheduleleaguev2.ScheduleLeagueV2(season=season, timeout=config.NBA_API_TIMEOUT_SECONDS),
            cache_path=v2_path, refresh=not _cache_is_fresh(v2_path, refresh_hours))
        v2 = _schedule_from_v2(frames[0])
    except Exception as exc:
        print(f"  ScheduleLeagueV2 failed for {season} ({type(exc).__name__}); trying cache / game log")
        empty = pd.DataFrame(columns=["game_id", "game_date", "home_team_id", "away_team_id"])
        v2 = _schedule_from_v2(call_frames(lambda: None, cache_path=v2_path)[0]) if os.path.exists(v2_path) else empty
    from nba_client import season_for_date

    if season_for_date(date.today()) == season and not v2.empty:
        return v2          # current season: the schedule is the source; game logs only cover played games
    # Past seasons: the V2 schedule misses rescheduled (COVID) and bubble/playoff games, so union it with the
    # game logs (regular season + playoffs), which carry the dates the games were actually played.
    from nba_api.stats.endpoints import leaguegamelog

    parts = []
    for season_type in ("Regular Season", "Playoffs"):
        path = os.path.join(base, f"teamlog_{season}_{season_type.replace(' ', '')}.json")
        try:
            frames = call_frames(lambda st=season_type: leaguegamelog.LeagueGameLog(
                season=season, player_or_team_abbreviation="T", season_type_all_star=st,
                timeout=config.NBA_API_TIMEOUT_SECONDS), cache_path=path)
        except Exception as exc:
            print(f"  LeagueGameLog {season} {season_type} failed ({type(exc).__name__})")
            continue
        if not frames[0].empty:
            parts.append(_schedule_from_gamelog(frames[0]))
    out = pd.concat([v2] + parts, ignore_index=True)
    return out.drop_duplicates(subset=["game_date", "home_team_id", "away_team_id"], keep="last")


def load_player_candidates(*, refresh_hours: float = 24.0) -> list[dict]:
    """nba_api CommonAllPlayers (all seasons) as resolver rows. Stale cache is used if the refresh fails.

    Phase 1 replaces this with the player_aliases table; NameResolver.from_rows takes either.
    """
    from nba_api.stats.endpoints import commonallplayers

    from nba_client import call_frames

    path = os.path.join(config.RAW_DIR, "nba_api", "common_all_players.json")
    try:
        frames = call_frames(
            lambda: commonallplayers.CommonAllPlayers(is_only_current_season=0, league_id="00",
                                                      timeout=config.NBA_API_TIMEOUT_SECONDS),
            cache_path=path, refresh=not _cache_is_fresh(path, refresh_hours),
        )
    except Exception as exc:
        if not os.path.exists(path):
            print(f"  player list unavailable ({type(exc).__name__}); names stay unmatched")
            return []
        from nba_client import frames_from_json

        with open(path, encoding="utf-8") as fh:
            frames = frames_from_json(fh.read())
    df = frames[0]
    return [
        {"name": r["DISPLAY_FIRST_LAST"], "player_id": int(r["PERSON_ID"]),
         "team_id": int(r["TEAM_ID"]) if str(r.get("TEAM_ID") or "0") not in ("0", "") else None,
         "is_active": str(r.get("ROSTERSTATUS")) == "1"}
        for r in df.to_dict("records") if r.get("DISPLAY_FIRST_LAST")
    ]


@dataclass
class Matchers:
    resolver: NameResolver
    by_nick: dict
    by_tri: dict
    schedules: dict = field(default_factory=dict)       # season -> {(date, home_id, away_id): game_id}
    schedule_loader: object = None

    def game_id(self, game_date: date | None, matchup: str | None) -> str | None:
        if game_date is None or not matchup or "@" not in matchup:
            return None
        away, home = (s.strip().upper() for s in matchup.split("@", 1))
        home_id, away_id = self.by_tri.get(home), self.by_tri.get(away)
        if home_id is None or away_id is None:
            return None
        from nba_client import season_for_date

        season = season_for_date(game_date)
        if season not in self.schedules:
            index = {}
            loader = self.schedule_loader or load_schedule
            try:
                sched = loader(season)
                for r in sched.to_dict("records"):
                    index[(r["game_date"], int(r["home_team_id"]), int(r["away_team_id"]))] = r["game_id"]
            except Exception as exc:
                print(f"  schedule unavailable for {season} ({type(exc).__name__}); game_id left null")
            self.schedules[season] = index
        return self.schedules[season].get((game_date.isoformat(), home_id, away_id))


def default_matchers() -> Matchers:
    """Names resolve against players + player_aliases (phase 1 tables, local store or Supabase); if those are
    empty or unavailable, against the cached nba_api CommonAllPlayers list. Manual fixes for names that stay
    unmatched go into player_aliases (provider 'nba_injury_report' or 'manual')."""
    by_nick, by_tri = team_lookup()
    rows: list[dict] = []
    try:
        from collect_players import resolver_rows

        rows = resolver_rows()
    except Exception as exc:
        print(f"  player_aliases unavailable ({type(exc).__name__}); using the nba_api player list")
    if not rows:
        rows = load_player_candidates()
    return Matchers(NameResolver.from_rows(rows), by_nick, by_tri)


# ---------------------------------------------------------------------------
# Local append-only sink
# ---------------------------------------------------------------------------

SCHEMA = """
create table if not exists injury_snapshots (
  snapshot_id      integer primary key autoincrement,
  captured_at      text not null,
  report_time      text not null,
  game_id          text,
  game_date        text not null,
  game_time_et     text,
  matchup          text,
  team_id          integer not null,
  player_id        integer,
  player_name_raw  text not null,
  status_raw       text not null,
  status           text not null,
  reason           text,
  source           text not null,
  raw_file         text,
  unique (source, report_time, team_id, player_name_raw)
);
create index if not exists injury_snapshots_game_idx on injury_snapshots (game_id, report_time);
create table if not exists injury_reports (
  raw_file     text primary key,
  source       text not null,
  report_time  text,
  captured_at  text not null,
  ingested_at  text not null,
  n_rows       integer, n_inserted integer, n_unmatched integer, n_not_submitted integer,
  warnings     text
);
create table if not exists injury_unmatched (
  report_time      text not null,
  kind             text not null,          -- 'player' | 'team' | 'game'
  team_name        text,
  team_id          integer,
  player_name_raw  text,
  game_date        text,
  matchup          text,
  unique (report_time, kind, team_name, player_name_raw, matchup)
);
create table if not exists injury_fetch_misses (
  slot        text primary key,
  checked_at  text not null
);
create table if not exists injury_events (
  logged_at  text not null,
  kind       text not null,
  detail     text
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or config.INJURY_LOCAL_DB
    if path != ":memory:":
        os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def log_event(conn: sqlite3.Connection, kind: str, detail: str) -> None:
    conn.execute("insert into injury_events values (?, ?, ?)",
                 (utc_iso(datetime.now(timezone.utc)), kind, detail[:2000]))


# ---------------------------------------------------------------------------
# Ingest one parsed report
# ---------------------------------------------------------------------------

def build_rows(parsed, *, raw_file: str | None, captured_at: datetime, matchers: Matchers,
               fallback_report_time_et: datetime | None = None):
    """Turn a ParsedReport into snapshot rows plus unmatched records and unknown statuses."""
    report_et = parsed.report_time_et or fallback_report_time_et
    if report_et is None:
        raise InjuryReportParseError("report time missing from header and file name")
    report_time = utc_iso(report_et.replace(tzinfo=ET))
    rows, unmatched, unknown = [], [], []
    for r in parsed.rows:
        gdate = parse_game_date(r.get("game_date"))
        team_id = resolve_team(r.get("team"), matchers.by_nick)
        if team_id is None or gdate is None:
            unmatched.append({"report_time": report_time, "kind": "team", "team_name": r.get("team"),
                              "team_id": None, "player_name_raw": r.get("player"),
                              "game_date": r.get("game_date"), "matchup": r.get("matchup")})
            continue
        status, known = normalize_status(r.get("status"))
        if not known:
            unknown.append(r.get("status"))
        match = matchers.resolver.resolve(r["player"], team_id)
        game_id = matchers.game_id(gdate, r.get("matchup"))
        if match.player_id is None:
            unmatched.append({"report_time": report_time, "kind": "player", "team_name": r.get("team"),
                              "team_id": team_id, "player_name_raw": r["player"],
                              "game_date": gdate.isoformat(), "matchup": r.get("matchup")})
        if game_id is None:
            unmatched.append({"report_time": report_time, "kind": "game", "team_name": r.get("team"),
                              "team_id": team_id, "player_name_raw": None,
                              "game_date": gdate.isoformat(), "matchup": r.get("matchup")})
        rows.append({
            "captured_at": utc_iso(captured_at),
            "report_time": report_time,
            "game_id": game_id,
            "game_date": gdate.isoformat(),
            "game_time_et": r.get("game_time"),
            "matchup": r.get("matchup"),
            "team_id": team_id,
            "player_id": match.player_id,
            "player_name_raw": r["player"],
            "status_raw": r.get("status") or "",
            "status": status,
            "reason": r.get("reason"),
            "source": config.INJURY_SOURCE,
            "raw_file": raw_file,
        })
    return rows, unmatched, unknown


def store_rows(conn: sqlite3.Connection, rows: list[dict], unmatched: list[dict]) -> int:
    """Append-only insert; existing (source, report_time, team_id, player_name_raw) rows are left alone."""
    before = conn.total_changes
    conn.executemany(
        f"insert or ignore into injury_snapshots ({', '.join(SNAPSHOT_COLUMNS)}) "
        f"values ({', '.join('?' for _ in SNAPSHOT_COLUMNS)})",
        [tuple(r[c] for c in SNAPSHOT_COLUMNS) for r in rows],
    )
    inserted = conn.total_changes - before
    conn.executemany(
        "insert or ignore into injury_unmatched values (?, ?, ?, ?, ?, ?, ?)",
        [(u["report_time"], u["kind"], u["team_name"], u["team_id"], u["player_name_raw"],
          u["game_date"], u["matchup"]) for u in unmatched],
    )
    return inserted


def ingest_pdf(conn: sqlite3.Connection, path: str, matchers: Matchers, *,
               captured_at: datetime | None = None) -> dict:
    raw_file = os.path.basename(path)
    if captured_at is None:
        captured_at = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    stem = os.path.splitext(raw_file)[0].replace("Injury-Report_", "")
    parsed = parse_pdf(path)
    rows, unmatched, unknown = build_rows(parsed, raw_file=raw_file, captured_at=captured_at,
                                          matchers=matchers, fallback_report_time_et=slot_time_from_name(stem))
    inserted = store_rows(conn, rows, unmatched)
    for status in sorted(set(unknown)):
        print(f"  unknown injury status {status!r} -> {config.INJURY_STATUS_FALLBACK} (add it to INJURY_STATUS_MAP)")
        log_event(conn, "unknown_status", f"{raw_file}: {status}")
    for w in parsed.warnings:
        log_event(conn, "parse_warning", f"{raw_file}: {w}")
    report_time = rows[0]["report_time"] if rows else None
    n_unmatched_players = sum(1 for u in unmatched if u["kind"] == "player")
    conn.execute(
        "insert or replace into injury_reports values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (raw_file, config.INJURY_SOURCE, report_time, utc_iso(captured_at), utc_iso(datetime.now(timezone.utc)),
         len(rows), inserted, n_unmatched_players, len(parsed.not_submitted), "; ".join(parsed.warnings)[:2000]),
    )
    conn.commit()
    return {"file": raw_file, "rows": len(rows), "inserted": inserted, "unmatched_players": n_unmatched_players,
            "unknown_statuses": sorted(set(unknown)), "not_submitted": len(parsed.not_submitted),
            "report_time": report_time}


def _unmatched_path_for(conn: sqlite3.Connection) -> str:
    db_file = conn.execute("pragma database_list").fetchone()[2]
    if db_file and os.path.abspath(db_file) != os.path.abspath(config.INJURY_LOCAL_DB):
        return os.path.join(os.path.dirname(db_file), "injury_unmatched.csv")
    return config.INJURY_UNMATCHED_CSV


def write_unmatched_report(conn: sqlite3.Connection, path: str | None = None) -> str | None:
    """Rewrite the injury_unmatched CSV: one line per distinct unmatched name/team/game, with counts.
    The CSV sits next to the SQLite sink (data/injuries/injury_unmatched.csv by default)."""
    path = path or _unmatched_path_for(conn)
    if not path:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cur = conn.execute(
        "select kind, team_name, team_id, player_name_raw, matchup, count(*) as n, "
        "min(report_time) as first_seen, max(report_time) as last_seen "
        "from injury_unmatched group by kind, team_name, team_id, player_name_raw, matchup "
        "order by kind, last_seen desc")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["kind", "team_name", "team_id", "player_name_raw", "matchup", "reports",
                         "first_seen", "last_seen"])
        for r in cur:
            writer.writerow(list(r))
    return path


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

_last_http = 0.0


def fetch_slot(slot: str, *, session=None, raw_dir: str | None = None) -> tuple[str, str | None]:
    """Download one report slot into the raw cache. Returns (state, path): state is
    'cached' (already archived), 'fetched', 'missing' (HTTP 403/404) or 'error'."""
    global _last_http
    raw_dir = raw_dir or config.INJURY_RAW_DIR
    filename = f"Injury-Report_{slot}.pdf"
    path = os.path.join(raw_dir, filename)
    if os.path.exists(path):
        return "cached", path
    import requests

    wait = config.INJURY_HTTP_MIN_INTERVAL_SECONDS - (time.monotonic() - _last_http)
    if wait > 0:
        time.sleep(wait)
    _last_http = time.monotonic()
    http = session or requests
    try:
        resp = http.get(config.INJURY_REPORT_URL.format(slot=slot), headers={"User-Agent": _USER_AGENT},
                        timeout=config.INJURY_HTTP_TIMEOUT_SECONDS)
    except Exception as exc:
        print(f"  fetch {slot}: {type(exc).__name__}")
        return "error", None
    if resp.status_code in (403, 404):
        return "missing", None
    if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
        print(f"  fetch {slot}: HTTP {resp.status_code}")
        return "error", None
    os.makedirs(raw_dir, exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(resp.content)
    os.replace(tmp, path)
    return "fetched", path


def snapshot_slots(now_et: datetime, lookback_hours: float) -> list[str]:
    """Slot names from (now - lookback) up to now, oldest first, on the 15-minute grid."""
    end = now_et.replace(minute=now_et.minute // 15 * 15, second=0, microsecond=0)
    start = end - timedelta(hours=lookback_hours)
    names, t = [], start
    while t <= end:
        for name in slot_names(t):
            if name not in names:
                names.append(name)
        t += timedelta(minutes=15)
    return names


def _ingest_paths(conn, paths, matchers) -> list[dict]:
    results = []
    for path in paths:
        try:
            results.append(ingest_pdf(conn, path, matchers))
        except Exception as exc:
            print(f"  parse/ingest failed for {os.path.basename(path)}: {type(exc).__name__}: {exc}")
            log_event(conn, "ingest_error", f"{os.path.basename(path)}: {type(exc).__name__}: {exc}")
            conn.commit()
    return results


def _already_ingested(conn, path) -> bool:
    return conn.execute("select 1 from injury_reports where raw_file = ?",
                        (os.path.basename(path),)).fetchone() is not None


def snapshot(*, now: datetime | None = None, conn=None, matchers: Matchers | None = None,
             session=None, lookback_hours: float | None = None, mode: str | None = None) -> dict:
    """Archive and ingest the newest published report (mode 'latest', default) or every report in the
    lookback window that we do not have yet (mode 'all')."""
    now_et = (now or datetime.now(timezone.utc)).astimezone(ET).replace(tzinfo=None)
    lookback = config.INJURY_SNAPSHOT_LOOKBACK_HOURS if lookback_hours is None else lookback_hours
    mode = mode or config.INJURY_SNAPSHOT_MODE
    conn = conn or connect()
    new_paths, states = [], {}
    slots = snapshot_slots(now_et, lookback)
    for slot in (reversed(slots) if mode == "latest" else slots):
        state, path = fetch_slot(slot, session=session)
        states[state] = states.get(state, 0) + 1
        if path and not _already_ingested(conn, path):
            new_paths.append(path)
        if mode == "latest" and path:
            break
    results = []
    if new_paths:
        matchers = matchers or default_matchers()
        results = _ingest_paths(conn, new_paths, matchers)
        write_unmatched_report(conn)
    summary = {"slots": states, "ingested": results}
    print(f"injury snapshot ({mode}): slots {states}; ingested {len(results)} report(s), "
          f"{sum(r['inserted'] for r in results)} new row(s)")
    return summary


def backfill(start: date, end: date | None = None, *, slots=None, conn=None,
             matchers: Matchers | None = None, session=None) -> dict:
    """One or more report slots per day from start to end (inclusive). Resumable: cached PDFs are not
    re-downloaded, already-ingested files are skipped, and historical misses are remembered."""
    end = end or (datetime.now(ET).date() - timedelta(days=1))
    slots = list(slots or config.INJURY_BACKFILL_SLOTS_ET)
    conn = conn or connect()
    matchers = matchers or default_matchers()
    counts = {"fetched": 0, "cached": 0, "missing": 0, "error": 0, "known_missing": 0, "ingested": 0}
    day = start
    while day <= end:
        for slot_label in slots:
            when = slot_time_from_name(f"{day.isoformat()}_{slot_label}")
            if when is None:
                raise ValueError(f"bad slot label {slot_label!r} (use e.g. 05PM or 05_30PM)")
            for name in slot_names(when) or [f"{day.isoformat()}_{slot_label}"]:
                if conn.execute("select 1 from injury_fetch_misses where slot = ?", (name,)).fetchone():
                    counts["known_missing"] += 1
                    continue
                state, path = fetch_slot(name, session=session)
                counts[state] += 1
                if state == "missing" and day < datetime.now(ET).date() - timedelta(days=1):
                    conn.execute("insert or ignore into injury_fetch_misses values (?, ?)",
                                 (name, utc_iso(datetime.now(timezone.utc))))
                    conn.commit()
                if path and not _already_ingested(conn, path):
                    counts["ingested"] += len(_ingest_paths(conn, [path], matchers))
                if path:
                    break
        if day.day == 1 or day == end:
            print(f"  backfill through {day.isoformat()}: {counts}")
        day += timedelta(days=1)
    write_unmatched_report(conn)
    return counts


def rematch(*, conn=None, matchers: Matchers | None = None) -> dict:
    """Fill NULL player_id / game_id after the matchers improve (new aliases, overrides, schedule fixes).
    This is the one permitted change to stored snapshots: it only fills missing match keys and never
    touches statuses, times or names."""
    conn = conn or connect()
    matchers = matchers or default_matchers()
    rows = conn.execute("select snapshot_id, team_id, player_name_raw, game_date, matchup, player_id, game_id "
                        "from injury_snapshots where player_id is null or game_id is null").fetchall()
    filled = {"player_id": 0, "game_id": 0}
    for r in rows:
        if r["player_id"] is None:
            pid = matchers.resolver.resolve(r["player_name_raw"], r["team_id"]).player_id
            if pid is not None:
                conn.execute("update injury_snapshots set player_id = ? where snapshot_id = ? and player_id is null",
                             (pid, r["snapshot_id"]))
                filled["player_id"] += 1
        if r["game_id"] is None:
            gid = matchers.game_id(date.fromisoformat(r["game_date"]), r["matchup"])
            if gid is not None:
                conn.execute("update injury_snapshots set game_id = ? where snapshot_id = ? and game_id is null",
                             (gid, r["snapshot_id"]))
                filled["game_id"] += 1
    conn.execute("delete from injury_unmatched where kind = 'player' and exists (select 1 from injury_snapshots s "
                 "where s.report_time = injury_unmatched.report_time and s.team_id = injury_unmatched.team_id "
                 "and s.player_name_raw = injury_unmatched.player_name_raw and s.player_id is not null)")
    conn.execute("delete from injury_unmatched where kind = 'game' and exists (select 1 from injury_snapshots s "
                 "where s.report_time = injury_unmatched.report_time and s.team_id = injury_unmatched.team_id "
                 "and s.matchup = injury_unmatched.matchup and s.game_id is not null)")
    conn.commit()
    write_unmatched_report(conn)
    print(f"rematch: {len(rows)} rows with missing keys; filled {filled}")
    return filled


def reparse(*, conn=None, matchers: Matchers | None = None, raw_dir: str | None = None) -> int:
    """Re-ingest every cached PDF (idempotent: existing rows are kept, new ones added)."""
    raw_dir = raw_dir or config.INJURY_RAW_DIR
    conn = conn or connect()
    matchers = matchers or default_matchers()
    paths = sorted(os.path.join(raw_dir, f) for f in os.listdir(raw_dir) if f.endswith(".pdf")) \
        if os.path.isdir(raw_dir) else []
    results = _ingest_paths(conn, paths, matchers)
    write_unmatched_report(conn)
    return len(results)


# ---------------------------------------------------------------------------
# Point-in-time query
# ---------------------------------------------------------------------------

def newest_per_player(df: pd.DataFrame, as_of) -> pd.DataFrame:
    """Point-in-time status rows: only rows with report_time <= as_of count. For each team, the newest
    report that lists the team is the current one; a player listed earlier but missing from it has been
    taken off the report and is dropped (treated as no report). Unmatched players are keyed by raw name."""
    if df.empty:
        return df
    cutoff = utc_iso(parse_as_of(as_of))
    df = df[df["report_time"].astype(str) <= cutoff].copy()
    if df.empty:
        return df
    team_latest = df.groupby("team_id")["report_time"].transform("max")
    df = df[df["report_time"] == team_latest]
    pid = df["player_id"].astype("Int64").astype(str)
    df = df.assign(_key=pid.where(df["player_id"].notna(),
                                  "name:" + df["team_id"].astype(str) + ":" + df["player_name_raw"].astype(str)))
    df = df.sort_values(["_key", "report_time"]).groupby("_key", as_index=False).tail(1)
    return df.drop(columns="_key").sort_values(["team_id", "player_name_raw"]).reset_index(drop=True)


def latest_status(game_id: str, as_of, *, conn=None, backend: str = "local") -> pd.DataFrame:
    """Newest snapshot row per player for game_id at or before as_of (report_time <= as_of).

    backend='local' reads the SQLite sink; backend='supabase' reads public.injury_snapshots
    (available once migrations/0001_injury_snapshots.sql is applied).
    """
    from database import normalize_game_id

    game_id = normalize_game_id(game_id)
    cutoff = utc_iso(parse_as_of(as_of))
    if backend == "supabase":
        from database import select_rows

        df = select_rows("injury_snapshots", filters=[("game_id", "eq", game_id), ("report_time", "lte", cutoff)],
                         order_by=["report_time", "snapshot_id"])
        if not df.empty:
            df["report_time"] = df["report_time"].map(lambda v: utc_iso(parse_as_of(v)))
    else:
        conn = conn or connect()
        df = pd.read_sql_query(
            "select * from injury_snapshots where game_id = ? and report_time <= ? order by report_time",
            conn, params=(game_id, cutoff))
    return newest_per_player(df, as_of)


# ---------------------------------------------------------------------------
# Push the local sink to Supabase (after Noel applies the migration)
# ---------------------------------------------------------------------------

def push_to_supabase(*, conn=None, dry_run: bool = True, batch_size: int = 500) -> int:
    from database import upsert_rows

    conn = conn or connect()
    df = pd.read_sql_query(f"select {', '.join(SNAPSHOT_COLUMNS)} from injury_snapshots order by snapshot_id", conn)
    print(f"local injury_snapshots rows: {len(df)}")
    if dry_run or df.empty:
        print("dry run: nothing written (pass --yes to push)")
        return 0
    rows = df.astype(object).where(df.notna(), None).to_dict("records")
    upsert_rows("injury_snapshots", rows, conflict_columns=CONFLICT_COLUMNS, batch_size=batch_size,
                ignore_duplicates=True)
    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.injuries", description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", action="store_true")
    mode.add_argument("--backfill-from", type=date.fromisoformat)
    mode.add_argument("--reparse", action="store_true")
    mode.add_argument("--rematch", action="store_true", help="fill missing player_id/game_id in stored rows")
    mode.add_argument("--ingest-file")
    mode.add_argument("--latest", metavar="GAME_ID")
    mode.add_argument("--push-supabase", action="store_true")
    parser.add_argument("--to", type=date.fromisoformat)
    parser.add_argument("--slots", nargs="+")
    parser.add_argument("--as-of")
    parser.add_argument("--now", help="override the clock for --snapshot (ISO time)")
    parser.add_argument("--lookback-hours", type=float)
    parser.add_argument("--all-slots", action="store_true",
                        help="--snapshot archives every report in the lookback window, not just the newest")
    parser.add_argument("--yes", action="store_true", help="really write for --push-supabase")
    parser.add_argument("--strict", action="store_true", help="nonzero exit code on snapshot errors")
    parser.add_argument("--db", help="local SQLite sink path (default data/injuries/injury_snapshots.sqlite)")
    args = parser.parse_args(argv)

    try:
        from console import force_utf8_stdio

        force_utf8_stdio()
    except Exception:
        pass

    if args.snapshot:
        conn = None
        try:
            conn = connect(args.db)
            snapshot(now=parse_as_of(args.now) if args.now else None, conn=conn,
                     lookback_hours=args.lookback_hours, mode="all" if args.all_slots else None)
        except Exception as exc:  # never fail the pipeline
            print(f"injury snapshot failed: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            return 1 if args.strict else 0
        finally:
            if conn is not None:
                conn.close()
        return 0
    conn = connect(args.db)
    try:
        if args.backfill_from:
            print(backfill(args.backfill_from, args.to, slots=args.slots, conn=conn))
        elif args.reparse:
            print(f"re-ingested {reparse(conn=conn)} cached report(s)")
        elif args.rematch:
            rematch(conn=conn)
        elif args.ingest_file:
            print(ingest_pdf(conn, args.ingest_file, default_matchers()))
            write_unmatched_report(conn)
        elif args.latest:
            if not args.as_of:
                parser.error("--latest needs --as-of")
            df = latest_status(args.latest, args.as_of, conn=conn)
            cols = ["report_time", "team_id", "player_id", "player_name_raw", "status", "reason"]
            print(df[cols].to_string(index=False) if not df.empty else "no rows")
        elif args.push_supabase:
            dotenv_path = os.getenv("NBA_DOTENV_PATH")
            if dotenv_path:
                from dotenv import load_dotenv

                load_dotenv(dotenv_path)
            print(f"pushed {push_to_supabase(conn=conn, dry_run=not args.yes)} row(s)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
