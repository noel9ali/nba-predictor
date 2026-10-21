"""Minutes projection v1: p_play, expected minutes, a minutes range and a role per player per game.

Everything here is a function of (player_id, game_id, as_of) and player_games before the game date, with no
dependence on the game model, so player props can reuse it.

- p_play: from the latest injury status through config.STATUS_TO_P_PLAY (no report entry: 1.0). For history
  the caller passes realized availability instead (absent 0, else 1).
- Base minutes: exponentially weighted average of minutes in games played (half-life MINUTES_HALF_LIFE_GAMES).
- Redistribution: minutes-if-playing m_j = min(cap, s * base_j), with one scale s per team chosen so that the
  expected total sum(p_j * m_j) is MINUTES_TEAM_TOTAL. Absent teammates' minutes therefore flow to the others in
  proportion to their current minutes, respecting the per-player cap. exp_min = p_play * m_j (0 when out).
- min_p10 / min_p90: empirical quantiles of his last MINUTES_QUANTILE_GAMES played, times s (conditional on playing).
- role: inactive if p_play == 0; else the top 5 by m_j are starters, then rotation if m_j >= MINUTES_ROTATION_MIN,
  else bench.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

if __package__ in (None, "", "src"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
import player_store  # noqa: E402

player_store.register_table("player_minutes_projection", """
    create table if not exists player_minutes_projection (
      game_id text not null, player_id integer not null, as_of text not null, team_id integer not null,
      p_play real not null, exp_min real not null, min_if_play real, min_p10 real, min_p90 real,
      role text not null,
      basis text not null, version text not null, primary key (game_id, player_id, as_of))""",
    ["game_id", "player_id", "as_of"],
    ["create index if not exists player_minutes_projection_game_idx on player_minutes_projection (game_id, as_of)"])


def p_play_for_status(status: str | None) -> float:
    return float(config.STATUS_TO_P_PLAY.get(status, config.STATUS_TO_P_PLAY[None]))


def ewma_minutes(minutes: pd.Series) -> float:
    """EWMA of a player's minutes over games played (oldest first)."""
    m = pd.to_numeric(minutes, errors="coerce").dropna()
    if m.empty:
        return 0.0
    return float(m.ewm(halflife=config.MINUTES_HALF_LIFE_GAMES, adjust=True).mean().iloc[-1])


def solve_scale(base: np.ndarray, p: np.ndarray, *, cap: float | None = None, total: float | None = None) -> float:
    """Scale s with sum(p * min(cap, s * base)) == total (bisection). If even everyone at the cap cannot reach
    the total, returns the scale that caps everyone."""
    cap = config.MINUTES_PLAYER_CAP if cap is None else cap
    total = config.MINUTES_TEAM_TOTAL if total is None else total
    base = np.asarray(base, dtype=float)
    p = np.asarray(p, dtype=float)
    if not np.any((base > 0) & (p > 0)):
        return 1.0
    f = lambda s: float(np.sum(p * np.minimum(cap, s * base)))  # noqa: E731
    hi = 1.0
    while f(hi) < total and hi < 1e6:
        if f(hi) >= float(np.sum(p * cap)) - 1e-9:
            return hi
        hi *= 2.0
    lo = 0.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(mid) < total:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def redistribute(base, p, *, cap: float | None = None, total: float | None = None):
    """Returns (minutes_if_playing, expected_minutes, scale)."""
    cap = config.MINUTES_PLAYER_CAP if cap is None else cap
    base = np.asarray(base, dtype=float)
    p = np.asarray(p, dtype=float)
    s = solve_scale(base, p, cap=cap, total=total)
    m = np.minimum(cap, s * base)
    return m, p * m, s


def assign_roles(m: np.ndarray, p: np.ndarray) -> list[str]:
    roles = ["bench"] * len(m)
    order = [i for i in np.argsort(-np.asarray(m), kind="stable") if p[i] > 0]
    for rank, i in enumerate(order):
        if rank < 5:
            roles[i] = "starter"
        elif m[i] >= config.MINUTES_ROTATION_MIN:
            roles[i] = "rotation"
    for i in range(len(m)):
        if p[i] <= 0:
            roles[i] = "inactive"
    return roles


def infer_roster(pg_before: pd.DataFrame, team_id: int) -> list[int]:
    """Players seen in the team's last MINUTES_ROSTER_LOOKBACK_GAMES games whose latest appearance was for it."""
    team_games = pg_before[pg_before["team_id"] == team_id][["game_id", "game_date"]].drop_duplicates()
    recent = team_games.sort_values(["game_date", "game_id"]).tail(config.MINUTES_ROSTER_LOOKBACK_GAMES)
    seen = pg_before[(pg_before["team_id"] == team_id) & pg_before["game_id"].isin(recent["game_id"])]
    candidates = seen["player_id"].unique()
    latest = (pg_before[pg_before["player_id"].isin(candidates)].sort_values(["game_date", "game_id"])
              .groupby("player_id").tail(1))
    return sorted(int(p) for p in latest[latest["team_id"] == team_id]["player_id"])


