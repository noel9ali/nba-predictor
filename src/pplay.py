"""Learned play probabilities, a data-fitted replacement for the hand-set STATUS_TO_P_PLAY table (PROPOSAL, shipped OFF).

    config.P_PLAY_SOURCE = "status_table"   (default: today's behaviour)   |   "learned_table"

The learned table is a small empirical-Bayes lookup (no sklearn, nothing heavy: it ships as JSON and is used with
plain dicts) fitted on the injury-report archive at tip minus 60 minutes against what actually happened (a
player_games row with minutes > 0). It differs from the hand table in two places:

- listed players: P(play | status, reason group, base minutes), e.g. 'questionable' G League assignees play ~19% of
  the time, questionable injuries ~52%, 'available' G League players ~41%.
- UNLISTED players (the hand table says 1.0): P(play | base minutes, appearances in the team's last 10 games). An
  unlisted rotation player who has played 0 of the last 10 team games plays ~6% of the time; one who played 10 of 10
  plays ~98%. This is where nearly all of the measured gain comes from.

Everything used at lookup time is known before tip-off: the report status and reason text at the as_of time, the
player's EWMA minutes and his appearances in the team's previous 10 games (player_games strictly before the game date).
Fitting uses only rows with game_date < a cutoff, so a time-ordered evaluation cannot see the future.

Lookup order (each step falls back to the next when a cell has fewer than MIN_CELL_N examples):
  cell -> status+reason group -> status -> the hand table.
Players without a valid appearance count (not on the team's recent game log, e.g. an offseason signing) get the hand
table value, never a learned 'absent' value: the learned unlisted rule is only valid for players with history here.
"""

from __future__ import annotations

import json
import os
from bisect import bisect_right

import config

BM_EDGES = (6.0, 12.0, 18.0, 24.0)          # base-minute buckets: <6, 6-12, 12-18, 18-24, 24+
BM3_EDGES = (12.0, 24.0)                    # coarse buckets for listed players
APP_BUCKETS = ((0, 0), (1, 3), (4, 6), (7, 9), (10, 10))
MIN_CELL_N = 40
SHRINK_M = 20.0                             # pseudo-observations of the parent in each cell estimate
STATUSES = ("out", "doubtful", "questionable", "probable", "available")
FORMAT_VERSION = 1


def bm_bucket(base_min: float, edges=BM_EDGES) -> int:
    return bisect_right(edges, float(base_min or 0.0))


def app_bucket(n: int) -> int:
    n = max(0, min(10, int(n)))
    for i, (lo, hi) in enumerate(APP_BUCKETS):
        if lo <= n <= hi:
            return i
    return len(APP_BUCKETS) - 1


def reason_group(reason: str | None) -> str:
    x = (reason or "").lower()
    if x.startswith("g league"):
        return "g_league"
    if "injury/illness" in x or "illness" in x or "injury" in x:
        return "injury"
    return "other"


def _shrunk(k: float, n: float, parent: float, m: float = SHRINK_M) -> float:
    return (k + m * parent) / (n + m)


