"""Phase 5: does player availability improve the game model? One command, reproducible.

    venv\\Scripts\\python.exe scripts\\evaluate_availability.py [--refresh-features] [--no-archive] [--no-gb]
                                                               [--write-candidates]

Inputs (read only): the production `features` table (cached under data/eval/ after the first read; Supabase
credentials come from NBA_DOTENV_PATH or the environment), and the local player-data store
(team_availability_features, player_games, injury archive).

Evaluations, all with the production model family first (calibrated logistic, same code as src/model.py):
1. The leaderboard split (first 80% of games by date train, last 20% test: 1,596 games from 2025-02-25),
   for: baseline, +rest, +availability (rapm_lite_v1), +availability (box_value_v1), all.
2. Walk-forward by season (train on earlier seasons, test on the next), 2021-22 to 2025-26, pooled.
3. The star-out subset (a top-2 player by rating out, realized) of both.
4. Live-like: the same trained models scored with features built from the archived injury reports
   (p_play from the report at tip minus 60 minutes) instead of realized absences, on the games the archive covers.
5. Optional second family: gradient boosting with the production grid, baseline vs all.
Outputs: data/eval/availability_eval.md and .json; with --write-candidates also
data/model_leaderboard_candidates.csv and a `candidates` entry in data/model_metadata.json. Nothing is promoted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402

EVAL_DIR = os.path.join(REPO, "data", "eval")
FEATURES_CACHE = os.path.join(EVAL_DIR, "features_snapshot.json")
CANDIDATES_CSV = os.path.join(REPO, "data", "model_leaderboard_candidates.csv")
METADATA_JSON = os.path.join(REPO, "data", "model_metadata.json")
FEATURE_SET_VERSION = f"{config.AVAILABILITY_FEATURE_VERSION}+ratings:{config.RATING_VERSION}"

REST = ["rest_days_diff", "home_is_b2b", "away_is_b2b", "games_last_7_diff"]
AVAIL = ["rating_expected_diff", "value_out_diff", "home_star_out", "away_star_out", "top3_avail_diff",
         "minutes_lost_diff"]


def load_production_features(refresh: bool = False) -> pd.DataFrame:
    from nba_client import frames_from_json, frames_to_json

    if os.path.exists(FEATURES_CACHE) and not refresh:
        with open(FEATURES_CACHE, encoding="utf-8") as fh:
            return frames_from_json(fh.read())[0]
    dotenv_path = os.getenv("NBA_DOTENV_PATH")
    if dotenv_path:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path)
    from database import select_rows

    df = select_rows("features", order_by=["GAME_DATE", "GAME_ID"])
    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(FEATURES_CACHE, "w", encoding="utf-8") as fh:
        fh.write(frames_to_json([df]))
    return df


def prefixed(matrix: pd.DataFrame, tag: str) -> pd.DataFrame:
    cols = REST + AVAIL
    out = matrix[["game_id"] + cols].copy()
    return out.rename(columns={c: f"{tag}:{c}" for c in cols}).rename(columns={"game_id": "GAME_ID"})


def feature_sets(base: list[str]) -> dict[str, list[str]]:
    return {
        "baseline": base,
        "baseline+rest": base + [f"rapm:{c}" for c in REST],
        "baseline+avail_rapm": base + [f"rapm:{c}" for c in AVAIL],
        "baseline+avail_box": base + [f"box:{c}" for c in AVAIL],
        "all_rapm": base + [f"rapm:{c}" for c in REST + AVAIL],
    }


# ---------------------------------------------------------------------------
# Models and metrics (same family and code as src/model.py)
# ---------------------------------------------------------------------------

def fit(family: str, X: np.ndarray, y: np.ndarray, *, return_parts: bool = False):
    import model as prod
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(X)
    fitter = prod._fit_calibrated_logistic if family == "logistic" else prod._fit_tuned_gradient_boosting
    est, _search = fitter(scaler.transform(X), y)
    predict = lambda Xn: est.predict_proba(scaler.transform(Xn))[:, 1]  # noqa: E731
    return (predict, est, scaler) if return_parts else predict


def metrics(y, p) -> dict:
    import model as prod

    row = prod._metric_row("x", np.asarray(y), np.asarray(p))
    return {k: row[k] for k in ("test_games", "accuracy", "log_loss", "brier_score", "roc_auc", "calibration_ece",
                                "baseline_home_win_rate", "extreme_prediction_rate")}


def calibration_table(y, p, bins=10) -> list[dict]:
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0, 1, bins + 1)
    ids = np.clip(np.digitize(p, edges[1:-1], right=True), 0, bins - 1)
    out = []
    for b in range(bins):
        m = ids == b
        if m.sum():
            out.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(m.sum()),
                        "mean_pred": round(float(p[m].mean()), 3), "actual": round(float(y[m].mean()), 3),
                        "gap": round(float(y[m].mean() - p[m].mean()), 3)})
    return out


def fmt_table(rows: list[dict], cols: list[str]) -> str:
    def cell(v):
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(cell(r.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live-like features from the injury archive
# ---------------------------------------------------------------------------

def report_matrix(game_ids: set) -> tuple[pd.DataFrame, set]:
    """Wide rapm matrix with p_play from archived reports (basis 'report') for the given games, plus the set of
    games the archive actually covers (a report at or before tip minus 60 minutes)."""
    import availability_features as af
    import player_store

    pg = player_store.read("player_games", columns="game_id, player_id, team_id, game_date, season, minutes")
    archive = af.ArchivedStatus()
    lookups = {"rapm_lite_v1": af.RatingLookup("rapm_lite_v1")}
    tips = af.tip_times(sorted(pg["season"].unique()))
    rows = af.historical_rows(pg, set(), lookups, tips, p_play_fn=archive.p_play, basis="report",
                              game_ids=game_ids)
    feats = pd.DataFrame(rows)
    covered = {r["game_id"] for r in rows if archive.covered(r["game_id"], r["as_of"])}
    sides = player_store.query("select distinct game_id, team_id, is_home from player_games")
    feats = feats.merge(sides, on=["game_id", "team_id"])
    home = feats[feats["is_home"] == 1].set_index("game_id")[af.FEATURES].add_prefix("home_")
    away = feats[feats["is_home"] == 0].set_index("game_id")[af.FEATURES].add_prefix("away_")
    wide = home.join(away, how="inner")
    for f in af.FEATURES:
        wide[f"{f}_diff"] = wide[f"home_{f}"] - wide[f"away_{f}"]
    return wide.reset_index(), covered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--refresh-features", action="store_true")
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--no-gb", action="store_true")
    parser.add_argument("--write-candidates", action="store_true")
    parser.add_argument("--save-candidates", action="store_true",
                        help="save the trained candidate models to data/candidates/ for predict-time shadow use")
    args = parser.parse_args(argv)
    try:
        from console import force_utf8_stdio

        force_utf8_stdio()
    except Exception:
        pass

    import availability_features as af
    import model as prod
    import player_store

    base_cols = list(prod.FEATURES)
    feats = load_production_features(args.refresh_features)
    feats["GAME_ID"] = feats["GAME_ID"].astype(str).str.zfill(10)
    rapm = prefixed(af.model_matrix("rapm_lite_v1"), "rapm")
    box = prefixed(af.model_matrix("box_value_v1"), "box")
    df = feats.merge(rapm, on="GAME_ID", how="left").merge(box, on="GAME_ID", how="left")
    seasons = player_store.query("select distinct game_id as GAME_ID, season from player_games")
    df = df.merge(seasons, on="GAME_ID", how="left")
    extra = [c for c in df.columns if c.startswith(("rapm:", "box:"))]
    missing_avail = int(df[extra].isna().any(axis=1).sum())
    df[extra] = df[extra].fillna(0.0)          # games before the first rating refit: neutral
    sets = feature_sets(base_cols)
    out_md, results = [], {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "feature_set_version": FEATURE_SET_VERSION, "missing_availability_rows": missing_avail}

    # 1. Leaderboard split (identical to src/model.py run()).
    train, test = prod.split_data(df)
    train, test = prod._clean_frame(train), prod._clean_frame(test)
    ytr, yte = train[prod.TARGET].astype(int).to_numpy(), test[prod.TARGET].astype(int).to_numpy()
    star = ((test["rapm:home_star_out"] == 1) | (test["rapm:away_star_out"] == 1)).to_numpy()
    lb_rows, preds, models = [], {}, {}
    saved = {"baseline+avail_rapm": "lr-calibrated-availability-v1", "all_rapm": "lr-calibrated-availability-rest-v1"}
    for name, cols in sets.items():
        predict, est, scaler = fit("logistic", train[cols].to_numpy(float), ytr, return_parts=True)
        models[name] = (predict, cols)
        if args.save_candidates and name in saved:
            from availability_predict import save_candidate

            path = save_candidate(saved[name], est, scaler, cols, {"feature_set": name, "trained_on":
                                  "leaderboard train split", "feature_set_version": FEATURE_SET_VERSION})
            print(f"saved {path}")
        p = predict(test[cols].to_numpy(float))
        preds[name] = p
        lb_rows.append({"feature_set": name, "subset": "all", **metrics(yte, p)})
        lb_rows.append({"feature_set": name, "subset": "star_out", **metrics(yte[star], p[star])})
    results["leaderboard_split"] = {"train_games": int(len(train)), "test_games": int(len(test)),
                                    "cutoff_date": str(test["GAME_DATE"].min())[:10], "rows": lb_rows,
                                    "calibration": {k: calibration_table(yte, v) for k, v in preds.items()}}
    cols = ["feature_set", "subset", "test_games", "accuracy", "log_loss", "brier_score", "roc_auc",
            "calibration_ece"]
    out_md += ["## Leaderboard split (calibrated logistic)",
               f"Train {len(train)} games, test {len(test)} games from {str(test['GAME_DATE'].min())[:10]}; "
               f"{int(star.sum())} test games have a top-2 player out (realized). "
               f"{missing_avail} feature rows had no availability values (filled with 0).", "",
               fmt_table(lb_rows, cols), ""]
    for k in ("baseline", "all_rapm"):
        out_md += [f"Calibration, {k}:", "", fmt_table(results["leaderboard_split"]["calibration"][k],
                                                      ["bin", "n", "mean_pred", "actual", "gap"]), ""]

    # 2. Walk-forward by season.
    wf_rows, wf_season = [], []
    test_seasons = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
    clean_all = prod._clean_frame(df)
    pooled = {k: ([], [], []) for k in sets}
    for season in test_seasons:
        tr = clean_all[clean_all["season"] < season]
        te = clean_all[clean_all["season"] == season]
        if tr.empty or te.empty:
            continue
        y_tr, y_te = tr[prod.TARGET].astype(int).to_numpy(), te[prod.TARGET].astype(int).to_numpy()
        so = ((te["rapm:home_star_out"] == 1) | (te["rapm:away_star_out"] == 1)).to_numpy()
        for name, cols_ in sets.items():
            p = fit("logistic", tr[cols_].to_numpy(float), y_tr)(te[cols_].to_numpy(float))
            pooled[name][0].append(y_te)
            pooled[name][1].append(p)
            pooled[name][2].append(so)
            m = metrics(y_te, p)
            wf_season.append({"season": season, "feature_set": name, "test_games": m["test_games"],
                              "brier_score": m["brier_score"], "log_loss": m["log_loss"], "accuracy": m["accuracy"]})
    for name, (ys, ps, sos) in pooled.items():
        if not ys:
            continue
        y, p, so = np.concatenate(ys), np.concatenate(ps), np.concatenate(sos)
        wf_rows.append({"feature_set": name, "subset": "all", **metrics(y, p)})
        wf_rows.append({"feature_set": name, "subset": "star_out", **metrics(y[so], p[so])})
    results["walk_forward"] = {"seasons": test_seasons, "pooled": wf_rows, "by_season": wf_season}
    out_md += ["## Walk-forward by season, pooled 2021-22 to 2025-26 (calibrated logistic)", "",
               fmt_table(wf_rows, cols), "", "Brier by season:", "",
               fmt_table(wf_season, ["season", "feature_set", "test_games", "brier_score", "log_loss", "accuracy"]),
               ""]

    # 3. Live-like: models trained on realized features, scored on archived-report features.
    if not args.no_archive:
        try:
            wide, covered = report_matrix(set(test["GAME_ID"]))
            rep = prefixed(wide, "rapm")
            te_rep = test[["GAME_ID", prod.TARGET] + base_cols].merge(rep, on="GAME_ID", how="inner")
            te_rep = te_rep[te_rep["GAME_ID"].isin(covered)]
            te_real = test[test["GAME_ID"].isin(te_rep["GAME_ID"])].set_index("GAME_ID").loc[te_rep["GAME_ID"]]
            y_rep = te_rep[prod.TARGET].astype(int).to_numpy()
            live_rows = []
            for name in ("baseline", "baseline+avail_rapm", "all_rapm"):
                predict, cols_ = models[name]
                live_rows.append({"feature_set": name, "features_from": "report (live-like)",
                                  **metrics(y_rep, predict(te_rep[cols_].to_numpy(float)))})
                live_rows.append({"feature_set": name, "features_from": "realized (hindsight)",
                                  **metrics(y_rep, predict(te_real[cols_].to_numpy(float)))})
            results["live_like"] = {"games": int(len(te_rep)), "rows": live_rows}
            out_md += ["## Live-like: archived injury reports (5 PM ET report, p_play from status)",
                       f"{len(te_rep)} of {len(test)} leaderboard test games have an archived report at or before "
                       "tip minus 60 minutes. Same trained models; only the availability inputs change.", "",
                       fmt_table(live_rows, ["feature_set", "features_from", "test_games", "accuracy", "log_loss",
                                             "brier_score", "roc_auc", "calibration_ece"]), ""]
        except Exception as exc:
            out_md += [f"## Live-like evaluation skipped: {type(exc).__name__}: {exc}", ""]

    # 4. Gradient boosting (second family).
    if not args.no_gb:
        gb_rows = []
        for name in ("baseline", "all_rapm"):
            cols_ = sets[name]
            p = fit("gb", train[cols_].to_numpy(float), ytr)(test[cols_].to_numpy(float))
            gb_rows.append({"feature_set": name, "subset": "all", **metrics(yte, p)})
            gb_rows.append({"feature_set": name, "subset": "star_out", **metrics(yte[star], p[star])})
        results["gradient_boosting"] = gb_rows
        out_md += ["## Gradient boosting (production grid), leaderboard split", "", fmt_table(gb_rows, cols), ""]

    # 5. Promotion check against production and the same-family baseline.
    lb = pd.read_csv(os.path.join(REPO, "data", "model_leaderboard.csv"))
    prod_row = lb.iloc[0].to_dict()
    cand = next(r for r in lb_rows if r["feature_set"] == "all_rapm" and r["subset"] == "all")
    base = next(r for r in lb_rows if r["feature_set"] == "baseline" and r["subset"] == "all")
    checks = []
    for label, ref in ((f"production {prod_row['model']}", prod_row), ("same-family baseline", base)):
        d_brier = float(ref["brier_score"]) - cand["brier_score"]
        d_ll = float(ref["log_loss"]) - cand["log_loss"]
        checks.append({"against": label, "brier_improvement": round(d_brier, 5), "log_loss_improvement": round(d_ll, 5),
                       "passes_rule": bool(d_brier >= 0.001 and d_ll >= 0)})
    results["promotion_check"] = checks
    # Promotion is deliberately stricter than the fixed split: calibration bias must not worsen.
    base_cal = results["leaderboard_split"]["calibration"].get("baseline", [])
    cand_cal = results["leaderboard_split"]["calibration"].get("all_rapm", [])
    base_ece = float(base.get("calibration_ece") or 0.0)
    cand_ece = float(cand.get("calibration_ece") or 0.0)
    results["evaluation_gate"] = {
        "fixed_split_games": int(len(test)),
        "missing_availability_rows": missing_avail,
        "availability_coverage": round(1 - (missing_avail / len(df) if len(df) else 1), 6),
        "walk_forward_present": bool(wf_rows),
        "live_like_present": "live_like" in results,
        "calibration_ece_baseline": base_ece, "calibration_ece_candidate": cand_ece,
        "no_new_calibration_bias": cand_ece <= base_ece,
        "human_approval_required": True,
        "promote": bool(checks[0]["passes_rule"] and cand_ece <= base_ece and wf_rows),
    }
    out_md += ["## Promotion rule (Brier better by >= 0.001 and log loss no worse); nothing is promoted", "",
               fmt_table(checks, ["against", "brier_improvement", "log_loss_improvement", "passes_rule"]), ""]

    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(os.path.join(EVAL_DIR, "availability_eval.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=float)
    with open(os.path.join(EVAL_DIR, "availability_eval.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out_md))
    print("\n".join(out_md))

    if args.write_candidates:
        write_candidates(lb_rows, results)
    return 0


def write_candidates(lb_rows: list[dict], results: dict) -> None:
    """Candidate rows in a separate leaderboard file (the production leaderboard must keep its invariants:
    every row is a selectable model and ranks follow log loss), plus a `candidates` entry in the metadata."""
    trained = results["generated_at"]
    names = {"baseline+rest": "lr-calibrated-rest-v1", "baseline+avail_rapm": "lr-calibrated-availability-v1",
             "baseline+avail_box": "lr-calibrated-availability-box-v1", "all_rapm": "lr-calibrated-availability-rest-v1"}
    rows = [{"model": names[r["feature_set"]], "feature_set": r["feature_set"],
             "feature_set_version": results["feature_set_version"], "evaluated_at": trained,
             "artifact_path": f"data/candidates/{names[r['feature_set']]}.pkl",
             **{k: r[k] for k in ("test_games", "accuracy", "log_loss", "brier_score", "roc_auc", "calibration_ece",
                                  "baseline_home_win_rate", "extreme_prediction_rate")}}
            for r in lb_rows if r["subset"] == "all" and r["feature_set"] in names]
    pd.DataFrame(rows).sort_values("log_loss").to_csv(CANDIDATES_CSV, index=False)
    with open(METADATA_JSON, encoding="utf-8") as fh:
        meta = json.load(fh)
    meta["candidates"] = {"path": "data/model_leaderboard_candidates.csv", "evaluated_at": trained,
                          "feature_set_version": results["feature_set_version"],
                          "models": [r["model"] for r in rows], "rows": rows, "promoted": False,
                          "promotion_check": results["promotion_check"]}
    with open(METADATA_JSON, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
        fh.write("\n")
    print(f"wrote {CANDIDATES_CSV} and the candidates entry in {METADATA_JSON}")


if __name__ == "__main__":
    sys.exit(main())
