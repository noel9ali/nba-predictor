"""Append-only archive of every Odds API response the pipeline pays for (local sqlite, git-ignored).

    data/odds_history/odds_history.sqlite   (override with NBA_ODDS_HISTORY_DB; tests do)

Why: the live tables keep only the best price of five preferred books per side and no tip time, so model-vs-market and
line-movement questions cannot be answered later. This archive keeps EVERY bookmaker in the response, every market in
it, the event's commence_time and the response's quota headers, one row per (capture, event, book, market, side).
Nothing here makes a request: it stores a response that was already fetched, so it costs zero credits.

Tables
- odds_calls     one row per Odds API response: captured_at (UTC, taken when the response arrived), purpose
                 ('pricing' | 'closing' | 'debug'), http status, number of events, x-requests-remaining / -used / -last.
- odds_snapshots one row per price: captured_at, event_id (Odds API id), commence_time, home_team, away_team,
                 nba_game_id (NULL until link_game_ids matches it to the scoreboard), bookmaker_key / title, market,
                 selection ('home' | 'away' | other outcome name lower-cased), price_american, market_last_update
                 (the book's own timestamp for that price, when the API provides it).
                 Primary key (captured_at, event_id, bookmaker_key, market, selection): a later capture of the same game
                 is a NEW row (a time series); re-archiving the same response is a no-op (idempotent).
- closing_captures  ledger of tip times that already had a closing call (so a 15-minute tick never repeats it).

Everything is non-fatal: safe_archive() never raises, a failure prints an ERROR line and the prediction run goes on.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import config

SCHEMA = """
create table if not exists odds_calls (
  call_id integer primary key autoincrement,
  captured_at text not null, purpose text not null, http_status integer, n_events integer,
  requests_remaining integer, requests_used integer, requests_last integer,
  sport text, regions text, markets text,
  unique (captured_at, purpose));
create table if not exists odds_snapshots (
  captured_at text not null, event_id text not null, commence_time text, home_team text, away_team text,
  nba_game_id text, bookmaker_key text not null, bookmaker_title text, market text not null, selection text not null,
  price_american integer, market_last_update text,
  primary key (captured_at, event_id, bookmaker_key, market, selection));
create index if not exists odds_snapshots_event_idx on odds_snapshots (event_id, captured_at);
create index if not exists odds_snapshots_game_idx on odds_snapshots (nba_game_id, captured_at);
create table if not exists closing_captures (
  tip_utc text primary key, captured_at text not null, game_ids text);
"""


def db_path() -> str:
    return os.getenv("NBA_ODDS_HISTORY_DB") or config.ODDS_HISTORY_DB


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or db_path()
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def now_utc_ms() -> str:
    """UTC capture stamp with millisecond precision, e.g. 2026-10-20T21:15:03.412Z."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def header_values(headers) -> dict:
    """x-requests-remaining / used / last from a requests-style (case-insensitive) mapping."""
    get = (lambda k: headers.get(k)) if headers is not None else (lambda k: None)
    return {"requests_remaining": _int(get("x-requests-remaining")), "requests_used": _int(get("x-requests-used")),
            "requests_last": _int(get("x-requests-last"))}


def snapshot_rows(events, captured_at: str) -> list[dict]:
    """Every bookmaker, market and outcome of an odds response as flat rows (no filtering by book)."""
    rows = []
    for ev in events or []:
        event_id = str(ev.get("id") or "")
        home, away = ev.get("home_team"), ev.get("away_team")
        if not event_id:
            continue
        for book in ev.get("bookmakers") or []:
            for market in book.get("markets") or []:
                for out in market.get("outcomes") or []:
                    name = out.get("name")
                    selection = "home" if name == home else "away" if name == away else str(name or "").lower()
                    price = out.get("price")
                    rows.append({
                        "captured_at": captured_at, "event_id": event_id, "commence_time": ev.get("commence_time"),
                        "home_team": home, "away_team": away, "nba_game_id": None,
                        "bookmaker_key": str(book.get("key") or book.get("title") or ""),
                        "bookmaker_title": book.get("title"), "market": str(market.get("key") or ""),
                        "selection": selection, "price_american": _int(price),
                        "market_last_update": market.get("last_update") or book.get("last_update")})
    return rows


def archive_response(events, headers, captured_at: str, *, purpose: str = "pricing", http_status: int = 200,
                     sport: str | None = None, regions: str | None = None, markets: str | None = None,
                     conn: sqlite3.Connection | None = None) -> dict:
    """Store one response. Returns {'calls': 0|1, 'rows': inserted rows}. Idempotent per (captured_at, ...)."""
    own = conn is None
    conn = conn or connect()
    try:
        rows = snapshot_rows(events if isinstance(events, list) else [], captured_at)
        h = header_values(headers)
        cur = conn.execute(
            "insert or ignore into odds_calls (captured_at, purpose, http_status, n_events, requests_remaining, "
            "requests_used, requests_last, sport, regions, markets) values (?,?,?,?,?,?,?,?,?,?)",
            (captured_at, purpose, http_status, len(events) if isinstance(events, list) else 0,
             h["requests_remaining"], h["requests_used"], h["requests_last"], sport, regions, markets))
        calls = cur.rowcount
        cols = ["captured_at", "event_id", "commence_time", "home_team", "away_team", "nba_game_id", "bookmaker_key",
                "bookmaker_title", "market", "selection", "price_american", "market_last_update"]
        before = conn.total_changes
        conn.executemany(f"insert or ignore into odds_snapshots ({', '.join(cols)}) values ({', '.join('?' for _ in cols)})",
                         [tuple(r[c] for c in cols) for r in rows])
        conn.commit()
        return {"calls": calls, "rows": conn.total_changes - before}
    finally:
        if own:
            conn.close()


