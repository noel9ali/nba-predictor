"""Fit the learned play-probability mapping (src/pplay.py) from the local injury-report archive and player_games.

    venv\\Scripts\\python.exe scripts\\fit_pplay_mapping.py [--cutoff 2026-07-01] [--out data\\pplay\\pplay_mapping_v1.json]
                                                          [--injury-db PATH] [--schedule-dir DIR]

Offline and read-only apart from the output file. For every game with an archived report at or before tip minus 60 minutes
(config.AVAILABILITY_AS_OF_MINUTES_BEFORE_TIP), and for each rostered player (same roster rule as
availability_features.historical_rows) plus every matched player listed on the team's newest report, it records the
status/reason on that report, the player's EWMA base minutes and appearances in the team's previous 10 games (both from
games strictly before the game date), and whether he played (player_games minutes > 0). Rows with game_date < cutoff
are fitted. See docs/pplay-learned.md for the evaluation that justifies (or not) switching config.P_PLAY_SOURCE.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import availability_features as af  # noqa: E402
import config  # noqa: E402
import injuries  # noqa: E402
import player_store  # noqa: E402
import pplay  # noqa: E402


def load_tips(schedule_dir: str | None, seasons) -> dict:
    if not schedule_dir:
        return af.tip_times(seasons)
    from nba_client import frames_from_json

    out = {}
    for path in sorted(glob.glob(os.path.join(schedule_dir, "schedule_*.json"))):
        with open(path, encoding="utf-8") as fh:
            df = frames_from_json(fh.read())[0]
        for gid, tip in zip(df["gameId"].astype(str).str.zfill(10), df["gameDateTimeUTC"].astype(str)):
            if tip[:4].isdigit():
                out[gid] = tip
    return out


def build_rows(pg: pd.DataFrame, snap: pd.DataFrame, tips: dict) -> pd.DataFrame:
    pg = pg.copy()
    pg["game_date"] = pg["game_date"].astype(str).str[:10]
    pg["minutes"] = pd.to_numeric(pg["minutes"], errors="coerce")
    pg = pg.sort_values(["player_id", "game_date", "game_id"]).reset_index(drop=True)
    pg["ewma"] = pg.groupby("player_id")["minutes"].transform(
        lambda s: s.ewm(halflife=config.MINUTES_HALF_LIFE_GAMES, adjust=True).mean())
    players = {pid: (g["game_date"].to_numpy(), g["team_id"].to_numpy(), g["ewma"].to_numpy())
               for pid, g in pg.groupby("player_id", sort=False)}
    played = set(zip(pg.loc[pg["minutes"] > 0, "game_id"], pg.loc[pg["minutes"] > 0, "player_id"].astype(int)))
    team_games = (pg[["team_id", "game_id", "game_date"]].drop_duplicates()
                  .sort_values(["team_id", "game_date", "game_id"]))
    appeared = pg.groupby(["team_id", "game_id"])["player_id"].apply(list).to_dict()
    by_game = {g: p for g, p in snap.groupby("game_id")}
    lookback = config.MINUTES_ROSTER_LOOKBACK_GAMES
    out = []
    for team_id, tg in team_games.groupby("team_id", sort=False):
        gids, gdates = tg["game_id"].tolist(), tg["game_date"].tolist()
        for i, (gid, gdate) in enumerate(zip(gids, gdates)):
            part = by_game.get(gid)
            as_of = af.as_of_for(gid, gdate, tips)
            if part is None or not (part["report_time"].astype(str) <= as_of).any():
                continue                                             # no report at tip-60: not a labelled game
            team_part = part[part["team_id"] == team_id]
            latest = injuries.newest_per_player(team_part, as_of) if not team_part.empty else pd.DataFrame()
            listed = {int(r["player_id"]): r for r in latest.to_dict("records") if pd.notna(r["player_id"])}
            roster = {}
            for pid in {p for g in gids[max(0, i - lookback):i] for p in appeared.get((team_id, g), [])}:
                d, t, e = players[pid]
                k = np.searchsorted(d, gdate, side="left") - 1
                if k >= 0 and t[k] == team_id:
                    roster[pid] = float(e[k])
            last10 = gids[max(0, i - 10):i]
            app = {}
            for g in last10:
                for p in appeared.get((team_id, g), []):
                    app[p] = app.get(p, 0) + 1
            for pid in sorted(set(roster) | set(listed)):
                s = listed.get(pid)
                out.append({"game_id": gid, "game_date": gdate, "player_id": pid,
                            "status": s["status"] if s is not None else "none",
                            "reason": (s["reason"] or "") if s is not None else "",
                            "base_min": roster.get(pid, 0.0), "app_l10": app.get(pid, 0),
                            "in_roster": int(pid in roster), "played": int((gid, pid) in played)})
    return pd.DataFrame(out).drop_duplicates(["game_id", "player_id"])


def main(argv=None) -> int:
    try:
        from console import force_utf8_stdio

        force_utf8_stdio()
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cutoff", default=None, help="fit only games with game_date < cutoff (default: all)")
    ap.add_argument("--out", default=pplay.default_path())
    ap.add_argument("--injury-db", default=config.INJURY_LOCAL_DB)
    ap.add_argument("--schedule-dir", default=None, help="folder of schedule_<season>.json (default: cached schedules)")
    args = ap.parse_args(argv)

    pg = player_store.read("player_games", columns="game_id, player_id, team_id, game_date, season, minutes")
    conn = injuries.connect(args.injury_db)
    try:
        snap = pd.read_sql_query("select game_id, team_id, player_id, player_name_raw, report_time, status, reason "
                                 "from injury_snapshots where game_id is not null", conn)
    finally:
        conn.close()
    tips = load_tips(args.schedule_dir, sorted(pg["season"].unique()))
    data = build_rows(pg, snap, tips)
    if args.cutoff:
        data = data[data["game_date"] < args.cutoff]
    fit = data[data["in_roster"] == 1]                    # the rows that feed the availability features
    table = pplay.fit_table(fit.to_dict("records"), built_from=f"{len(fit)} roster rows, {data['game_id'].nunique()} games",
                            cutoff=args.cutoff or str(data["game_date"].max()))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"fitted on {len(fit)} roster rows from {data['game_id'].nunique()} games "
          f"({data['game_date'].min()} to {data['game_date'].max()}); wrote {args.out}")
    print(f"cells: {len(table['none'])} unlisted, {len(table['listed'])} listed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
