"""Availability-adjusted team features and rest days (team_availability_features).

    python src/availability_features.py --backfill      # every historical team-game, both rating types
    build(game_id, as_of)                                 # live: injury-report probabilities

Per team and game, from player_games strictly before the game date and ratings with as_of <= game date:
- rating_baseline: sum(healthy_min / 240 x rating) over the inferred rotation, everyone playing.
- rating_expected: sum(exp_min / 240 x rating) with p_play (minutes.redistribute).
- value_out = baseline - expected; star_out: a top-2 player by rating has p_play < 0.5;
  top3_avail: mean p_play of the top 3 by rating ("top" = players with >= 15 base minutes);
  minutes_lost: healthy minus expected minutes over the usual top 8 by healthy minutes;
  n_key_uncertain: top 5 by impact (rating x healthy minutes) with 0.1 < p_play < 0.9.
- rest_days (1 = back-to-back, capped at REST_DAYS_CAP; season opener = cap), is_b2b, games_last_7.

History uses realized availability: a player with an inferred absence (player_absences) gets p_play 0, everyone
else 1 (basis 'realized'). Live uses the injury report (basis 'report'). These differ: see the report.
The same `team_features` function computes both, so live and history cannot drift apart.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

if __package__ in (None, "", "src"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
import player_store  # noqa: E402
from minutes import redistribute  # noqa: E402

player_store.register_table("team_availability_features", """
    create table if not exists team_availability_features (
      game_id text not null, team_id integer not null, as_of text not null, rating_type text not null,
      basis text not null, rating_baseline real, rating_expected real, value_out real, star_out integer,
      top3_avail real, minutes_lost real, n_key_uncertain integer, rest_days integer, is_b2b integer,
      games_last_7 integer, feature_version text not null,
      primary key (game_id, team_id, as_of, rating_type))""",
    ["game_id", "team_id", "as_of", "rating_type"],
    ["create index if not exists team_availability_features_game_idx on team_availability_features (game_id)"])

FEATURES = ["rating_baseline", "rating_expected", "value_out", "star_out", "top3_avail", "minutes_lost",
            "n_key_uncertain", "rest_days", "is_b2b", "games_last_7"]
REST_FEATURES = ["rest_days", "is_b2b", "games_last_7"]


# ---------------------------------------------------------------------------
# Core computations (shared by live and history)
# ---------------------------------------------------------------------------

def team_features(roster: pd.DataFrame) -> dict:
    """roster columns: player_id, base_min, p_play, rating. Returns the availability feature values."""
    empty = {k: None for k in FEATURES if k not in REST_FEATURES}
    if roster is None or roster.empty:
        return empty
    base = roster["base_min"].to_numpy(dtype=float)
    p = roster["p_play"].to_numpy(dtype=float)
    rating = roster["rating"].to_numpy(dtype=float)
    healthy, _, _ = redistribute(base, np.ones_like(p))
    _, exp, _ = redistribute(base, p)
    total = config.MINUTES_TEAM_TOTAL
    baseline = float(np.sum(healthy / total * rating))
    expected = float(np.sum(exp / total * rating))
    key = np.where(base >= config.AVAILABILITY_KEY_MIN_BASE_MINUTES)[0]
    if key.size == 0:
        key = np.arange(len(base))
    by_rating = key[np.argsort(-rating[key], kind="stable")]
    top8 = np.argsort(-healthy, kind="stable")[:8]
    by_impact = key[np.argsort(-(rating[key] * healthy[key]), kind="stable")][:5]
    return {
        "rating_baseline": round(baseline, 4),
        "rating_expected": round(expected, 4),
        "value_out": round(baseline - expected, 4),
        "star_out": int(bool(np.any(p[by_rating[:2]] < 0.5))),
        "top3_avail": round(float(np.mean(p[by_rating[:3]])), 4),
        "minutes_lost": round(float(np.sum(np.clip(healthy[top8] - exp[top8], 0, None))), 2),
        "n_key_uncertain": int(np.sum((p[by_impact] > 0.1) & (p[by_impact] < 0.9))),
    }


def rest_features(previous_dates: list[str], game_date: str) -> dict:
    """previous_dates: the team's earlier game dates this season (any order)."""
    d = date.fromisoformat(str(game_date)[:10])
    prev = sorted(date.fromisoformat(str(x)[:10]) for x in previous_dates if str(x)[:10] < d.isoformat())
    if not prev:
        rest = config.REST_DAYS_CAP
    else:
        rest = min((d - prev[-1]).days, config.REST_DAYS_CAP)
    last7 = sum(1 for x in prev if (d - x).days <= 7)
    return {"rest_days": int(rest), "is_b2b": int(rest == 1), "games_last_7": int(last7)}


