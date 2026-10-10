"""Read side of the availability API fields (Vercel-safe: pandas + src/database.py only).

Every function takes `read(table, **select_rows_kwargs) -> DataFrame` (the app's reader) and returns plain
JSON-ready values. A missing table or column (migrations 0001-0005 not applied yet) reads as empty, so the
additions degrade to empty lists and nulls, never errors. Query counts are constant in slate size.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import config
from player_names import to_first_last

STATUS_ORDER = {"out": 0, "doubtful": 1, "questionable": 2, "probable": 3, "available": 4}
TEAM_ID_TO_TRICODE = {v: k for k, v in config.TEAM_IDS.items()}
KEY_MINUTES = 20.0           # a player who would play this many minutes is "key" for summaries


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    f = _num(v)
    return int(f) if f is not None else None


def _iso(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_statuses(snapshots: pd.DataFrame, as_of: datetime | None = None) -> pd.DataFrame:
    """Newest row per (game, team, player) with report_time <= as_of; players dropped from a newer report
    of their team are removed (same rule as injuries.newest_per_player)."""
    if snapshots is None or snapshots.empty:
        return pd.DataFrame()
    df = snapshots.copy()
    df["report_time"] = df["report_time"].map(_iso)
    if as_of is not None:
        df = df[df["report_time"] <= _iso(as_of.isoformat())]
    if df.empty:
        return df
    latest_team = df.groupby(["game_id", "team_id"])["report_time"].transform("max")
    df = df[df["report_time"] == latest_team]
    key = df["player_id"].map(lambda p: f"id:{int(p)}" if _num(p) is not None else None)
    df = df.assign(_key=key.fillna("name:" + df["player_name_raw"].astype(str)))
    df = df.sort_values("report_time").groupby(["game_id", "team_id", "_key"], as_index=False).tail(1)
    return df.drop(columns="_key")


def latest_projection(proj: pd.DataFrame) -> pd.DataFrame:
    if proj is None or proj.empty:
        return pd.DataFrame()
    proj = proj.copy()
    latest = proj.groupby("game_id")["as_of"].transform("max")
    return proj[proj["as_of"] == latest]


def latest_ratings(ratings: pd.DataFrame) -> dict:
    """player_id -> rating, preferring the primary type, newest as_of per player."""
    if ratings is None or ratings.empty:
        return {}
    out = {}
    for rtype in (config.RATING_FALLBACK, config.RATING_PRIMARY):          # primary overwrites fallback
        part = ratings[ratings["rating_type"] == rtype].sort_values("as_of")
        if rtype == config.RATING_PRIMARY and "minutes_basis" in part:
            part = part[pd.to_numeric(part["minutes_basis"], errors="coerce").fillna(0)
                        >= config.RATING_MIN_MINUTES_FOR_PRIMARY]
        for pid, value in zip(part["player_id"], part["value"]):
            out[int(pid)] = float(value)
    return out


def player_entry(row: dict, proj_row: dict | None, rating: float | None) -> dict:
    status = row.get("status") if row.get("status") in STATUS_ORDER else "questionable"
    p_play = _num(proj_row.get("p_play")) if proj_row else None
    if p_play is None:
        p_play = float(config.STATUS_TO_P_PLAY.get(status, 1.0))
    exp_min = _num(proj_row.get("exp_min")) if proj_row else None
    min_if_play = _num(proj_row.get("min_if_play")) if proj_row else None
    impact = round(rating * min_if_play / 48.0, 1) if rating is not None and min_if_play else None
    return {
        "player_id": _int(row.get("player_id")),
        "name": to_first_last(str(row.get("player_name_raw") or "")),
        "status": status,
        "reason": row.get("reason") if isinstance(row.get("reason"), str) else None,
        "p_play": round(p_play, 3),
        "rating": round(rating, 1) if rating is not None else None,
        "exp_min": round(exp_min, 1) if exp_min is not None else None,
        "impact_pts": impact,
        "report_time": _iso(row.get("report_time")),
    }


def availability_by_game(read, game_ids: list[str], sides: dict, *, with_ratings: bool = True,
                         as_of: datetime | None = None) -> dict:
    """{game_id: {"home": [player...], "away": [player...]}} for report-listed players.
    sides: {game_id: (home_tricode, away_tricode)}. 2-3 queries regardless of slate size."""
    out = {g: {"home": [], "away": []} for g in game_ids}
    if not game_ids:
        return out
    snaps = read("injury_snapshots", columns="game_id,team_id,player_id,player_name_raw,status,reason,report_time",
                 filters=[("game_id", "in", list(game_ids))], order_by=["report_time", "snapshot_id"])
    statuses = latest_statuses(snaps, as_of)
    proj = latest_projection(read("player_minutes_projection",
                                  columns="game_id,player_id,as_of,p_play,exp_min,min_if_play,role",
                                  filters=[("game_id", "in", list(game_ids))], order_by=["game_id", "as_of"]))
    proj_by = {(r["game_id"], int(r["player_id"])): r for r in proj.to_dict("records")} if not proj.empty else {}
    ratings = {}
    if with_ratings and not statuses.empty:
        ids = sorted({int(p) for p in statuses["player_id"] if _num(p) is not None})
        if ids:
            ratings = latest_ratings(read("player_ratings", columns="player_id,as_of,rating_type,value,minutes_basis",
                                          filters=[("player_id", "in", ids)], order_by=["as_of", "player_id"]))
    for r in statuses.to_dict("records") if not statuses.empty else []:
        gid = r["game_id"]
        tri = TEAM_ID_TO_TRICODE.get(_int(r["team_id"]))
        home, away = sides.get(gid, (None, None))
        side = "home" if tri == home else "away" if tri == away else None
        if gid not in out or side is None:
            continue
        pid = _int(r.get("player_id"))
        entry = player_entry(r, proj_by.get((gid, pid)) if pid is not None else None, ratings.get(pid))
        out[gid][side].append(entry)
    for gid in out:
        for side in ("home", "away"):
            out[gid][side].sort(key=lambda e: (STATUS_ORDER[e["status"]], -(abs(e["impact_pts"] or 0)), e["name"]))
    return out


def summary(avail: dict, *, status_changed: bool) -> dict:
    """availability_summary for a slate game."""
    def outs(players):
        return [p for p in players if p["status"] == "out"]

    def key(p):
        return (p["impact_pts"] is not None and abs(p["impact_pts"]) >= 1.0) or \
            (p["exp_min"] is not None and p["exp_min"] >= KEY_MINUTES)

    home, away = avail.get("home", []), avail.get("away", [])
    key_out = [p["name"] for p in outs(home) + outs(away) if key(p)]
    uncertain = any(config.SCENARIO_P_LOW < p["p_play"] < config.SCENARIO_P_HIGH for p in home + away)
    return {"home_out": len(outs(home)), "away_out": len(outs(away)), "key_out": key_out,
            "uncertain": bool(uncertain), "status_changed": bool(status_changed)}


def availability_inputs(read, game_ids: list[str]) -> dict:
    """{game_id: row} from prediction_availability_inputs (status_changed flag and probability range)."""
    if not game_ids:
        return {}
    df = read("prediction_availability_inputs",
              columns="game_id,model_name,prob_range_low,prob_range_high,status_changed_after_pred,predicted_at",
              filters=[("game_id", "in", list(game_ids))], order_by=["game_id", "predicted_at"])
    return {r["game_id"]: r for r in df.to_dict("records")} if not df.empty else {}


def rest_for_game(read, game_id: str, sides: tuple) -> dict | None:
    df = read("team_availability_features", columns="game_id,team_id,as_of,rest_days,is_b2b",
              filters=[("game_id", "eq", game_id)], order_by=["as_of", "team_id"])
    if df.empty:
        return None
    df = df.sort_values("as_of").groupby("team_id", as_index=False).tail(1)
    out = {}
    for side, tri in zip(("home", "away"), sides):
        row = df[df["team_id"].map(_int) == config.TEAM_IDS.get(tri)]
        if row.empty:
            out[side] = {"rest_days": None, "is_b2b": None}
        else:
            r = row.iloc[0]
            b2b = _int(r.get("is_b2b"))
            out[side] = {"rest_days": _int(r.get("rest_days")), "is_b2b": bool(b2b) if b2b is not None else None}
    return out


def scenarios_and_factors(read, game_id: str, model_name: str | None) -> tuple[list, list]:
    if not model_name:
        return [], []
    scen = read("prediction_scenarios", columns="scenario_key,weight,home_win_prob,label,model_name",
                filters=[("game_id", "eq", game_id), ("model_name", "eq", model_name)], order_by="scenario_key")
    facts = read("prediction_factors", columns='factor_key,label,"group",prob_points,sort_order,model_name',
                 filters=[("game_id", "eq", game_id), ("model_name", "eq", model_name)], order_by="sort_order")
    scenarios = [{"label": r.get("label") or r["scenario_key"], "weight": round(float(r["weight"]), 4),
                  "home_win_prob": round(float(r["home_win_prob"]), 4)}
                 for r in scen.sort_values("weight", ascending=False).to_dict("records")] if not scen.empty else []
    factors = [{"key": r["factor_key"], "label": r["label"], "group": r["group"],
                "prob_points": round(float(r["prob_points"]), 2)}
               for r in facts.to_dict("records")] if not facts.empty else []
    return scenarios, factors


def star_out_by_game(read) -> dict:
    """{game_id: bool} for predicted games: a top-2 player out on either team (live report features)."""
    df = read("team_availability_features", columns="game_id,team_id,as_of,star_out,rating_type,basis",
              filters=[("basis", "eq", "report"), ("rating_type", "eq", config.RATING_PRIMARY)],
              order_by=["game_id", "as_of"])
    if df.empty:
        return {}
    df = df.sort_values("as_of").groupby(["game_id", "team_id"], as_index=False).tail(1)
    return {gid: bool((pd.to_numeric(part["star_out"], errors="coerce").fillna(0) > 0).any())
            for gid, part in df.groupby("game_id")}
