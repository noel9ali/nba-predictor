"""Player box scores (player_games), players and name aliases from nba_api.

    python src/collect_players.py              # incremental: games since the newest stored game_date
    python src/collect_players.py --backfill   # every season from PLAYER_FIRST_SEASON (resumable, cached)
    python src/collect_players.py --players    # refresh players + player_aliases only

One LeagueGameLog (player mode, regular season) call per season. Completed seasons are cached in
data/raw/nba_api/ and never re-fetched; writes are upserts on (game_id, player_id), so reruns change nothing.
Storage goes through player_store (local SQLite until the migration is applied).
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

if __package__ in (None, "", "src"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

import config  # noqa: E402
import player_store  # noqa: E402
from nba_client import call_frames, season_for_date  # noqa: E402
from player_names import normalize_name, to_first_last  # noqa: E402

STAT_COLUMNS = {
    "PTS": "pts", "REB": "reb", "OREB": "oreb", "DREB": "dreb", "AST": "ast", "STL": "stl", "BLK": "blk",
    "TOV": "tov", "PF": "pf", "FGM": "fgm", "FGA": "fga", "FG3M": "fg3m", "FG3A": "fg3a", "FTM": "ftm",
    "FTA": "fta", "PLUS_MINUS": "plus_minus",
}
_ISO_MIN = re.compile(r"^PT(?:(\d+)M)?(?:([\d.]+)S)?$")


def parse_minutes(value) -> float | None:
    """'34:12' -> 34.2, 'PT34M12.00S' -> 34.2, 28 -> 28.0, ''/None/NaN -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)
    text = str(value).strip()
    if not text:
        return None
    if ":" in text:
        mins, secs = text.split(":", 1)
        try:
            return round(int(mins) + float(secs) / 60.0, 4)
        except ValueError:
            return None
    m = _ISO_MIN.match(text)
    if m and (m.group(1) or m.group(2)):
        return round(int(m.group(1) or 0) + float(m.group(2) or 0) / 60.0, 4)
    try:
        return float(text)
    except ValueError:
        return None


def seasons_through(today: date) -> list[str]:
    first = int(config.PLAYER_FIRST_SEASON[:4])
    last = int(season_for_date(today)[:4])
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(first, last + 1)]


