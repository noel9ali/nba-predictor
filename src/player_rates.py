"""Point-in-time shrunk per-minute player rates for future prop models.

This module only produces reusable rates; it does not make prop predictions or bets.
Every input game is strictly before ``as_of``.  The local SQLite store is the
default, matching the other player-data jobs, and Supabase is opt-in.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import argparse
import os
import sys

import numpy as np
import pandas as pd

try:
    from . import player_store
    from . import config
except ImportError:  # modules are also invoked with src on PYTHONPATH
    import player_store
    import config

STATS = ("pts", "reb", "ast", "fg3m", "stl", "blk", "tov")
VERSION = "player-rates-v1"
WINDOW_DAYS = 365
PRIOR_MINUTES = 400.0

player_store.register_table(
    "player_rate_stats",
    """create table if not exists player_rate_stats (
      player_id integer not null, as_of text not null, stat text not null,
      rate_per_min real not null, minutes_basis real not null, version text not null,
      primary key (player_id, as_of, stat))""",
    ["player_id", "as_of", "stat"],
)


def compute(player_games: pd.DataFrame, as_of: date | str) -> pd.DataFrame:
    """Return shrunk rates using only games with ``game_date < as_of``."""
    day = pd.Timestamp(as_of).date()
    pg = player_games.copy()
    if pg.empty:
        return pd.DataFrame(columns=[
            "player_id", "as_of", "stat", "rate_per_min", "minutes_basis", "version"])
    pg["game_date"] = pd.to_datetime(pg["game_date"]).dt.date
    pg = pg[pg["game_date"] < day].copy()
    pg["minutes"] = pd.to_numeric(pg["minutes"], errors="coerce").fillna(0).clip(lower=0)
    pg = pg[pg["minutes"] > 0]
    start = day - timedelta(days=WINDOW_DAYS)
    pg = pg[pg["game_date"] >= start]
    if pg.empty:
        return pd.DataFrame(columns=[
            "player_id", "as_of", "stat", "rate_per_min", "minutes_basis", "version"])

    # League priors are also point-in-time.  A 400-minute prior keeps short
    # samples useful without allowing one hot game to dominate.
    league = {s: float(pg[s].fillna(0).sum() / pg["minutes"].sum()) for s in STATS}
    rows = []
    for pid, group in pg.groupby("player_id"):
        mins = float(group["minutes"].sum())
        for stat in STATS:
            total = float(group[stat].fillna(0).sum())
            rate = (total + PRIOR_MINUTES * league[stat]) / (mins + PRIOR_MINUTES)
            rows.append({
                "player_id": int(pid), "as_of": day.isoformat(), "stat": stat,
                "rate_per_min": rate, "minutes_basis": mins, "version": VERSION,
            })
    return pd.DataFrame(rows)


def run_as_of(as_of: date | str, *, conn=None) -> int:
    columns = "player_id,game_date,minutes," + ",".join(STATS)
    pg = player_store.read("player_games", columns=columns, conn=conn)
    rows = compute(pg, as_of).to_dict("records")
    return player_store.upsert("player_rate_stats", rows, conn=conn)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=None, help="ISO date; defaults to today")
    args = parser.parse_args(argv)
    day = args.as_of or date.today().isoformat()
    try:
        print(f"player rates: {run_as_of(day)} rows at {day}")
        return 0
    except Exception as exc:
        # Nightly player-data jobs are non-fatal to the game pipeline.
        print(f"player rates skipped: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