def project_team(pg_before: pd.DataFrame, team_id: int, p_play: dict | None = None,
                 roster: list[int] | None = None) -> pd.DataFrame:
    """Projection rows for one team from player_games strictly before the game (pg_before)."""
    p_play = p_play or {}
    roster = roster if roster is not None else infer_roster(pg_before, team_id)
    cols = ["player_id", "team_id", "p_play", "base_min", "min_if_play", "exp_min", "min_p10", "min_p90", "role"]
    if not roster:
        return pd.DataFrame(columns=cols)
    hist = pg_before[pg_before["player_id"].isin(roster)].sort_values(["game_date", "game_id"])
    by_player = {pid: g["minutes"] for pid, g in hist.groupby("player_id")}
    base = np.array([ewma_minutes(by_player.get(pid, pd.Series(dtype=float))) for pid in roster])
    p = np.array([float(p_play.get(pid, 1.0)) for pid in roster])
    m, exp, s = redistribute(base, p)
    q10, q90 = [], []
    for pid in roster:
        mins = pd.to_numeric(by_player.get(pid, pd.Series(dtype=float)), errors="coerce").dropna()
        mins = mins.tail(config.MINUTES_QUANTILE_GAMES)
        q10.append(float(np.clip(mins.quantile(0.1) * s, 0, 48)) if len(mins) else None)
        q90.append(float(np.clip(mins.quantile(0.9) * s, 0, 48)) if len(mins) else None)
    return pd.DataFrame({"player_id": roster, "team_id": team_id, "p_play": p, "base_min": base,
                         "min_if_play": m, "exp_min": exp, "min_p10": q10, "min_p90": q90,
                         "role": assign_roles(m, p)})


def project_game(game_id: str, game_date: str, home_team_id: int, away_team_id: int, as_of: datetime, *,
                 pg_all: pd.DataFrame, p_play: dict | None = None, rosters: dict | None = None,
                 basis: str = "report") -> pd.DataFrame:
    """Rows for player_minutes_projection for both teams. pg_all may contain any dates; only games strictly
    before game_date (and before as_of's date) are used."""
    cutoff = min(str(game_date)[:10], as_of.date().isoformat() if hasattr(as_of, "date") else str(as_of)[:10])
    pg_before = pg_all[pg_all["game_date"].astype(str) < cutoff]
    rosters = rosters or {}
    parts = [project_team(pg_before, t, p_play, rosters.get(t)) for t in (home_team_id, away_team_id)]
    out = pd.concat([p for p in parts if not p.empty], ignore_index=True) if any(not p.empty for p in parts) \
        else pd.DataFrame(columns=parts[0].columns)
    out["game_id"] = game_id
    out["as_of"] = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    out["basis"] = f"ewma_hl{config.MINUTES_HALF_LIFE_GAMES}+{basis}"
    out["version"] = config.MINUTES_VERSION
    return out


def store_projection(df: pd.DataFrame, *, conn=None) -> int:
    cols = ["game_id", "player_id", "as_of", "team_id", "p_play", "exp_min", "min_if_play", "min_p10", "min_p90",
            "role", "basis", "version"]
    return player_store.upsert("player_minutes_projection", df[cols].to_dict("records"), conn=conn)


# ---------------------------------------------------------------------------
# CLI: worked example / manual check for one game
# ---------------------------------------------------------------------------

def report_p_play(game_id: str, as_of) -> tuple[dict, pd.DataFrame]:
    """p_play per player_id from the injury sink's latest_status (report_time <= as_of)."""
    import injuries

    status = injuries.latest_status(
        game_id, as_of,
        backend="supabase" if player_store.backend() == "supabase" else "local")
    if status.empty:
        return {}, status
    matched = status[status["player_id"].notna()]
    return {int(r["player_id"]): p_play_for_status(r["status"]) for r in matched.to_dict("records")}, status


def explain_game(game_id: str, as_of: datetime, *, conn=None) -> pd.DataFrame:
    import ratings

    pg_all = player_store.read("player_games", columns="game_id, player_id, team_id, game_date, season, is_home, "
                               "minutes", conn=conn)
    g = pg_all[pg_all["game_id"] == game_id]
    if g.empty:
        raise SystemExit(f"{game_id} not in player_games (future games: phase 6 uses the schedule)")
    game_date = str(g["game_date"].iloc[0])
    home = int(g[g["is_home"] == 1]["team_id"].iloc[0])
    away = int(g[g["is_home"] == 0]["team_id"].iloc[0])
    p_play, status = report_p_play(game_id, as_of)
    proj = project_game(game_id, game_date, home, away, as_of, pg_all=pg_all, p_play=p_play)
    rates = ratings.combined_ratings(game_date, conn=conn)
    names = player_store.read("players", columns="player_id, full_name", conn=conn)
    out = proj.merge(rates, on="player_id", how="left").merge(names, on="player_id", how="left")
    st = status[["player_id", "status"]].dropna() if not status.empty else pd.DataFrame(columns=["player_id", "status"])
    out = out.merge(st.astype({"player_id": int}), on="player_id", how="left")
    actual = g[["player_id", "minutes"]].rename(columns={"minutes": "actual_min"})
    return out.merge(actual, on="player_id", how="left").sort_values(["team_id", "exp_min"], ascending=[True, False])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Minutes projection for one game (worked example)")
    parser.add_argument("--game", required=True)
    parser.add_argument("--as-of", required=True, help="ISO time, e.g. 2026-04-10T18:00-04:00")
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args()
    try:
        from console import force_utf8_stdio

        force_utf8_stdio()
    except Exception:
        pass
    import injuries

    df = explain_game(args.game, injuries.parse_as_of(args.as_of))
    cols = ["team_id", "full_name", "status", "p_play", "value", "source", "base_min", "exp_min", "min_p10",
            "min_p90", "role", "actual_min"]
    for team, part in df.groupby("team_id", sort=False):
        print(part[cols].head(args.top).round(1).to_string(index=False))
        print()