def fit_table(rows, *, built_from: str = "", cutoff: str | None = None) -> dict:
    """rows: iterable of dicts with status ('none' for unlisted), reason, base_min, app_l10, played (0/1).
    Returns the JSON-serializable mapping."""
    none_all = [0, 0]
    none_app: dict[int, list] = {}
    none_cell: dict[tuple, list] = {}
    st: dict[str, list] = {s: [0, 0] for s in STATUSES}
    st_rg: dict[tuple, list] = {}
    st_cell: dict[tuple, list] = {}

    def add(d, key, played):
        v = d.setdefault(key, [0, 0])
        v[0] += int(played)
        v[1] += 1

    for r in rows:
        played = int(r["played"])
        if r["status"] == "none":
            none_all[0] += played
            none_all[1] += 1
            add(none_app, app_bucket(r["app_l10"]), played)
            add(none_cell, (app_bucket(r["app_l10"]), bm_bucket(r["base_min"])), played)
        elif r["status"] in st:
            st[r["status"]][0] += played
            st[r["status"]][1] += 1
            rg = reason_group(r.get("reason"))
            add(st_rg, (r["status"], rg), played)
            add(st_cell, (r["status"], rg, bm_bucket(r["base_min"], BM3_EDGES)), played)

    out = {"format_version": FORMAT_VERSION, "built_from": built_from, "cutoff_game_date": cutoff,
           "bm_edges": list(BM_EDGES), "bm3_edges": list(BM3_EDGES), "app_buckets": [list(b) for b in APP_BUCKETS],
           "min_cell_n": MIN_CELL_N, "shrink_m": SHRINK_M, "none": {}, "listed": {}}
    p0 = none_all[0] / max(1, none_all[1])
    out["none"]["all"] = {"p": round(p0, 4), "n": none_all[1]}
    for a, (k, n) in sorted(none_app.items()):
        out["none"][f"app{a}"] = {"p": round(_shrunk(k, n, p0), 4), "n": n}
    for (a, b), (k, n) in sorted(none_cell.items()):
        parent = _shrunk(*none_app.get(a, [0, 0]), p0)
        out["none"][f"app{a}|bm{b}"] = {"p": round(_shrunk(k, n, parent), 4), "n": n}
    for s, (k, n) in st.items():
        if n:
            out["listed"][s] = {"p": round(k / n, 4), "n": n}
    for (s, rg), (k, n) in sorted(st_rg.items()):
        parent = st[s][0] / max(1, st[s][1])
        out["listed"][f"{s}|{rg}"] = {"p": round(_shrunk(k, n, parent), 4), "n": n}
    for (s, rg, b), (k, n) in sorted(st_cell.items()):
        k0, n0 = st_rg[(s, rg)]
        parent = _shrunk(k0, n0, st[s][0] / max(1, st[s][1]))
        out["listed"][f"{s}|{rg}|bm{b}"] = {"p": round(_shrunk(k, n, parent), 4), "n": n}
    return out


def _cell(table: dict, section: str, key: str):
    c = table.get(section, {}).get(key)
    return c["p"] if c and c.get("n", 0) >= table.get("min_cell_n", MIN_CELL_N) else None


def lookup(table: dict | None, status: str | None, reason: str | None, base_min: float | None,
           app_l10: int | None) -> float:
    """Learned P(play). status None / 'none' = not on the report. Falls back to the hand table whenever the mapping
    has no usable cell, or (for unlisted players) when app_l10 is None (no recent game log with this team)."""
    hand = float(config.STATUS_TO_P_PLAY.get(None if status in (None, "none") else status,
                                             config.STATUS_TO_P_PLAY[None]))
    if not table:
        return hand
    if status in (None, "none"):
        if app_l10 is None:
            return hand
        a = app_bucket(app_l10)
        p = _cell(table, "none", f"app{a}|bm{bm_bucket(base_min)}")
        if p is None:
            p = _cell(table, "none", f"app{a}")
        return hand if p is None else float(p)
    rg = reason_group(reason)
    for key in (f"{status}|{rg}|bm{bm_bucket(base_min, BM3_EDGES)}", f"{status}|{rg}", status):
        p = _cell(table, "listed", key)
        if p is not None:
            return float(p)
    return hand


def appearances_last10(pg_before, team_id: int, player_ids) -> dict[int, int]:
    """For each player: in how many of the team's previous 10 games (strictly before, from pg_before = player_games
    rows before the game date) did he record minutes. Players with no row for this team in the window get 0 only if
    they appear in the team's recent log at all; players never seen with the team in the last
    MINUTES_ROSTER_LOOKBACK_GAMES games are omitted (None downstream = hand table)."""
    team_games = pg_before[pg_before["team_id"] == team_id][["game_id", "game_date"]].drop_duplicates()
    last = team_games.sort_values(["game_date", "game_id"]).tail(10)["game_id"].tolist()
    lookback = team_games.sort_values(["game_date", "game_id"]).tail(config.MINUTES_ROSTER_LOOKBACK_GAMES)["game_id"].tolist()
    rows = pg_before[(pg_before["team_id"] == team_id) & pg_before["game_id"].isin(lookback)]
    seen = set(rows["player_id"].astype(int))
    counts = rows[rows["game_id"].isin(last)].groupby("player_id")["game_id"].nunique()
    return {int(p): int(counts.get(p, 0)) for p in player_ids if int(p) in seen}


def default_path() -> str:
    return getattr(config, "P_PLAY_MAPPING_PATH", os.path.join(config.DATA_DIR, "pplay", "pplay_mapping_v1.json"))


def load_mapping(path: str | None = None) -> dict | None:
    try:
        with open(path or default_path(), encoding="utf-8") as fh:
            table = json.load(fh)
    except (OSError, ValueError):
        return None
    return table if table.get("format_version") == FORMAT_VERSION else None
