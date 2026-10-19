"""Model versus market, closing-line value and line movement against injury news (offline).

    venv\\Scripts\\python.exe scripts\\market_vs_model.py --predictions predictions_export.csv
        [--archive data\\odds_history\\odds_history.sqlite] [--injuries data\\injuries\\injury_snapshots.sqlite]
        [--out-dir DIR] [--json]

Reads the odds archive (src/odds_archive.py: every bookmaker, append-only) and an export of the `predictions` table
(CSV or JSON with at least game_id, home_team, away_team, home_win_prob; optional predicted_winner, bet_placed,
actual_winner, tip_time_utc, predicted_at, odds, bookmaker). It makes no network calls and writes nothing unless
--out-dir is given. It runs on an empty or tiny archive: every section then says "n/a (n=...)" instead of failing.

Snapshots per game (tip time = the archive's commence_time):
  pricing = the earliest capture 80 to 45 minutes before tip (the predict stage prices 60-75 minutes before tip);
            if predicted_at is exported, the latest capture at or before predicted_at + 2 min inside that window
  close   = the latest capture 30 minutes before tip up to tip (a closing capture is taken about tip minus 10 minutes
            when config.ODDS_CLOSING_CAPTURE is on; otherwise a late pricing capture may qualify, else the game has
            no close and is left out of the close-based numbers)
Market probability = median across bookmakers of the proportional no-vig home probability (books with both sides).

What it reports
  1. model vs market at pricing: mean difference, correlation, mean absolute gap.
  2. closing-line value (CLV) of our priced side (bet_placed, else predicted_winner):
       clv = no-vig close probability of that side minus no-vig pricing probability of that side (positive = the market
       moved toward us); edge_vs_close = model probability of that side minus the no-vig close probability.
  3. calibration: Brier, log loss and a reliability table for model, pricing market and close, plus the paired
     bootstrap (by game, 2,000 resamples) of model minus close.
  4. line moves after pricing: |close - pricing| no-vig home probability; whether big moves (>= 2 percentage points)
     coincide with a change in the injury archive between the pricing and close times, and whether the direction agrees
     (a home player newly out/doubtful should lower the home probability).

SAMPLE SIZE NEEDED before any conclusion (planning figures; no real odds history exists yet, so the CLV spread is an
ASSUMPTION to be replaced by the observed one after the first few hundred games):
  - CLV sign and size: ASSUMING a per-game CLV standard deviation of about 0.015 (typical NBA open-to-close moves of
    1-2 percentage points), a mean CLV of +0.003 needs >= 400 games with both snapshots (about a third of a season)
    to be distinguishable from zero, and several hundred more before it can support a stake-sizing change.
  - Model vs market Brier: the paired per-game difference has a standard deviation of 0.03-0.09 depending on how far
    apart the two are (measured 0.086 between the candidate and the gradient-boosting baseline, which differ a lot;
    a market closer to the model is nearer 0.03-0.05). With 0.05, a 0.002 gap needs roughly 2,400 games (about two
    full seasons) and a 0.005 gap about 400 games. Before ~400 games treat every model-vs-market gap as noise; the
    market is normally a tough benchmark.
  - Calibration slope: about +/-0.2 (95%) at 1,500 games and +/-0.35 at 500 games.
  - Line movement vs injury news: needs >= 100 big moves (about 500-700 games with two snapshots at ~15-20% big
    moves) to compare big-move vs small-move news rates; direction agreement needs the same.
  - Real ROI: thousands of bets; this script does not compute ROI and one season of CLV is not a profit estimate.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402

ABBR_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets", "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers", "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons", "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies", "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves", "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz", "WAS": "Washington Wizards"}
NAME_TO_ABBR = {v: k for k, v in ABBR_NAMES.items()}
EPS = 1e-6
PRICING_WINDOW_MIN = (45, 80)        # minutes before tip
CLOSE_WINDOW_MIN = (0, 30)
BIG_MOVE = 0.02
BOOT = 2000


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def implied(price) -> float:
    price = float(price)
    return 100.0 / (price + 100.0) if price > 0 else -price / (-price + 100.0)


def no_vig_home(home_price, away_price) -> float:
    h, a = implied(home_price), implied(away_price)
    return h / (h + a)


def _ts(value):
    try:
        t = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(t):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def load_predictions(path: str | None) -> pd.DataFrame:
    cols = ["game_id", "home_team", "away_team", "home_win_prob", "predicted_winner", "bet_placed", "actual_winner",
            "tip_time_utc", "predicted_at", "odds", "game_date"]
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    df = pd.read_json(path) if path.lower().endswith(".json") else pd.read_csv(path, dtype={"game_id": str})
    for c in cols:
        if c not in df:
            df[c] = None
    df["game_id"] = df["game_id"].astype(str).str.zfill(10)
    p = pd.to_numeric(df["home_win_prob"], errors="coerce")
    df["home_win_prob"] = np.where(p > 1.0, p / 100.0, p)          # accept percentages
    df["home_win"] = np.where(df["actual_winner"].notna() & (df["actual_winner"].astype(str) != ""),
                              (df["actual_winner"] == df["home_team"]).astype(float), np.nan)
    side = df["bet_placed"].where(df["bet_placed"].notna() & (df["bet_placed"].astype(str) != ""), df["predicted_winner"])
    df["side_home"] = np.where(side.isna(), np.nan, (side == df["home_team"]).astype(float))
    return df


def load_archive(path: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    empty = (pd.DataFrame(columns=["captured_at", "event_id", "commence_time", "home_team", "away_team", "nba_game_id",
                                   "bookmaker_key", "market", "selection", "price_american"]),
             pd.DataFrame(columns=["captured_at", "purpose", "requests_remaining", "requests_used"]))
    if not path or not os.path.exists(path):
        return empty
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        snaps = pd.read_sql_query("select * from odds_snapshots where market = 'h2h'", conn)
        calls = pd.read_sql_query("select * from odds_calls", conn)
    except Exception:
        return empty
    finally:
        conn.close()
    return snaps, calls


def snapshot_consensus(snaps: pd.DataFrame) -> pd.DataFrame:
    """One row per (event, capture): median no-vig home prob, best home/away price, number of books."""
    if snaps.empty:
        return pd.DataFrame(columns=["event_id", "captured_at", "nv_home", "best_home", "best_away", "n_books"])
    piv = snaps[snaps["selection"].isin(["home", "away"])].pivot_table(
        index=["event_id", "captured_at", "bookmaker_key"], columns="selection", values="price_american", aggfunc="first")
    piv = piv.dropna(subset=["home", "away"]) if {"home", "away"} <= set(piv.columns) else piv.iloc[0:0]
    if piv.empty:
        return pd.DataFrame(columns=["event_id", "captured_at", "nv_home", "best_home", "best_away", "n_books"])
    piv = piv.reset_index()
    piv["nv"] = [no_vig_home(h, a) for h, a in zip(piv["home"], piv["away"])]
    g = piv.groupby(["event_id", "captured_at"])
    return g.agg(nv_home=("nv", "median"), best_home=("home", "max"), best_away=("away", "max"),
                 n_books=("nv", "size")).reset_index()


def build_game_table(preds: pd.DataFrame, snaps: pd.DataFrame, calls: pd.DataFrame) -> pd.DataFrame:
    cons = snapshot_consensus(snaps)
    if cons.empty:
        return pd.DataFrame()
    ev = snaps.groupby("event_id").agg(commence_time=("commence_time", "first"), home_team=("home_team", "first"),
                                       away_team=("away_team", "first"), nba_game_id=("nba_game_id", "first")).reset_index()
    cons = cons.merge(ev, on="event_id")
    cons["t"] = cons["captured_at"].map(_ts)
    cons["tip"] = cons["commence_time"].map(_ts)
    cons = cons.dropna(subset=["t", "tip"])
    cons["min_to_tip"] = (cons["tip"] - cons["t"]).dt.total_seconds() / 60.0
    p = preds.copy()
    p["home_full"] = p["home_team"].map(ABBR_NAMES)
    p["away_full"] = p["away_team"].map(ABBR_NAMES)
    p["pred_at"] = p["predicted_at"].map(_ts)
    by_id = {str(r.game_id): r for r in p.itertuples()}
    by_pair = {(r.home_full, r.away_full, str(r.game_date)[:10]): r for r in p.itertuples()}
    rows = []
    for event_id, g in cons.groupby("event_id"):
        first = g.iloc[0]
        pr = by_id.get(str(first["nba_game_id"])) if first["nba_game_id"] else None
        if pr is None:
            day = (first["tip"] - timedelta(hours=8)).strftime("%Y-%m-%d")           # US evening tips: local date
            pr = by_pair.get((first["home_team"], first["away_team"], day)) or by_pair.get(
                (first["home_team"], first["away_team"], first["tip"].strftime("%Y-%m-%d")))
        lo, hi = PRICING_WINDOW_MIN
        w = g[(g["min_to_tip"] >= lo) & (g["min_to_tip"] <= hi)].sort_values("t")
        if pr is not None and pd.notna(getattr(pr, "pred_at", None)) and not w.empty:
            ww = w[w["t"] <= pr.pred_at + pd.Timedelta(minutes=2)]
            w = ww.tail(1) if not ww.empty else w.head(1)
        else:
            w = w.head(1)
        clo, chi = CLOSE_WINDOW_MIN
        c = g[(g["min_to_tip"] >= clo) & (g["min_to_tip"] <= chi)].sort_values("t").tail(1)
        if w.empty:
            continue
        if not c.empty and c.iloc[0]["t"] <= w.iloc[0]["t"]:
            c = c.iloc[0:0]
        row = {"event_id": event_id, "game_id": getattr(pr, "game_id", None), "tip": first["tip"],
               "home": first["home_team"], "away": first["away_team"],
               "open_t": w.iloc[0]["t"], "open_min_to_tip": w.iloc[0]["min_to_tip"], "open_nv": w.iloc[0]["nv_home"],
               "open_best_home": w.iloc[0]["best_home"], "open_best_away": w.iloc[0]["best_away"], "n_books": w.iloc[0]["n_books"],
               "close_t": c.iloc[0]["t"] if not c.empty else pd.NaT,
               "close_min_to_tip": c.iloc[0]["min_to_tip"] if not c.empty else np.nan,
               "close_nv": c.iloc[0]["nv_home"] if not c.empty else np.nan,
               "model_home": getattr(pr, "home_win_prob", np.nan), "side_home": getattr(pr, "side_home", np.nan),
               "home_win": getattr(pr, "home_win", np.nan)}
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------

def _boot_ci(values: np.ndarray, n: int = BOOT, seed: int = 7):
    v = np.asarray(values, float)
    v = v[~np.isnan(v)]
    if len(v) < 2:
        return (float(v.mean()) if len(v) else np.nan, np.nan, np.nan, len(v))
    rng = np.random.default_rng(seed)
    means = v[rng.integers(0, len(v), (n, len(v)))].mean(1)
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), len(v)


def _fmt(t, digits=4):
    m, lo, hi, n = t
    if n == 0:
        return "n/a (n=0)"
    if np.isnan(lo):
        return f"{m:+.{digits}f} (n={n}; interval n/a)"
    return f"{m:+.{digits}f} [{lo:+.{digits}f}, {hi:+.{digits}f}] (n={n})"


def _scores(p, y):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    return (p - y) ** 2, -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _slope(y, p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    if len(p) < 30 or len(np.unique(y)) < 2:
        return np.nan
    z = np.log(p / (1 - p))
    X = np.column_stack([np.ones_like(z), z])
    b = np.array([0.0, 1.0])
    for _ in range(25):
        mu = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        W = mu * (1 - mu) + 1e-9
        step = np.linalg.solve(X.T @ (X * W[:, None]) + 1e-6 * np.eye(2), X.T @ (np.asarray(y, float) - mu))
        b = b + step
        if np.abs(step).max() < 1e-8:
            break
    return float(b[1])


def _reliability(p, y, bins=5):
    if len(p) < bins * 5:
        return None
    q = pd.qcut(pd.Series(p), bins, duplicates="drop")
    t = pd.DataFrame({"p": p, "y": y, "b": q}).groupby("b", observed=True).agg(n=("y", "size"), pred=("p", "mean"), obs=("y", "mean"))
    return t.round(3)


# ---------------------------------------------------------------------------
# injury archive
# ---------------------------------------------------------------------------

def status_map(conn, game_id: str, cutoff: pd.Timestamp) -> dict:
    """{(team_id, player key): status} from the newest report at or before cutoff that lists each team."""
    cut = cutoff.isoformat()
    df = pd.read_sql_query("select team_id, player_id, player_name_raw, report_time, status from injury_snapshots "
                           "where game_id = ? and report_time <= ?", conn, params=(game_id, cut))
    if df.empty:
        return {}
    df["report_time"] = df["report_time"].astype(str)
    df = df[df["report_time"] == df.groupby("team_id")["report_time"].transform("max")]
    key = df["player_id"].map(lambda v: f"id:{int(v)}" if pd.notna(v) else None).fillna("name:" + df["player_name_raw"].astype(str))
    return {(int(t), k): s for t, k, s in zip(df["team_id"], key, df["status"])}


def injury_change(conn, game_id: str, t0: pd.Timestamp, t1: pd.Timestamp, home_team_id: int | None):
    """(any change, signed score). score = (# home players newly out/doubtful) - (# away players newly out/doubtful)
    plus the reverse for players who came off (a return counts negative)."""
    a, b = status_map(conn, game_id, t0), status_map(conn, game_id, t1)
    bad = {"out", "doubtful"}
    changed = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
    score = 0
    for key in changed:
        team = key[0]
        delta = (b.get(key) in bad) - (a.get(key) in bad)
        score += delta if team == home_team_id else -delta
    return bool(changed), int(score)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def analyse(preds: pd.DataFrame, snaps: pd.DataFrame, calls: pd.DataFrame, injuries_path: str | None = None) -> dict:
    out: dict = {"n_predictions": int(len(preds)), "n_snapshots": int(len(snaps)), "n_calls": int(len(calls))}
    if not calls.empty and "requests_remaining" in calls and calls["requests_remaining"].notna().any():
        last = calls.sort_values("captured_at").dropna(subset=["requests_remaining"]).iloc[-1]
        out["requests_remaining_last"] = int(last["requests_remaining"])
    games = build_game_table(preds, snaps, calls)
    out["n_games_with_pricing_snapshot"] = int(len(games))
    if games.empty:
        out["note"] = "no usable games (empty archive or no snapshot 45-80 min before tip)"
        return out
    g = games.copy()
    m = g.dropna(subset=["model_home"])
    out["n_matched_to_predictions"] = int(len(m))
    # 1. model vs market at pricing
    if len(m):
        d = m["model_home"] - m["open_nv"]
        out["model_minus_market_mean"] = _boot_ci(d.values)
        out["model_market_abs_gap"] = float(np.abs(d).mean())
        out["model_market_corr"] = float(np.corrcoef(m["model_home"], m["open_nv"])[0, 1]) if len(m) > 2 else np.nan
    # 2. CLV of the priced side
    cl = g.dropna(subset=["close_nv"])
    out["n_games_with_close"] = int(len(cl))
    if len(cl):
        out["median_minutes_to_tip_open"] = float(cl["open_min_to_tip"].median())
        out["median_minutes_to_tip_close"] = float(cl["close_min_to_tip"].median())
        s = cl.dropna(subset=["side_home"])
        if len(s):
            sh = s["side_home"].values == 1
            open_side = np.where(sh, s["open_nv"], 1 - s["open_nv"])
            close_side = np.where(sh, s["close_nv"], 1 - s["close_nv"])
            out["clv_prob"] = _boot_ci(close_side - open_side)
            out["share_clv_positive"] = float(np.mean(close_side > open_side))
            sm = s.dropna(subset=["model_home"])
            if len(sm):
                model_side = np.where(sm["side_home"].values == 1, sm["model_home"], 1 - sm["model_home"])
                close_sm = np.where(sm["side_home"].values == 1, sm["close_nv"], 1 - sm["close_nv"])
                out["edge_vs_close"] = _boot_ci(model_side - close_sm)
    # 3. calibration
    o = m.dropna(subset=["home_win"])
    out["n_with_outcome"] = int(len(o))
    if len(o):
        y = o["home_win"].values
        cal = {}
        for name, col in (("model", "model_home"), ("pricing_market", "open_nv"), ("close_market", "close_nv")):
            sub = o.dropna(subset=[col])
            if len(sub):
                bs, ll = _scores(sub[col].values, sub["home_win"].values)
                cal[name] = {"n": int(len(sub)), "brier": float(bs.mean()), "log_loss": float(ll.mean()),
                             "slope": _slope(sub["home_win"].values, sub[col].values)}
        out["calibration"] = cal
        both = o.dropna(subset=["close_nv"])
        if len(both):
            bm, lm = _scores(both["model_home"].values, both["home_win"].values)
            bc, lc = _scores(both["close_nv"].values, both["home_win"].values)
            out["model_minus_close_brier"] = _boot_ci(bm - bc)
            out["model_minus_close_logloss"] = _boot_ci(lm - lc)
        rel = _reliability(o["model_home"].values, y)
        if rel is not None:
            out["reliability_model"] = rel
    # 4. line moves vs injury news
    mv = g.dropna(subset=["close_nv"]).copy()
    if len(mv):
        mv["move"] = mv["close_nv"] - mv["open_nv"]
        mv["big"] = mv["move"].abs() >= BIG_MOVE
        out["n_big_moves"] = int(mv["big"].sum())
        out["mean_abs_move"] = float(mv["move"].abs().mean())
        if injuries_path and os.path.exists(injuries_path) and mv["game_id"].notna().any():
            conn = sqlite3.connect(f"file:{injuries_path}?mode=ro", uri=True)
            try:
                ch, sc = [], []
                for r in mv.itertuples():
                    if r.game_id is None or pd.isna(r.game_id):
                        ch.append(np.nan); sc.append(np.nan); continue
                    home_id = config.TEAM_IDS.get(NAME_TO_ABBR.get(r.home))
                    c, s = injury_change(conn, str(r.game_id), r.open_t, r.close_t, home_id)
                    ch.append(float(c)); sc.append(float(s))
            finally:
                conn.close()
            mv["inj_change"], mv["inj_score"] = ch, sc
            k = mv.dropna(subset=["inj_change"])
            out["n_with_injury_comparison"] = int(len(k))
            if len(k):
                out["share_injury_change_big_moves"] = float(k[k["big"]]["inj_change"].mean()) if k["big"].any() else np.nan
                out["share_injury_change_small_moves"] = float(k[~k["big"]]["inj_change"].mean()) if (~k["big"]).any() else np.nan
                if len(k) > 2 and k["inj_score"].std() > 0 and k["move"].std() > 0:
                    out["corr_move_vs_home_injury_score"] = float(np.corrcoef(k["move"], k["inj_score"])[0, 1])
        else:
            out["injury_comparison"] = "skipped (no --injuries database, or no game ids matched)"
    out["games"] = games
    return out


def render(out: dict) -> str:
    lines = [f"predictions: {out['n_predictions']}   archived price rows: {out['n_snapshots']}   odds calls: {out['n_calls']}"]
    if "requests_remaining_last" in out:
        lines.append(f"last x-requests-remaining header: {out['requests_remaining_last']}")
    lines.append(f"games with a pricing snapshot: {out['n_games_with_pricing_snapshot']}")
    if "note" in out:
        lines.append(out["note"])
        return "\n".join(lines)
    lines.append(f"matched to predictions: {out.get('n_matched_to_predictions', 0)}   with a close snapshot: {out.get('n_games_with_close', 0)}"
                 f"   with an outcome: {out.get('n_with_outcome', 0)}")
    if "model_minus_market_mean" in out:
        lines.append(f"model minus market (home prob, at pricing): {_fmt(out['model_minus_market_mean'])}; mean |gap| "
                     f"{out['model_market_abs_gap']:.4f}; corr {out['model_market_corr']:.3f}")
    if "clv_prob" in out:
        lines.append(f"CLV of the priced side (close minus pricing, no-vig prob): {_fmt(out['clv_prob'])}; share positive "
                     f"{out['share_clv_positive']:.1%}")
    if "edge_vs_close" in out:
        lines.append(f"model edge vs the close (model prob minus no-vig close prob, priced side): {_fmt(out['edge_vs_close'])}")
    for name, c in out.get("calibration", {}).items():
        lines.append(f"{name:15s} n={c['n']:4d} Brier {c['brier']:.4f} log loss {c['log_loss']:.4f} slope {c['slope']:.2f}")
    if "model_minus_close_brier" in out:
        lines.append(f"model minus close, Brier: {_fmt(out['model_minus_close_brier'])}; log loss: {_fmt(out['model_minus_close_logloss'])}"
                     "   (negative = model better)")
    if "reliability_model" in out:
        lines.append("model reliability:\n" + out["reliability_model"].to_string())
    if "n_big_moves" in out:
        lines.append(f"line moves after pricing: mean |move| {out['mean_abs_move']:.4f}; big moves (>= {BIG_MOVE:.0%}): {out['n_big_moves']}")
    if "n_with_injury_comparison" in out:
        lines.append(f"injury change between pricing and close: big moves {out['share_injury_change_big_moves']:.1%} vs small "
                     f"{out['share_injury_change_small_moves']:.1%} (n={out['n_with_injury_comparison']}); corr(move, home injury score) "
                     f"{out.get('corr_move_vs_home_injury_score', float('nan')):.3f}")
    elif "injury_comparison" in out:
        lines.append("injury comparison " + out["injury_comparison"])
    n = out.get("n_games_with_close", 0)
    if n < 400:
        lines.append(f"\nNOTE: only {n} games have both snapshots; the docstring says >= 400 before CLV and >= ~2,400 "
                     "before a model-vs-market Brier gap of 0.002 means anything. Treat every number above as noise.")
    return "\n".join(lines)


def main(argv=None) -> int:
    try:
        from console import force_utf8_stdio

        force_utf8_stdio()
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--archive", default=config.ODDS_HISTORY_DB)
    ap.add_argument("--predictions", default=None, help="CSV/JSON export of the predictions table")
    ap.add_argument("--injuries", default=config.INJURY_LOCAL_DB)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    preds = load_predictions(args.predictions)
    snaps, calls = load_archive(args.archive)
    out = analyse(preds, snaps, calls, args.injuries)
    if args.out_dir and isinstance(out.get("games"), pd.DataFrame):
        os.makedirs(args.out_dir, exist_ok=True)
        out["games"].to_csv(os.path.join(args.out_dir, "market_vs_model_games.csv"), index=False)
    if args.json:
        print(json.dumps({k: (v if not isinstance(v, (pd.DataFrame,)) else None) for k, v in out.items()
                          if k != "games"}, default=lambda o: None if isinstance(o, float) and np.isnan(o) else str(o)))
    else:
        print(render(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