def safe_archive(events, headers, captured_at: str, **kwargs) -> dict | None:
    """archive_response that can never raise: a storage problem must not stop predictions."""
    if not config.ODDS_ARCHIVE_ENABLED:
        return None
    try:
        return archive_response(events, headers, captured_at, **kwargs)
    except Exception as exc:
        print(f"ERROR: could not archive the odds response: {type(exc).__name__}: {exc}")
        return None


def link_game_ids(games, *, conn: sqlite3.Connection | None = None, abbr_map: dict | None = None,
                  tolerance_hours: float = 4.0) -> int:
    """Fill nba_game_id on archived rows whose NULL id matches a scoreboard game: same home/away team names and a
    commence_time within tolerance_hours of the game's TIP_UTC. `games` has gameId, HOME/VISITOR_TEAM_ABBREVIATION
    and TIP_UTC (predict.games_from_scoreboard). Never raises; returns rows updated."""
    try:
        if games is None or len(games) == 0:
            return 0
        if abbr_map is None:
            from odds import ABBR_MAP as abbr_map
        own = conn is None
        conn = conn or connect()
        try:
            updated = 0
            for g in games.to_dict("records"):
                home, away = abbr_map.get(g.get("HOME_TEAM_ABBREVIATION")), abbr_map.get(g.get("VISITOR_TEAM_ABBREVIATION"))
                tip = _parse(g.get("TIP_UTC"))
                if not (home and away and g.get("gameId")):
                    continue
                lo = (tip - timedelta(hours=tolerance_hours)).isoformat() if tip else "0"
                hi = (tip + timedelta(hours=tolerance_hours)).isoformat() if tip else "9"
                cur = conn.execute(
                    "update odds_snapshots set nba_game_id = ? where nba_game_id is null and home_team = ? and away_team = ? "
                    "and replace(commence_time, 'Z', '+00:00') between ? and ?",
                    (str(g["gameId"]), home, away, lo.replace("Z", "+00:00"), hi.replace("Z", "+00:00")))
                updated += cur.rowcount
            conn.commit()
            return updated
        finally:
            if own:
                conn.close()
    except Exception as exc:
        print(f"ERROR: could not link odds archive rows to game ids: {type(exc).__name__}: {exc}")
        return 0


def _parse(value):
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Closing-line capture (flag config.ODDS_CLOSING_CAPTURE, default OFF)
# ---------------------------------------------------------------------------

def due_closing_tips(games, now=None, *, window=None, conn: sqlite3.Connection | None = None) -> list[str]:
    """Distinct TIP_UTC strings of scheduled games whose tip is within the closing window (default 2-17 minutes
    ahead) and that have no closing capture yet. Fails SAFE: if the ledger cannot be read, returns [] (no credit is
    spent when state is unknown)."""
    lo, hi = window or config.ODDS_CLOSING_WINDOW_MINUTES
    now = _parse(now) if now is not None else datetime.now(timezone.utc)
    if games is None or len(games) == 0 or "TIP_UTC" not in games.columns:
        return []
    try:
        own = conn is None
        conn = conn or connect()
        try:
            done = {r[0] for r in conn.execute("select tip_utc from closing_captures")}
        finally:
            if own:
                conn.close()
    except Exception as exc:
        print(f"Closing capture ledger unreadable ({type(exc).__name__}); no closing call made.")
        return []
    due = []
    for tip in sorted({str(t) for t in games["TIP_UTC"].dropna()}):
        ts = _parse(tip)
        if ts is None or tip in done:
            continue
        minutes = (ts - now).total_seconds() / 60.0
        if lo <= minutes <= hi:
            due.append(tip)
    return due


def mark_closing_done(tips, game_ids=None, *, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or connect()
    try:
        stamp = now_utc_ms()
        conn.executemany("insert or ignore into closing_captures (tip_utc, captured_at, game_ids) values (?,?,?)",
                         [(t, stamp, ",".join(map(str, game_ids or []))) for t in tips])
        conn.commit()
    finally:
        if own:
            conn.close()


def latest_requests_remaining(*, conn: sqlite3.Connection | None = None) -> int | None:
    """x-requests-remaining from the newest archived call that carried it (None when unknown)."""
    try:
        own = conn is None
        conn = conn or connect()
        try:
            row = conn.execute("select requests_remaining from odds_calls where requests_remaining is not null "
                               "order by captured_at desc limit 1").fetchone()
        finally:
            if own:
                conn.close()
        return row[0] if row else None
    except Exception:
        return None