class RatingLookup:
    """Point-in-time ratings by day for one feature rating type (rapm with box fallback, or box only)."""

    def __init__(self, rating_type: str, *, conn=None):
        self.rating_type = rating_type
        df = player_store.query("select player_id, as_of, rating_type, value, minutes_basis from player_ratings",
                                conn=conn)
        self.by_type = {t: g for t, g in df.groupby("rating_type")}
        self.as_ofs = sorted(df["as_of"].unique()) if not df.empty else []
        self._cache: dict[str, dict] = {}

    def for_day(self, day: str) -> dict:
        idx = np.searchsorted(self.as_ofs, str(day)[:10], side="right") - 1
        if idx < 0:
            return {}
        as_of = self.as_ofs[idx]
        if as_of not in self._cache:
            box = self.by_type.get(config.RATING_FALLBACK, pd.DataFrame(columns=["as_of"]))
            box = box[box["as_of"] == as_of]
            values = dict(zip(box["player_id"].astype(int), box["value"]))
            if self.rating_type == config.RATING_PRIMARY:
                prim = self.by_type.get(config.RATING_PRIMARY, pd.DataFrame(columns=["as_of"]))
                prim = prim[(prim["as_of"] == as_of)
                            & (prim["minutes_basis"] >= config.RATING_MIN_MINUTES_FOR_PRIMARY)]
                values.update(dict(zip(prim["player_id"].astype(int), prim["value"])))
            self._cache[as_of] = values
        return self._cache[as_of]


def tip_times(seasons) -> dict:
    """game_id -> tip time (UTC ISO) from the cached schedules; missing games fall back later."""
    import injuries

    out = {}
    for season in seasons:
        try:
            sched = injuries.load_schedule(season)
        except Exception as exc:
            print(f"  schedule for {season} unavailable ({type(exc).__name__}); default tip times")
            continue
        if "tip_utc" in sched:
            for gid, tip in zip(sched["game_id"], sched["tip_utc"]):
                if isinstance(tip, str) and tip[:4].isdigit():
                    out[gid] = tip
    return out


