"""Point-in-time player ratings: rapm_lite_v1 (ridge on game margins) and box_value_v1 (shrunk box composite).

Both are in points per 100 possessions relative to an average player, for a player on the court for a full game.
A rating with as_of = D uses only games strictly before D, so it is safe for any game on or after D.

    python src/ratings.py --backfill           # weekly refits over the history (resumable)
    python src/ratings.py                      # nightly refresh: ratings as of today

rapm_lite_v1: one row per game. Features are each player's share of his team's minutes (x5, so a full game is 1.0;
+ for home players, - for away players); target is the final margin per 100 possessions (possessions estimated
from team box scores). Trailing window of RATING_WINDOW_DAYS with exponential down-weighting
(RATING_HALF_LIFE_DAYS). Ridge shrinks toward a prior: last season's final rapm rating where available, otherwise
the player's box_value_v1. The penalty is chosen by time-ordered validation (last 20% of the window by date).

box_value_v1: Hollinger Game Score per minute, empirical-Bayes shrunk toward the league mean by minutes played
(BOX_PRIOR_MINUTES), centred so the average minute is 0, then scaled to margin-per-100 units with one
regression of game margins on the minutes-weighted team sums.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import date, timedelta

if __package__ in (None, "", "src"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import sparse  # noqa: E402

import config  # noqa: E402
import player_store  # noqa: E402
from nba_client import season_for_date  # noqa: E402

player_store.register_table("player_ratings", """
    create table if not exists player_ratings (
      player_id integer not null, as_of text not null, rating_type text not null, value real not null,
      minutes_basis real not null, se real, version text not null,
      primary key (player_id, as_of, rating_type))""", ["player_id", "as_of", "rating_type"],
    ["create index if not exists player_ratings_type_asof_idx on player_ratings (rating_type, as_of)"])

PG_COLUMNS = ("game_id, player_id, team_id, game_date, season, is_home, minutes, pts, oreb, dreb, ast, stl, blk, "
              "tov, pf, fgm, fga, ftm, fta")


def game_score(pg: pd.DataFrame) -> pd.Series:
    f = lambda c: pd.to_numeric(pg[c], errors="coerce").fillna(0.0)  # noqa: E731
    return (f("pts") + 0.4 * f("fgm") - 0.7 * f("fga") - 0.4 * (f("fta") - f("ftm")) + 0.7 * f("oreb")
            + 0.3 * f("dreb") + f("stl") + 0.7 * f("ast") + 0.7 * f("blk") - 0.4 * f("pf") - f("tov"))


def game_table(pg: pd.DataFrame) -> pd.DataFrame:
    """One row per game: game_id, game_date, season, home/away team, margin, possessions, y (margin per 100)."""
    num = pg.assign(**{c: pd.to_numeric(pg[c], errors="coerce").fillna(0.0)
                       for c in ("pts", "fga", "oreb", "tov", "fta", "minutes")})
    teams = num.groupby(["game_id", "team_id", "is_home", "game_date", "season"], as_index=False)[
        ["pts", "fga", "oreb", "tov", "fta", "minutes"]].sum()
    teams["poss"] = teams["fga"] - teams["oreb"] + teams["tov"] + 0.44 * teams["fta"]
    home = teams[teams["is_home"] == 1]
    away = teams[teams["is_home"] == 0][["game_id", "team_id", "pts", "poss", "minutes"]]
    g = home.merge(away, on="game_id", suffixes=("_home", "_away"))
    g["margin"] = g["pts_home"] - g["pts_away"]
    g["poss"] = (g["poss_home"] + g["poss_away"]) / 2.0
    g["y"] = 100.0 * g["margin"] / g["poss"].clip(lower=50)
    return g.rename(columns={"team_id_home": "home_team_id", "team_id_away": "away_team_id"})[
        ["game_id", "game_date", "season", "home_team_id", "away_team_id", "margin", "poss", "y",
         "minutes_home", "minutes_away"]]


def design(pg: pd.DataFrame, games: pd.DataFrame):
    """Sparse X (games x players): +share for home players, -share for away; share = 5 * min / team minutes."""
    pg = pg[pg["game_id"].isin(games["game_id"])]
    mins = pd.to_numeric(pg["minutes"], errors="coerce").fillna(0.0)
    team_min = pg.assign(m=mins).groupby(["game_id", "team_id"])["m"].transform("sum").clip(lower=1.0)
    share = 5.0 * mins / team_min
    sign = np.where(pg["is_home"].astype(int) == 1, 1.0, -1.0)
    players = np.sort(pg["player_id"].unique())
    pcol = {p: i for i, p in enumerate(players)}
    grow = {g: i for i, g in enumerate(games["game_id"])}
    rows = pg["game_id"].map(grow).to_numpy()
    cols = pg["player_id"].map(pcol).to_numpy()
    X = sparse.csr_matrix((share.to_numpy() * sign, (rows, cols)), shape=(len(games), len(players)))
    return X, players


def _weights(game_dates: pd.Series, as_of: date) -> np.ndarray:
    age = (pd.Timestamp(as_of) - pd.to_datetime(game_dates)).dt.days.to_numpy()
    return np.power(0.5, age / config.RATING_HALF_LIFE_DAYS)


def _ridge_fit(X, y, w, alpha):
    from sklearn.linear_model import Ridge

    model = Ridge(alpha=alpha, fit_intercept=True, solver="auto")
    model.fit(X, y, sample_weight=w)
    return model


def fit_rapm(X, y, w, prior: np.ndarray, alphas=None, holdout=None):
    """Ridge toward `prior`; returns (coef, intercept, alpha, se). Rows of X must be in date order."""
    alphas = alphas or config.RATING_RIDGE_ALPHAS
    holdout = config.RATING_CV_HOLDOUT_FRACTION if holdout is None else holdout
    y_adj = y - X @ prior
    n = X.shape[0]
    cut = int(n * (1 - holdout))
    best_alpha, best_err = alphas[0], math.inf
    if 0 < cut < n and len(alphas) > 1:
        for alpha in alphas:
            m = _ridge_fit(X[:cut], y_adj[:cut], w[:cut], alpha)
            err = np.average((y_adj[cut:] - m.predict(X[cut:])) ** 2, weights=w[cut:])
            if err < best_err:
                best_alpha, best_err = alpha, err
    model = _ridge_fit(X, y_adj, w, best_alpha)
    coef = prior + model.coef_
    resid = y_adj - model.predict(X)
    sigma2 = float(np.average(resid ** 2, weights=w))
    xtwx_diag = np.asarray(X.multiply(X).T @ w).ravel()
    se = np.sqrt(sigma2 / (xtwx_diag + best_alpha))
    return coef, float(model.intercept_), best_alpha, se


def box_values(pg: pd.DataFrame, games: pd.DataFrame, w_by_game: dict) -> pd.DataFrame:
    pg = pg[pg["game_id"].isin(games["game_id"])].copy()
    pg["w"] = pg["game_id"].map(w_by_game)
    pg["mins"] = pd.to_numeric(pg["minutes"], errors="coerce").fillna(0.0)
    pg["gs"] = game_score(pg)
    agg = pg.assign(wgs=pg["w"] * pg["gs"], wmin=pg["w"] * pg["mins"]).groupby("player_id").agg(
        wgs=("wgs", "sum"), wmin=("wmin", "sum"), minutes=("mins", "sum"))
    mean = agg["wgs"].sum() / max(agg["wmin"].sum(), 1e-9)
    m0 = config.BOX_PRIOR_MINUTES
    shrunk = (agg["wgs"] + m0 * mean) / (agg["wmin"] + m0)
    centered = (shrunk - mean) * 48.0
    # Scale to margin-per-100 units: regress game y on the minutes-share-weighted centred values.
    X, players = design(pg, games)
    vals = centered.reindex(players).fillna(0.0).to_numpy()
    z = X @ vals
    w = games["game_id"].map(w_by_game).to_numpy()
    y = games["y"].to_numpy()
    zc, yc = z - np.average(z, weights=w), y - np.average(y, weights=w)
    k = float(np.sum(w * zc * yc) / max(np.sum(w * zc * zc), 1e-9))
    out = pd.DataFrame({"player_id": agg.index.astype(int), "value": (centered * k).to_numpy(),
                        "minutes_basis": agg["minutes"].to_numpy()})
    out.attrs["scale"] = k
    return out


def compute(pg_all: pd.DataFrame, as_of: date, *, prior_rapm: dict | None = None) -> pd.DataFrame:
    """Ratings of both types as of `as_of` from games strictly before it."""
    start = as_of - timedelta(days=config.RATING_WINDOW_DAYS)
    dates = pg_all["game_date"].astype(str)
    pg = pg_all[(dates < as_of.isoformat()) & (dates >= start.isoformat())]
    cols = ["player_id", "as_of", "rating_type", "value", "minutes_basis", "se", "version"]
    if pg.empty:
        return pd.DataFrame(columns=cols)
    games = game_table(pg).sort_values(["game_date", "game_id"]).reset_index(drop=True)
    if len(games) < config.RATING_MIN_GAMES:
        return pd.DataFrame(columns=cols)
    w = _weights(games["game_date"], as_of)
    w_by_game = dict(zip(games["game_id"], w))

    box = box_values(pg, games, w_by_game)
    X, players = design(pg, games)
    box_map = dict(zip(box["player_id"], box["value"]))
    prior_rapm = prior_rapm or {}
    prior = np.array([prior_rapm.get(int(p), box_map.get(int(p), 0.0)) for p in players])
    coef, intercept, alpha, se = fit_rapm(X, games["y"].to_numpy(), w, prior)
    minutes = pd.to_numeric(pg["minutes"], errors="coerce").fillna(0.0).groupby(pg["player_id"]).sum()

    stamp = as_of.isoformat()
    rapm = pd.DataFrame({"player_id": players.astype(int), "as_of": stamp, "rating_type": "rapm_lite_v1",
                         "value": coef, "minutes_basis": minutes.reindex(players).to_numpy(), "se": se,
                         "version": f"{config.RATING_VERSION};alpha={alpha:g};hca={intercept:.2f}"})
    boxdf = box.assign(as_of=stamp, rating_type="box_value_v1", se=None,
                       version=f"{config.RATING_VERSION};scale={box.attrs['scale']:.3f}")[cols]
    out = pd.concat([rapm[cols], boxdf], ignore_index=True)
    out.attrs.update(alpha=alpha, hca=intercept, games=len(games))
    return out


def _season_start(as_of: date) -> date:
    return date(int(season_for_date(as_of)[:4]), 8, 1)


def prior_for(as_of: date, *, conn=None) -> dict:
    """Last season's final rapm_lite_v1 ratings (latest as_of before this season's start)."""
    cutoff = _season_start(as_of).isoformat()
    df = player_store.query(
        "select player_id, value from player_ratings where rating_type = 'rapm_lite_v1' and as_of = "
        "(select max(as_of) from player_ratings where rating_type = 'rapm_lite_v1' and as_of < ?)",
        [cutoff], conn=conn)
    return dict(zip(df["player_id"].astype(int), df["value"]))


def load_player_games(*, conn=None) -> pd.DataFrame:
    return player_store.read("player_games", columns=PG_COLUMNS, conn=conn)


def run_as_of(as_of: date, *, pg_all: pd.DataFrame | None = None, conn=None) -> int:
    pg_all = load_player_games(conn=conn) if pg_all is None else pg_all
    out = compute(pg_all, as_of, prior_rapm=prior_for(as_of, conn=conn))
    if out.empty:
        return 0
    player_store.upsert("player_ratings", out.to_dict("records"), conn=conn)
    return len(out)


def backfill_dates(start: date, end: date, every_days: int) -> list[date]:
    """Weekly refit dates, only while games are being played (first and last game of each season + 1 day)."""
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=every_days)
    return out


def backfill(*, start: date | None = None, end: date | None = None, conn=None, rebuild: bool = False) -> int:
    """Weekly refits during seasons. Resumable: as_of dates already stored are skipped unless rebuild=True
    (which refits and overwrites them, for example after a config change)."""
    pg_all = load_player_games(conn=conn)
    if pg_all.empty:
        print("player_games is empty; run collect_players.py --backfill first")
        return 0
    start = start or date.fromisoformat(config.RATING_BACKFILL_START)
    last_game = date.fromisoformat(str(pg_all["game_date"].max())[:10])
    end = end or (last_game + timedelta(days=1))
    done = set() if rebuild else set(player_store.query(
        "select distinct as_of from player_ratings where rating_type = 'rapm_lite_v1'", conn=conn)["as_of"])
    season_days = pg_all.groupby("season")["game_date"].agg(["min", "max"])
    in_season = lambda d: any(lo <= d.isoformat() <= (date.fromisoformat(hi) + timedelta(days=7)).isoformat()  # noqa: E731
                              for lo, hi in zip(season_days["min"], season_days["max"]))
    n = 0
    for d in backfill_dates(start, end, config.RATING_BACKFILL_EVERY_DAYS) + [end]:
        if d.isoformat() in done or not in_season(d):
            continue
        rows = run_as_of(d, pg_all=pg_all, conn=conn)
        done.add(d.isoformat())
        n += 1
        if n % 10 == 0:
            print(f"  ratings through {d.isoformat()} ({n} refits)")
    print(f"ratings backfill: {n} new refits")
    return n


def ratings_as_of(day, rating_type: str, *, conn=None) -> pd.DataFrame:
    """The latest stored ratings of a type with as_of <= day (point-in-time safe for games on `day`)."""
    day = day.isoformat() if hasattr(day, "isoformat") else str(day)[:10]
    return player_store.query(
        "select player_id, as_of, value, minutes_basis, se from player_ratings where rating_type = ? and as_of = "
        "(select max(as_of) from player_ratings where rating_type = ? and as_of <= ?)",
        [rating_type, rating_type, day], conn=conn)


def combined_ratings(day, *, conn=None) -> pd.DataFrame:
    """Primary rating where it has enough minutes, else the fallback. Columns player_id, value, source."""
    primary = ratings_as_of(day, config.RATING_PRIMARY, conn=conn)
    fallback = ratings_as_of(day, config.RATING_FALLBACK, conn=conn)
    p = primary[primary["minutes_basis"] >= config.RATING_MIN_MINUTES_FOR_PRIMARY][["player_id", "value"]]
    f = fallback[~fallback["player_id"].isin(p["player_id"])][["player_id", "value"]]
    return pd.concat([p.assign(source=config.RATING_PRIMARY), f.assign(source=config.RATING_FALLBACK)],
                     ignore_index=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Player ratings")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--rebuild", action="store_true", help="with --backfill: refit stored dates too")
    parser.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args(argv)
    try:
        from console import force_utf8_stdio

        force_utf8_stdio()
    except Exception:
        pass
    if args.backfill:
        backfill(rebuild=args.rebuild)
        return 0
    day = args.as_of or date.today()
    if args.as_of is None:
        latest = player_store.query("select max(as_of) d from player_ratings where rating_type = ?",
                                    [config.RATING_PRIMARY])["d"].iloc[0]
        last_game = player_store.query("select max(game_date) d from player_games")["d"].iloc[0]
        if latest and last_game and str(last_game) < str(latest):
            print(f"ratings: no games since the {latest} refit; nothing to do")
            return 0
    n = run_as_of(day)
    print(f"ratings as of {day.isoformat()}: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
