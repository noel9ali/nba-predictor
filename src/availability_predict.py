"""Predict-time availability: projections, features, scenario blending, factors and status-change flags.

Called from predict.py for every game of the slate (inside try/except: a failure here never stops
predictions). What it does per game, with as_of = now:
1. p_play from the newest injury snapshot (the --predict run takes a snapshot first);
2. player_minutes_projection and team_availability_features (basis 'report') are stored;
3. if an availability candidate model is saved (data/candidates/<name>.pkl), its scenario-blended probability,
   the scenarios and the factor contributions are stored under that model_name (shadow mode);
4. only when NBA_PRODUCTION_MODEL names that candidate does predict.py use the blended probability, the
   probability range and the (default-off) uncertainty gate for the real pick. Otherwise production is unchanged.

    python src/availability_predict.py --flag-status-changes     # later ticks / morning settle
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

if __package__ in (None, "", "src"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
import player_store  # noqa: E402

CANDIDATE_DIR = os.path.join(config.DATA_DIR, "candidates")
DEFAULT_CANDIDATE = "lr-calibrated-availability-v1"
EXPECTED_FEATURE_SET_VERSION = "avail_v1+ratings:2026-10-10"


class CandidateArtifactError(RuntimeError):
    """Candidate artifacts are incomplete, stale, or corrupted."""


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(name: str) -> str:
    return os.path.join(CANDIDATE_DIR, f"{name}.manifest.json")


def _feature_hash(features: list[str]) -> str:
    return hashlib.sha256(json.dumps(list(features), separators=(",", ":")).encode()).hexdigest()

player_store.register_table("prediction_scenarios", """
    create table if not exists prediction_scenarios (
      game_id text not null, model_name text not null, scenario_key text not null, weight real not null,
      home_win_prob real not null, label text, predicted_at text,
      primary key (game_id, model_name, scenario_key))""", ["game_id", "model_name", "scenario_key"])
player_store.register_table("prediction_factors", """
    create table if not exists prediction_factors (
      game_id text not null, model_name text not null, factor_key text not null, label text not null,
      "group" text not null, prob_points real not null, sort_order integer not null,
      primary key (game_id, model_name, factor_key))""", ["game_id", "model_name", "factor_key"])
player_store.register_table("prediction_availability_inputs", """
    create table if not exists prediction_availability_inputs (
      game_id text not null, model_name text not null, predicted_at text not null, as_of text not null,
      home_win_prob real, prob_range_low real, prob_range_high real, key_statuses text,
      status_changed_after_pred integer, primary key (game_id, model_name))""", ["game_id", "model_name"])


# ---------------------------------------------------------------------------
# Candidate artifacts
# ---------------------------------------------------------------------------

def save_candidate(name: str, model, scaler, features: list[str], meta: dict | None = None) -> str:
    import joblib

    os.makedirs(CANDIDATE_DIR, exist_ok=True)
    path = os.path.join(CANDIDATE_DIR, f"{name}.pkl")
    payload_meta = dict(meta or {})
    payload_meta.setdefault("model_name", name)
    payload_meta.setdefault("feature_set_version", EXPECTED_FEATURE_SET_VERSION)
    joblib.dump({"model": model, "scaler": scaler, "features": list(features), "meta": payload_meta}, path)
    manifest = {
        "model_name": name, "artifact_path": os.path.relpath(path, config.REPO_ROOT),
        "artifact_sha256": _sha256(path), "feature_hash": _feature_hash(features),
        "features": list(features), "feature_set_version": payload_meta.get("feature_set_version"),
        "trained_at": payload_meta.get("trained_at"), "evaluated_at": payload_meta.get("evaluated_at"),
    }
    with open(_manifest_path(name), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def load_candidate(name: str = DEFAULT_CANDIDATE, *, required: bool | None = None) -> dict | None:
    path = os.path.join(CANDIDATE_DIR, f"{name}.pkl")
    if required is None:
        required = production_uses_candidate(name)
    if not os.path.exists(path):
        if required:
            raise CandidateArtifactError(
                f"Configured availability candidate '{name}' is missing: expected {path}. "
                "Deploy the matching data/candidates/*.pkl and manifest, or unset NBA_PRODUCTION_MODEL."
            )
        return None
    manifest_path = _manifest_path(name)
    if not os.path.exists(manifest_path):
        raise CandidateArtifactError(f"Candidate '{name}' is missing integrity metadata: {manifest_path}")
    import joblib
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        if manifest.get("model_name") != name or manifest.get("artifact_sha256") != _sha256(path):
            raise CandidateArtifactError(f"Candidate '{name}' failed artifact hash/model-name validation")
        bundle = joblib.load(path)
        features = bundle.get("features")
        if not isinstance(features, list) or features != manifest.get("features"):
            raise CandidateArtifactError(f"Candidate '{name}' feature list does not match its manifest")
        if _feature_hash(features) != manifest.get("feature_hash"):
            raise CandidateArtifactError(f"Candidate '{name}' feature-list integrity hash mismatched")
        meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
        if meta.get("feature_set_version") != manifest.get("feature_set_version"):
            raise CandidateArtifactError(f"Candidate '{name}' feature-set version does not match its manifest")
        if manifest.get("feature_set_version") != EXPECTED_FEATURE_SET_VERSION:
            raise CandidateArtifactError(
                f"Candidate '{name}' uses feature_set_version={manifest.get('feature_set_version')!r}; "
                f"runtime expects {EXPECTED_FEATURE_SET_VERSION!r}"
            )
        if not bundle.get("model") or not bundle.get("scaler"):
            raise CandidateArtifactError(f"Candidate '{name}' must include model and scaler")
    except CandidateArtifactError:
        raise
    except Exception as exc:
        raise CandidateArtifactError(f"Unable to load candidate '{name}': {type(exc).__name__}: {exc}") from exc
    bundle["name"], bundle["manifest"] = name, manifest
    return bundle


def configured_candidate_name() -> str | None:
    value = os.getenv("NBA_PRODUCTION_MODEL", "").strip()
    return value if value.startswith("lr-calibrated-availability-") else None


def production_uses_candidate(name: str) -> bool:
    return os.getenv("NBA_PRODUCTION_MODEL", "").strip() == name


# ---------------------------------------------------------------------------
# Per-game computation
# ---------------------------------------------------------------------------

def _wide(home: dict, away: dict, rest_home: dict, rest_away: dict) -> dict:
    """Same column names as scripts/evaluate_availability.py ('rapm:' prefix)."""
    h = {**home, **rest_home}
    a = {**away, **rest_away}
    row = {}
    for f in ("rating_expected", "value_out", "top3_avail", "minutes_lost", "rest_days", "games_last_7"):
        hv, av = h.get(f), a.get(f)
        row[f"rapm:{f}_diff"] = (hv - av) if hv is not None and av is not None else 0.0
    row["rapm:home_star_out"] = h.get("star_out") or 0
    row["rapm:away_star_out"] = a.get("star_out") or 0
    row["rapm:home_is_b2b"] = h.get("is_b2b") or 0
    row["rapm:away_is_b2b"] = a.get("is_b2b") or 0
    return row


class GameAvailability:
    """Everything availability-related for one game at one as_of."""

    def __init__(self, game_id: str, game_date: str, home_team_id: int, away_team_id: int, as_of: datetime, *,
                 pg_all: pd.DataFrame | None = None, statuses: pd.DataFrame | None = None, conn=None,
                 rosters: dict | None = None):
        import availability_features as af
        import injuries
        from minutes import p_play_for_status, project_team

        self.game_id, self.game_date = game_id, str(game_date)[:10]
        self.home, self.away = int(home_team_id), int(away_team_id)
        self.as_of = as_of
        cutoff = min(self.game_date, as_of.astimezone(injuries.ET).date().isoformat())
        if pg_all is None:
            pg_all = player_store.read("player_games", columns="game_id, player_id, team_id, game_date, season, "
                                       "minutes", filters=[("game_date", "lt", cutoff)], conn=conn)
        self.pg = pg_all[pg_all["game_date"].astype(str) < cutoff]
        if statuses is None:
            statuses = injuries.latest_status(game_id, as_of,
                                              backend="supabase" if player_store.backend() == "supabase" else "local")
        self.statuses = statuses
        matched = statuses[statuses["player_id"].notna()] if not statuses.empty else statuses
        self.status_of = {int(r["player_id"]): r["status"] for r in matched.to_dict("records")} \
            if not matched.empty else {}
        self.p_play = {pid: p_play_for_status(s) for pid, s in self.status_of.items()}
        ratings = af.RatingLookup(config.RATING_PRIMARY, conn=conn).for_day(cutoff)
        self.ratings = ratings
        rosters = rosters or {}
        self.projection = {}
        self.rest = {}
        season = self.pg["season"].max() if not self.pg.empty else None
        from nba_client import season_for_date
        from datetime import date as _date

        for team in (self.home, self.away):
            proj = project_team(self.pg, team, self.p_play, rosters.get(team))
            proj["rating"] = [ratings.get(int(p), config.RATING_UNRATED_VALUE) for p in proj["player_id"]]
            self.projection[team] = proj
            same_season = season and season_for_date(_date.fromisoformat(cutoff)) == season
            dates = self.pg[(self.pg["team_id"] == team) & (self.pg["season"] == season)]["game_date"].unique() \
                if same_season else []
            self.rest[team] = af.rest_features(list(dates), self.game_date)

    def team_feats(self, team: int, overrides: dict | None = None) -> dict:
        import availability_features as af

        proj = self.projection[team]
        if proj.empty:
            return af.team_features(None)
        r = proj[["player_id", "base_min", "p_play", "rating"]].copy()
        if overrides:
            r["p_play"] = [overrides.get(int(p), v) for p, v in zip(r["player_id"], r["p_play"])]
        return af.team_features(r)

    def feature_row(self, overrides: dict | None = None) -> dict:
        return _wide(self.team_feats(self.home, overrides), self.team_feats(self.away, overrides),
                     self.rest[self.home], self.rest[self.away])

    def feature_rows_for_store(self) -> list[dict]:
        out = []
        stamp = self.as_of.astimezone(timezone.utc).isoformat(timespec="seconds")
        for team in (self.home, self.away):
            out.append({"game_id": self.game_id, "team_id": team, "as_of": stamp,
                        "rating_type": config.RATING_PRIMARY, "basis": "report", **self.team_feats(team),
                        **self.rest[team], "feature_version": config.AVAILABILITY_FEATURE_VERSION})
        return out

    def projection_rows_for_store(self) -> pd.DataFrame:
        stamp = self.as_of.astimezone(timezone.utc).isoformat(timespec="seconds")
        parts = [p for p in self.projection.values() if not p.empty]
        if not parts:
            return pd.DataFrame()
        df = pd.concat(parts, ignore_index=True)
        df["game_id"], df["as_of"] = self.game_id, stamp
        df["basis"] = f"ewma_hl{config.MINUTES_HALF_LIFE_GAMES}+report"
        df["version"] = config.MINUTES_VERSION
        return df

    def key_players(self) -> list[int]:
        """Top STATUS_CHANGE_KEY_PLAYERS by impact (|rating| x minutes if playing) per team."""
        keys = []
        for proj in self.projection.values():
            if proj.empty:
                continue
            impact = proj["rating"].abs() * proj["min_if_play"]
            keys += [int(p) for p in proj.loc[impact.sort_values(ascending=False).index, "player_id"]
                     .head(config.STATUS_CHANGE_KEY_PLAYERS)]
        return keys

    def uncertain(self) -> pd.DataFrame:
        from scenarios import uncertain_players

        parts = []
        for proj in self.projection.values():
            if not proj.empty:
                parts.append(uncertain_players(proj))
        if not parts:
            return pd.DataFrame(columns=["player_id", "p_play"])
        return pd.concat(parts, ignore_index=True)


def score_with_candidate(ga: GameAvailability, base_row: dict, candidate: dict, *, names: dict | None = None,
                         base_rate: float = 0.55) -> dict:
    """Scenario-blended probability, range, scenarios and factors for one game with a candidate model."""
    from factors import explain
    from scenarios import blend, enumerate_scenarios

    feats = candidate["features"]
    model, scaler = candidate["model"], candidate["scaler"]

    def x_for(overrides):
        row = {**base_row, **ga.feature_row(overrides)}
        return np.array([[float(row.get(f, 0.0) or 0.0) for f in feats]])

    def score(overrides):
        return float(model.predict_proba(scaler.transform(x_for(overrides)))[0, 1])

    scen = enumerate_scenarios(ga.uncertain(), names=names)
    blended, low, high, scored = blend(scen, score)
    # Factors at the expected (as reported) inputs, reconciled to the blended probability.
    split = []
    names = names or {}
    for team in (ga.home, ga.away):
        proj = ga.projection[team]
        for r in proj.to_dict("records"):
            lost = (r["min_if_play"] - r["exp_min"]) * r["rating"] / config.MINUTES_TEAM_TOTAL
            if r["p_play"] < 1 and abs(lost) > 1e-6:
                sign = 1 if team == ga.away else -1        # a home player missing hurts the home side
                split.append((f"{names.get(int(r['player_id']), int(r['player_id']))} "
                              f"{ga.status_of.get(int(r['player_id']), 'out')}", sign * lost))
    rows = explain(model, scaler, x_for({})[0], feats, blended, base_rate, availability_split=split or None)
    return {"home_win_prob": blended, "prob_range_low": low, "prob_range_high": high, "scenarios": scored,
            "factors": rows}


def store_results(ga: GameAvailability, result: dict | None, model_name: str | None, *, conn=None) -> None:
    import minutes

    proj = ga.projection_rows_for_store()
    if not proj.empty:
        minutes.store_projection(proj, conn=conn)
    player_store.upsert("team_availability_features", ga.feature_rows_for_store(), conn=conn)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if result is None or not model_name:
        return
    player_store.upsert("prediction_scenarios", [
        {"game_id": ga.game_id, "model_name": model_name, "scenario_key": s.key, "weight": s.weight,
         "home_win_prob": s.home_win_prob, "label": s.label, "predicted_at": stamp} for s in result["scenarios"]],
        conn=conn)
    player_store.upsert("prediction_factors", [
        {"game_id": ga.game_id, "model_name": model_name, **f} for f in result["factors"]], conn=conn)
    player_store.upsert("prediction_availability_inputs", [{
        "game_id": ga.game_id, "model_name": model_name, "predicted_at": stamp,
        "as_of": ga.as_of.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "home_win_prob": result["home_win_prob"], "prob_range_low": result["prob_range_low"],
        "prob_range_high": result["prob_range_high"],
        "key_statuses": json.dumps({str(p): ga.status_of.get(p) for p in ga.key_players()}),
        "status_changed_after_pred": 0}], conn=conn)


def player_names(*, conn=None) -> dict:
    df = player_store.read("players", columns="player_id, full_name", conn=conn)
    return dict(zip(df["player_id"].astype(int), df["full_name"])) if not df.empty else {}


ROSTER_CACHE_MAX_AGE_DAYS = 3     # older than this: the cache is not trusted, fall back to the inferred roster
ROSTER_MIN_PLAYERS = 5            # a team with fewer current players than this keeps its inferred roster


def current_rosters(path: str | None = None, *, now: datetime | None = None) -> dict[int, list[int]]:
    """team_id -> player ids on the current roster, from the CommonAllPlayers cache that collect_players refreshes
    daily (TEAM_ID is the team today, so offseason trades and signings are reflected; the roster inferred from
    the last 20 game logs is still last season's in October). Empty when the cache is missing or stale: callers
    then keep the inferred roster. Players without minutes history project to 0 minutes, so extra names are inert."""
    from nba_client import frames_from_json

    path = path or os.path.join(config.RAW_DIR, "nba_api", "common_all_players.json")
    try:
        age_days = ((now or datetime.now(timezone.utc)).timestamp() - os.path.getmtime(path)) / 86400
        if age_days > ROSTER_CACHE_MAX_AGE_DAYS:
            return {}
        with open(path, encoding="utf-8") as fh:
            df = frames_from_json(fh.read())[0]
    except (OSError, ValueError, IndexError):
        return {}
    if df.empty or not {"PERSON_ID", "TEAM_ID", "ROSTERSTATUS"} <= set(df.columns):
        return {}
    df = df[(pd.to_numeric(df["ROSTERSTATUS"], errors="coerce") == 1) & (pd.to_numeric(df["TEAM_ID"], errors="coerce") > 0)]
    rosters = {int(t): sorted(int(p) for p in g["PERSON_ID"]) for t, g in df.groupby(df["TEAM_ID"].astype(int))}
    return {t: ids for t, ids in rosters.items() if len(ids) >= ROSTER_MIN_PLAYERS}


def run_for_game(game_id: str, game_date: str, home_team_id: int, away_team_id: int, base_row: dict, *,
                 as_of: datetime | None = None, candidate: dict | None = None, conn=None,
                 names: dict | None = None, rosters: dict | None = None) -> dict | None:
    """Store projections/features and, with a candidate, its shadow prediction. Returns the candidate result."""
    as_of = as_of or datetime.now(timezone.utc)
    if rosters is None:
        rosters = current_rosters()
    ga = GameAvailability(game_id, game_date, home_team_id, away_team_id, as_of, conn=conn, rosters=rosters)
    result = score_with_candidate(ga, base_row, candidate, names=names) if candidate else None
    store_results(ga, result, candidate["name"] if candidate else None, conn=conn)
    return result


# ---------------------------------------------------------------------------
# Status-change flags
# ---------------------------------------------------------------------------

def flag_status_changes(*, conn=None, now: datetime | None = None, write_predictions: bool = True) -> int:
    """Compare key players' statuses at prediction time with the latest snapshot. Sets the local flag and,
    when write_predictions, predictions.status_changed_after_pred (needs migration 0005; skipped with a
    message if the column is missing). Informational only: nothing is re-bet."""
    import injuries
    from scenarios import status_changed

    now = now or datetime.now(timezone.utc)
    inputs = player_store.read("prediction_availability_inputs", conn=conn)
    changed = []
    for r in inputs.to_dict("records"):
        before = {int(k): v for k, v in json.loads(r["key_statuses"] or "{}").items()}
        latest = injuries.latest_status(
            r["game_id"], now,
            backend="supabase" if player_store.backend() == "supabase" else "local")
        after = {int(p): s for p, s in zip(latest.get("player_id", []), latest.get("status", []))
                 if pd.notna(p)} if not latest.empty else {}
        flag = status_changed(before, after, list(before))
        if flag and not r.get("status_changed_after_pred"):
            changed.append(r["game_id"])
            player_store.upsert("prediction_availability_inputs", [dict(r, status_changed_after_pred=1)], conn=conn)
    if changed and write_predictions:
        from database import DatabaseError, update_rows

        try:
            for gid in changed:
                update_rows("predictions", {"status_changed_after_pred": True}, filters=[("game_id", "eq", gid)])
        except DatabaseError as exc:
            print(f"status_changed_after_pred not written ({exc}); apply supabase/migrations/20261012000500_predict_availability.sql")
    print(f"status changes: {len(changed)} game(s) flagged")
    return len(changed)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Predict-time availability helpers")
    parser.add_argument("--flag-status-changes", action="store_true")
    args = parser.parse_args()
    if args.flag_status_changes:
        try:
            flag_status_changes()
        except Exception as exc:          # informational: never fail the pipeline
            print(f"status-change check failed: {type(exc).__name__}: {exc}")