def as_of_for(game_id: str, game_date: str, tips: dict) -> str:
    tip = tips.get(game_id)
    if tip:
        t = datetime.fromisoformat(tip.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    else:
        from zoneinfo import ZoneInfo

        t = datetime.fromisoformat(f"{str(game_date)[:10]}T19:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
    t = t - timedelta(minutes=config.AVAILABILITY_AS_OF_MINUTES_BEFORE_TIP)
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def historical_rows(pg: pd.DataFrame, absent: set, lookups: dict, tips: dict | None = None) -> list[dict]:
    """Feature rows for every team-game in pg (realized availability)."""
    tips = tips or {}
    pg = pg.copy()
    pg["game_date"] = pg["game_date"].astype(str).str[:10]
    pg["minutes"] = pd.to_numeric(pg["minutes"], errors="coerce")
    pg = pg.sort_values(["player_id", "game_date", "game_id"]).reset_index(drop=True)
    pg["ewma"] = pg.groupby("player_id")["minutes"].transform(
        lambda s: s.ewm(halflife=config.MINUTES_HALF_LIFE_GAMES, adjust=True).mean())
    players = {pid: (g["game_date"].to_numpy(), g["team_id"].to_numpy(), g["ewma"].to_numpy())
               for pid, g in pg.groupby("player_id", sort=False)}
    team_games = (pg[["team_id", "game_id", "game_date", "season"]].drop_duplicates()
                  .sort_values(["team_id", "game_date", "game_id"]))
    appeared = pg.groupby(["team_id", "game_id"])["player_id"].apply(list).to_dict()

    rows = []
    lookback = config.MINUTES_ROSTER_LOOKBACK_GAMES
    for team_id, tg in team_games.groupby("team_id", sort=False):
        gids, gdates, seasons = tg["game_id"].tolist(), tg["game_date"].tolist(), tg["season"].tolist()
        for i, (gid, gdate, season) in enumerate(zip(gids, gdates, seasons)):
            candidates = {p for g in gids[max(0, i - lookback):i] for p in appeared.get((team_id, g), [])}
            roster = []
            for pid in candidates:
                d, t, e = players[pid]
                k = np.searchsorted(d, gdate, side="left") - 1
                if k < 0 or t[k] != team_id:
                    continue
                roster.append((pid, float(e[k]), 0.0 if (gid, pid) in absent else 1.0))
            season_prev = [gdates[j] for j in range(i) if seasons[j] == season]
            rest = rest_features(season_prev, gdate)
            as_of = as_of_for(gid, gdate, tips)
            for rtype, lookup in lookups.items():
                values = lookup.for_day(gdate)
                if roster and values:
                    df = pd.DataFrame(roster, columns=["player_id", "base_min", "p_play"])
                    df["rating"] = [values.get(int(p), config.RATING_UNRATED_VALUE) for p in df["player_id"]]
                    feats = team_features(df)
                else:
                    feats = team_features(None)
                rows.append({"game_id": gid, "team_id": int(team_id), "as_of": as_of, "rating_type": rtype,
                             "basis": "realized", **feats, **rest,
                             "feature_version": config.AVAILABILITY_FEATURE_VERSION})
    return rows


def backfill(*, conn=None) -> int:
    pg = player_store.read("player_games", columns="game_id, player_id, team_id, game_date, season, minutes",
                           conn=conn)
    ab = player_store.read("player_absences", columns="game_id, player_id", conn=conn)
    absent = set(zip(ab["game_id"], ab["player_id"].astype(int)))
    lookups = {t: RatingLookup(t, conn=conn) for t in config.AVAILABILITY_RATING_TYPES}
    tips = tip_times(sorted(pg["season"].unique()))
    rows = historical_rows(pg, absent, lookups, tips)
    player_store.upsert("team_availability_features", rows, conn=conn)
    print(f"team_availability_features: {len(rows)} rows ({len(rows) // len(lookups)} team-games x "
          f"{len(lookups)} rating types)")
    return len(rows)


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------

def build(game_id: str, as_of, *, game_date: str, home_team_id: int, away_team_id: int, conn=None,
          p_play: dict | None = None, rosters: dict | None = None, store: bool = True) -> list[dict]:
    """Features for an upcoming game from the injury report (basis 'report'). p_play defaults to the
    injury sink's latest_status at as_of. Only data strictly before game_date (and as_of) is read."""
    import injuries
    from minutes import project_team, report_p_play

    as_of_dt = injuries.parse_as_of(as_of)
    cutoff = min(str(game_date)[:10], as_of_dt.astimezone(injuries.ET).date().isoformat())
    pg = player_store.read("player_games", columns="game_id, player_id, team_id, game_date, season, minutes",
                           filters=[("game_date", "lt", cutoff)], conn=conn)
    if p_play is None:
        p_play, _ = report_p_play(game_id, as_of_dt)
    rosters = rosters or {}
    rows = []
    season_of = pg["season"].max() if not pg.empty else None
    for team_id in (home_team_id, away_team_id):
        proj = project_team(pg, team_id, p_play, rosters.get(team_id))
        team_dates = pg[(pg["team_id"] == team_id) & (pg["season"] == season_of)]["game_date"].unique().tolist()
        from nba_client import season_for_date

        if season_of and season_for_date(date.fromisoformat(cutoff)) != season_of:
            team_dates = []                                  # first game of a new season
        rest = rest_features(team_dates, game_date)
        for rtype in config.AVAILABILITY_RATING_TYPES:
            values = RatingLookup(rtype, conn=conn).for_day(cutoff)
            if not proj.empty and values:
                df = proj[["player_id", "base_min", "p_play"]].copy()
                df["rating"] = [values.get(int(p), config.RATING_UNRATED_VALUE) for p in df["player_id"]]
                feats = team_features(df)
            else:
                feats = team_features(None)
            rows.append({"game_id": game_id, "team_id": int(team_id),
                         "as_of": as_of_dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
                         "rating_type": rtype, "basis": "report", **feats, **rest,
                         "feature_version": config.AVAILABILITY_FEATURE_VERSION})
    if store:
        player_store.upsert("team_availability_features", rows, conn=conn)
    return rows


# ---------------------------------------------------------------------------
# Model matrix
# ---------------------------------------------------------------------------

def model_matrix(rating_type: str, *, conn=None, basis: str = "realized") -> pd.DataFrame:
    """One row per game: home_*, away_* and *_diff columns, joined in code (the features table is untouched).
    Uses the newest as_of per (game, team) that is strictly before the tip (rows are written that way)."""
    feats = player_store.read("team_availability_features", filters=[("rating_type", "eq", rating_type),
                                                                      ("basis", "eq", basis)], conn=conn)
    if feats.empty:
        return feats
    feats = feats.sort_values("as_of").groupby(["game_id", "team_id"], as_index=False).tail(1)
    sides = player_store.query("select distinct game_id, team_id, is_home from player_games", conn=conn)
    feats = feats.merge(sides, on=["game_id", "team_id"], how="inner")
    home = feats[feats["is_home"] == 1].set_index("game_id")[FEATURES].add_prefix("home_")
    away = feats[feats["is_home"] == 0].set_index("game_id")[FEATURES].add_prefix("away_")
    wide = home.join(away, how="inner")
    for f in FEATURES:
        wide[f"{f}_diff"] = wide[f"home_{f}"] - wide[f"away_{f}"]
    return wide.reset_index()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Team availability features")
    parser.add_argument("--backfill", action="store_true")
    args = parser.parse_args(argv)
    if args.backfill:
        backfill()
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
