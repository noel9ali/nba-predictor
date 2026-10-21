"""Read-only readiness check for the availability (injury-aware) model before a run.

    python scripts/check_availability_ready.py [--data-dir C:\\path\\to\\checkout\\data] [--game-date 2026-10-20]

Works on COPIES of the local player-data and injury sqlite files, never on Supabase and never on the originals.
Checks: candidate artifact integrity, current rosters (all 30 teams), minutes history and ratings coverage of the
players who matter, injury-report freshness and player matching, and a no-write end-to-end projection for every
team. Prints PASS / WARN / FAIL lines; exits 1 on any FAIL.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import pandas as pd  # noqa: E402

import config  # noqa: E402

results: list[tuple[str, str]] = []


def report(level: str, msg: str) -> None:
    results.append((level, msg))
    print(f"{level:5s} {msg}")


def main() -> int:
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--data-dir", default=config.DATA_DIR)
    ap_.add_argument("--game-date", default=None, help="slate date to project for (default: today, ET)")
    args = ap_.parse_args()
    data = os.path.abspath(args.data_dir)

    tmp = tempfile.mkdtemp(prefix="avail_check_")
    player_db = os.path.join(tmp, "player_data.sqlite")
    inj_db = os.path.join(tmp, "injury_snapshots.sqlite")
    for src, dst in ((os.path.join(data, "player_data", "player_data.sqlite"), player_db),
                     (os.path.join(data, "injuries", "injury_snapshots.sqlite"), inj_db)):
        if os.path.exists(src):
            shutil.copy2(src, dst)
    os.environ["NBA_PLAYER_LOCAL_DB"] = player_db
    os.environ["NBA_PLAYER_STORE"] = "local"
    config.INJURY_LOCAL_DB = inj_db
    config.INJURY_UNMATCHED_CSV = os.path.join(tmp, "unmatched.csv")
    config.RAW_DIR = os.path.join(data, "raw")

    import availability_features as af
    import availability_predict as ap
    import injuries
    import player_store
    from minutes import project_team

    # 1. candidate artifacts (the same loader predict.py uses when the candidate is configured)
    try:
        cand = ap.load_candidate(ap.DEFAULT_CANDIDATE, required=True)
        report("PASS", f"candidate '{cand['name']}' loads and verifies ({len(cand['features'])} features)")
    except Exception as exc:  # noqa: BLE001
        cand = None
        report("FAIL", f"candidate cannot be loaded: {type(exc).__name__}: {exc}")

    # 2. player-game history
    if not os.path.exists(player_db):
        report("FAIL", f"no player_data.sqlite under {data}")
        return 1
    pg = player_store.read("player_games", columns="game_id, player_id, team_id, game_date, season, minutes")
    if pg.empty:
        report("FAIL", "player_games is empty")
        return 1
    last = str(pg["game_date"].max())
    report("PASS", f"player_games: {len(pg):,} rows, latest game {last}")
    game_date = args.game_date or datetime.now(timezone.utc).astimezone(injuries.ET).date().isoformat()
    pg_before = pg[pg["game_date"].astype(str) < game_date]

    # 3. current rosters
    rosters = ap.current_rosters()
    if len(rosters) == 30:
        report("PASS", f"current rosters cover all 30 teams (sizes {min(map(len, rosters.values()))}-"
                       f"{max(map(len, rosters.values()))})")
    else:
        report("FAIL" if not rosters else "WARN",
               f"current rosters for {len(rosters)}/30 teams (cache missing, stale, or thin): "
               "inferred rosters = last season's")

    # 4. ratings coverage and projections for every team
    cutoff = game_date
    ratings = af.RatingLookup(config.RATING_PRIMARY).for_day(cutoff)
    report("PASS" if len(ratings) > 300 else "FAIL", f"ratings available as of {cutoff}: {len(ratings)} players")
    teams = sorted(set(pg["team_id"].astype(int)) | set(rosters))
    teams = [t for t in teams if t >= 1610612737]
    bad, rows = [], []
    for t in teams:
        proj = project_team(pg_before, t, {}, rosters.get(t))
        if proj.empty:
            bad.append((t, "no projection"))
            continue
        top = proj.sort_values("base_min", ascending=False).head(8)
        rated = sum(int(p) in ratings for p in top["player_id"])
        rows.append((t, len(proj), int((proj["base_min"] > 0).sum()), rated, float(top["base_min"].sum())))
        if int((proj["base_min"] > 0).sum()) < 8:
            bad.append((t, f"only {int((proj['base_min'] > 0).sum())} players with minutes history"))
        if rated < 6:
            bad.append((t, f"only {rated}/8 of the top-minutes players are rated"))
    df = pd.DataFrame(rows, columns=["team", "roster", "with_minutes", "top8_rated", "top8_base_min"])
    report("PASS" if not bad else "WARN", f"projected {len(rows)}/{len(teams)} teams; "
           f"median roster {df['roster'].median():.0f}, median top-8 rated {df['top8_rated'].median():.0f}/8")
    for t, why in bad[:10]:
        report("WARN", f"team {t}: {why}")

    # 5. injury reports
    if not os.path.exists(inj_db):
        report("FAIL", "no injury_snapshots.sqlite: no injury data will reach the model")
    else:
        conn = sqlite3.connect(inj_db)
        n, mn, mx = conn.execute("select count(*), min(report_time), max(report_time) from injury_snapshots").fetchone()
        report("PASS" if n else "FAIL", f"injury snapshots: {n:,} rows, reports {str(mn)[:16]} .. {str(mx)[:16]}")
        if mx:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(mx)).total_seconds() / 3600
            report("PASS" if age_h < 12 else "WARN", f"newest injury report is {age_h:.1f} h old")
            nrows, nmatched = conn.execute("select count(*), sum(player_id is not null) from injury_snapshots "
                                           "where report_time = ?", (mx,)).fetchone()
            if nrows:
                share = nmatched / nrows
                report("PASS" if share > 0.97 else "WARN",
                       f"latest report: {nrows} rows, {share:.1%} matched to a player id")
            unk = conn.execute("select count(*) from injury_events where kind like '%unknown%'").fetchone()[0] \
                if conn.execute("select 1 from sqlite_master where name='injury_events'").fetchone() else 0
            report("PASS" if unk == 0 else "WARN", f"unknown status strings logged: {unk}")
        conn.close()

    # 6. end to end, no writes: one projection + candidate score for the first two teams
    if cand and len(teams) >= 2:
        try:
            home, away = teams[0], teams[1]
            as_of = datetime.now(timezone.utc)
            ga = ap.GameAvailability("0000000000", game_date, home, away, as_of, pg_all=pg, rosters=rosters)
            base = {f: 0.0 for f in cand["features"]}
            base.update({"HOME_ELO": 1500.0, "AWAY_ELO": 1500.0, "ELO_DIFF": 0.0})
            res = ap.score_with_candidate(ga, base, cand)
            ok = 0.0 < res["home_win_prob"] < 1.0 and res["prob_range_low"] <= res["prob_range_high"]
            report("PASS" if ok else "FAIL", f"end-to-end score ok: p={res['home_win_prob']:.3f} "
                   f"range {res['prob_range_low']:.3f}-{res['prob_range_high']:.3f} (neutral inputs, plumbing only)")
        except Exception as exc:  # noqa: BLE001
            report("FAIL", f"end-to-end projection failed: {type(exc).__name__}: {exc}")

    shutil.rmtree(tmp, ignore_errors=True)
    fails = [m for lvl, m in results if lvl == "FAIL"]
    print(f"\n{sum(l == 'PASS' for l, _ in results)} pass, {sum(l == 'WARN' for l, _ in results)} warn, "
          f"{len(fails)} fail")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