def _int_or_none(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return int(v)


def gamelog_to_rows(df: pd.DataFrame, season: str) -> list[dict]:
    """LeagueGameLog (player mode) frame -> player_games rows."""
    rows = []
    for r in df.to_dict("records"):
        row = {
            "game_id": str(r["GAME_ID"]).strip().zfill(10),
            "player_id": int(r["PLAYER_ID"]),
            "team_id": int(r["TEAM_ID"]),
            "game_date": str(r["GAME_DATE"])[:10],
            "season": season,
            "is_home": 1 if "vs." in str(r["MATCHUP"]) else 0,
            "started": None,
            "minutes": parse_minutes(r.get("MIN")),
        }
        for src, dst in STAT_COLUMNS.items():
            row[dst] = _int_or_none(r.get(src))
        rows.append(row)
    return rows


def fetch_season_log(season: str, *, date_from: str | None = None, refresh: bool = False) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguegamelog

    tag = f"_from{date_from}_{date.today().isoformat()}" if date_from else ""
    path = os.path.join(config.RAW_DIR, "nba_api", f"playerlog_{season}{tag}.json")
    current = season == season_for_date(date.today())
    frames = call_frames(
        lambda: leaguegamelog.LeagueGameLog(
            season=season, player_or_team_abbreviation="P", season_type_all_star="Regular Season",
            date_from_nullable=(datetime.strptime(date_from, "%Y-%m-%d").strftime("%m/%d/%Y") if date_from else ""),
            timeout=config.NBA_API_TIMEOUT_SECONDS),
        cache_path=path, refresh=refresh or (current and not date_from))
    return frames[0]


def collect_season(season: str, *, date_from: str | None = None, conn=None) -> int:
    df = fetch_season_log(season, date_from=date_from)
    rows = gamelog_to_rows(df, season) if not df.empty else []
    player_store.upsert("player_games", rows, conn=conn)
    print(f"  {season}{' from ' + date_from if date_from else ''}: {len(rows)} player-game rows")
    return len(rows)


def backfill(*, today: date | None = None, conn=None) -> dict:
    counts = {}
    for season in seasons_through(today or date.today()):
        try:
            counts[season] = collect_season(season, conn=conn)
        except Exception as exc:
            print(f"  {season} failed: {type(exc).__name__}: {exc}")
            counts[season] = None
    return counts


def max_game_date(*, conn=None) -> str | None:
    if player_store.backend() == "supabase" and conn is None:
        from database import select_rows

        df = select_rows("player_games", columns="game_date", order_by=[("game_date", True)], limit=1)
        return str(df["game_date"].iloc[0])[:10] if not df.empty else None
    row = (conn or player_store.connect()).execute("select max(game_date) from player_games").fetchone()
    return row[0] if row else None


def incremental(*, today: date | None = None, conn=None) -> int:
    """New games since the newest stored game_date (re-reads that day to catch late finishes)."""
    today = today or date.today()
    last = max_game_date(conn=conn)
    if not last:
        print("  player_games is empty: running the full backfill")
        return sum(v or 0 for v in backfill(today=today, conn=conn).values())
    season = season_for_date(today)
    if season_for_date(date.fromisoformat(last)) != season:
        # New season: finish the previous one, then start this one.
        prev = season_for_date(date.fromisoformat(last))
        collect_season(prev, date_from=last, conn=conn)
        return collect_season(season, conn=conn)
    return collect_season(season, date_from=last, conn=conn)


# ---------------------------------------------------------------------------
# players + player_aliases
# ---------------------------------------------------------------------------

def players_from_common_all(df: pd.DataFrame, *, now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """CommonAllPlayers -> (players rows, player_aliases rows). For duplicate display names the most recent
    player (highest TO_YEAR) keeps the alias; the clash is reported."""
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    players, aliases, clashes = [], {}, []
    for r in df.sort_values("TO_YEAR").to_dict("records"):
        pid = int(r["PERSON_ID"])
        full = str(r.get("DISPLAY_FIRST_LAST") or "").strip()
        if not full:
            continue
        last_first = str(r.get("DISPLAY_LAST_COMMA_FIRST") or "")
        if "," in last_first:
            last, first = (s.strip() for s in last_first.rsplit(",", 1))
        else:
            first, last = (full.split(" ", 1) + [""])[:2]
        players.append({"player_id": pid, "full_name": full, "first_name": first or None, "last_name": last or None,
                        "position": None, "birth_date": None, "is_active": 1 if str(r.get("ROSTERSTATUS")) == "1" else 0,
                        "updated_at": stamp})
        for provider, name in (("nba_api", full), ("normalized", normalize_name(full))):
            key = (provider, name)
            if key in aliases and aliases[key]["player_id"] != pid:
                clashes.append(f"{provider}:{name}")
            aliases[key] = {"provider": provider, "provider_name": name, "player_id": pid, "updated_at": stamp}
    if clashes:
        print(f"  {len(clashes)} alias name clashes resolved to the most recent player (e.g. {clashes[:3]})")
    return players, list(aliases.values())


def refresh_players(*, conn=None) -> tuple[int, int]:
    from nba_api.stats.endpoints import commonallplayers

    path = os.path.join(config.RAW_DIR, "nba_api", "common_all_players.json")
    fresh = os.path.exists(path) and (datetime.now().timestamp() - os.path.getmtime(path)) < 86400
    frames = call_frames(lambda: commonallplayers.CommonAllPlayers(
        is_only_current_season=0, league_id="00", timeout=config.NBA_API_TIMEOUT_SECONDS),
        cache_path=path, refresh=not fresh)
    players, aliases = players_from_common_all(frames[0])
    player_store.upsert("players", players, conn=conn)
    player_store.upsert("player_aliases", aliases, conn=conn)
    print(f"  players: {len(players)}, aliases: {len(aliases)}")
    return len(players), len(aliases)


def record_alias(provider: str, provider_name: str, player_id: int, *, conn=None) -> None:
    """Remember a successful match (for example an injury-report spelling) for future lookups."""
    player_store.upsert("player_aliases", [{
        "provider": provider, "provider_name": provider_name, "player_id": int(player_id),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}], conn=conn)


def resolver_rows(*, conn=None) -> list[dict]:
    """Rows for player_names.NameResolver built from players + player_aliases, with each player's most recent
    team from player_games. Empty when the tables are empty (callers fall back to nba_api)."""
    players = player_store.read("players", columns="player_id, full_name, is_active", conn=conn)
    if players.empty:
        return []
    teams = player_store.query(
        "select player_id, team_id from player_games pg where game_date = "
        "(select max(game_date) from player_games p2 where p2.player_id = pg.player_id)",
        conn=conn) if (player_store.backend() == "local" or conn is not None) else pd.DataFrame()
    team_of = dict(zip(teams["player_id"], teams["team_id"])) if not teams.empty else {}
    # "Active" for tie-breaking = on a roster now or has played since the first collected season, so
    # 'Glenn Robinson III' beats the retired 'Glenn Robinson' when the suffix is dropped.
    active = {int(p): bool(a) or int(p) in team_of for p, a in zip(players["player_id"], players["is_active"])}
    rows = [{"name": r["full_name"], "player_id": int(r["player_id"]), "team_id": team_of.get(r["player_id"]),
             "is_active": active[int(r["player_id"])]} for r in players.to_dict("records")]
    aliases = player_store.read("player_aliases", columns="provider, provider_name, player_id", conn=conn)
    for r in aliases.to_dict("records"):
        if r["provider"] in ("nba_api", "normalized"):
            continue          # same names as players.full_name
        name = to_first_last(r["provider_name"])
        rows.append({"name": name, "player_id": int(r["player_id"]), "team_id": team_of.get(r["player_id"]),
                     "is_active": bool(active.get(r["player_id"], False))})
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect player box scores and players")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--players", action="store_true", help="refresh players and aliases only")
    args = parser.parse_args(argv)
    try:
        from console import force_utf8_stdio

        force_utf8_stdio()
    except Exception:
        pass
    print(f"player store: {player_store.backend()}")
    refresh_players()
    if args.players:
        return 0
    if args.backfill:
        counts = backfill()
        print(f"backfill: {counts}")
        return 1 if any(v is None for v in counts.values()) else 0
    incremental()
    return 0


if __name__ == "__main__":
    sys.exit(main())
