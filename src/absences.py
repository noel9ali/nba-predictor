"""Derive player_absences from player_games (game-log data only).

A player is absent from a team game when, over his team's previous ABSENCE_LOOKBACK_GAMES games of the same
season, he appeared in at least ABSENCE_MIN_APPEARANCES and averaged at least ABSENCE_MIN_TYPICAL_MINUTES
in the games he played, and he has no player_games row for this game. basis = 'inferred'.

Trades: a player only counts for team T if his previous appearance (any team) was for T and his next
appearance in the season, if any, is also for T, so a traded player is never absent for his old team.
Season boundaries: the window never crosses seasons.
Note: this is a hindsight label for history (realized absences); live predictions use injury reports.

    python src/absences.py            # rebuild all seasons (idempotent upsert on (game_id, player_id))
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, "", "src"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
import player_store  # noqa: E402


def infer_absences(pg: pd.DataFrame, *, lookback: int | None = None, min_apps: int | None = None,
                   min_minutes: float | None = None) -> pd.DataFrame:
    """pg: player_games rows (game_id, player_id, team_id, game_date, season, minutes).
    Returns player_absences rows as a DataFrame."""
    lookback = lookback or config.ABSENCE_LOOKBACK_GAMES
    min_apps = min_apps or config.ABSENCE_MIN_APPEARANCES
    min_minutes = config.ABSENCE_MIN_TYPICAL_MINUTES if min_minutes is None else min_minutes
    cols = ["game_id", "player_id", "team_id", "game_date", "basis", "reason", "typical_minutes"]
    if pg.empty:
        return pd.DataFrame(columns=cols)
    pg = pg.copy()
    pg["game_date"] = pg["game_date"].astype(str).str[:10]
    pg["minutes"] = pd.to_numeric(pg["minutes"], errors="coerce").fillna(0.0)

    # Each player's appearance timeline (any team), for the trade check.
    timeline = pg.sort_values(["player_id", "game_date", "game_id"])[["player_id", "game_date", "team_id", "season"]]
    by_player = {pid: (g["game_date"].to_numpy(), g["team_id"].to_numpy(), g["season"].to_numpy())
                 for pid, g in timeline.groupby("player_id", sort=False)}

    out = []
    for (team_id, season), tg in pg.groupby(["team_id", "season"], sort=False):
        games = tg[["game_id", "game_date"]].drop_duplicates().sort_values(["game_date", "game_id"])
        mins = tg.pivot_table(index="game_id", columns="player_id", values="minutes", aggfunc="sum")
        mins = mins.reindex(games["game_id"])
        played = mins.notna()
        apps = played.rolling(lookback, min_periods=1).sum().shift(1)
        total = mins.fillna(0.0).rolling(lookback, min_periods=1).sum().shift(1)
        avg = total / apps.replace(0, np.nan)
        candidate = (~played) & (apps >= min_apps) & (avg >= min_minutes)
        if not candidate.values.any():
            continue
        dates = dict(zip(games["game_id"], games["game_date"]))
        for game_id, player_id in zip(*np.nonzero(candidate.to_numpy())):
            gid = candidate.index[game_id]
            pid = candidate.columns[player_id]
            gdate = dates[gid]
            p_dates, p_teams, p_seasons = by_player[pid]
            prev_i = np.searchsorted(p_dates, gdate, side="left") - 1
            next_i = np.searchsorted(p_dates, gdate, side="right")
            if prev_i < 0 or p_teams[prev_i] != team_id:
                continue                                   # last seen with another team: traded away
            if next_i < len(p_dates) and p_seasons[next_i] == season and p_teams[next_i] != team_id:
                continue                                   # next seen with another team: traded away
            out.append({"game_id": gid, "player_id": int(pid), "team_id": int(team_id), "game_date": gdate,
                        "basis": "inferred", "reason": None,
                        "typical_minutes": round(float(avg.iloc[game_id, player_id]), 2)})
    return pd.DataFrame(out, columns=cols)


def rebuild(*, conn=None) -> int:
    pg = player_store.read("player_games", columns="game_id, player_id, team_id, game_date, season, minutes",
                           conn=conn)
    absences = infer_absences(pg)
    rows = absences.to_dict("records")
    player_store.upsert("player_absences", rows, conn=conn)
    print(f"player_absences: {len(rows)} inferred absences from {len(pg)} player-game rows")
    return len(rows)


if __name__ == "__main__":
    try:
        from console import force_utf8_stdio

        force_utf8_stdio()
    except Exception:
        pass
    rebuild()
