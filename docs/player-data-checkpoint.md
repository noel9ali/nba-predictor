# Player data checkpoint

## Resume here (written Oct 10, 2026, ~17:10 ET; session paused at the user's request)

**State:** phases 0-4 done; phase 6 done (code + tests); phase 5 and 7 in progress; phases 8-9 not started.
All work is committed on branch `player-data-work` (worktree
`C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work`). Never touch the main checkout
`C:\Users\noel9\Desktop\nba-predictor` (Task Scheduler runs production there). Never push, merge, write to Supabase or
apply migrations.

**Possibly still running when this was written:** `python -m src.injuries --reparse` (log `logs/injury_reparse.log`),
followed by `--rematch`. Both are local-only and idempotent. On resume, check whether they finished:
`tail -3 logs/injury_reparse.log`. If not finished or unsure, simply re-run (from the worktree root):
```
venv/Scripts/python.exe -m src.injuries --reparse
venv/Scripts/python.exe -m src.injuries --rematch
```
Sanity check afterwards (should show rows for 2019-10 onward and few null game_ids):
```
venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('data/injuries/injury_snapshots.sqlite'); print(c.execute('select substr(game_date,1,4), count(*), sum(game_id is null), sum(player_id is null) from injury_snapshots group by 1').fetchall())"
```

**First commands on resume:**
```
git status && git log -5 --oneline
venv/Scripts/python.exe -m unittest tests.test_injuries tests.test_player_data tests.test_ratings_minutes tests.test_availability tests.test_scenarios tests.test_factors tests.test_betting tests.test_predict_availability tests.test_api_availability tests.test_api_v2
```
(all offline; 94 + API suites were green at pause time; full suite last run 325 OK after phase 1, run it again at phase ends:
`timeout 900 venv/Scripts/python.exe scripts/run_offline_tests.py`).

**Next steps, in order:**
1. Phase 5 finish: after reparse/rematch, run the full evaluation and save the artifacts:
   ```
   venv/Scripts/python.exe scripts/evaluate_availability.py --write-candidates --save-candidates
   ```
   (features table is cached in `data/eval/features_snapshot.json`; no Supabase read needed). It runs the leaderboard
   split, walk-forward, star-out subset, live-like (archived reports), gradient boosting and the promotion check, and
   writes `data/eval/availability_eval.md` (git-ignored) + `data/model_leaderboard_candidates.csv` +
   `data/model_metadata.json` `candidates` entry. Then paste the tables into the report's phase 5 section, replacing
   "Preliminary results", and write an honest promotion recommendation based on the LIVE-LIKE numbers (realized-feature
   results are hindsight). Commit `data/model_leaderboard_candidates.csv`, `data/model_metadata.json`, the report.
   Check `tests/test_model_publish.py` still passes after the metadata change.
2. Phase 7 finish: sample data. In `scripts/build_sample_data.py` add rows for tonight's games to the fake tables
   (`Tables` needs new lists: injury_snapshots, player_minutes_projection, player_ratings, team_availability_features,
   prediction_scenarios, prediction_factors, prediction_availability_inputs) with a few out / questionable /
   status_changed examples and one game with scenarios + factors (set its predictions.model_name to the candidate),
   write `injuries-2026-11-17.json` via `fetch(tables, "/api/injuries?date=2026-11-17")`, add `"injuries"` to
   `shape_for` in `tests/test_sample_data.py` (INJURIES shape), label it sample data, regenerate
   (`venv/Scripts/python.exe scripts/build_sample_data.py`; it is deterministic, other files only gain the new fields),
   run `tests.test_sample_data`. Commit.
3. Phase 8 props groundwork (spec sec11): `migrations/0007_market_odds.sql` (+ dual-write moneylines in `src/odds.py`
   through a non-fatal local/supabase path), `migrations/0008_player_rates.sql` + nightly `player_rate_stats`
   (shrunk per-minute rates, reuse ratings.box shrinkage idea), `migrations/reserved/NNNN_prop_predictions.sql`
   (clearly NOT to apply), reserved `prop_*` section in the contract, `src/props/__init__.py` + `src/props/README.md`
   (flow, open issues, odds-provider prop markets from the report's phase 0 section).
4. Phase 9: finish the report (what was built per phase, eval tables, recommendation, config values and why,
   deviations, risks, exact commands, migrations in order). Run the full suite. Final commit.

## For Noel: start archiving before opening night (Tue Oct 20, 2026)
```
powershell -ExecutionPolicy Bypass -File C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work\scheduler\register_injury_snapshot_task.ps1
```
or
```
schtasks /Create /TN "NBA-Predictor-Injury-Snapshot" /SC DAILY /ST 11:00 /RI 30 /DU 12:00 /TR "cmd.exe /c C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work\scheduler\run_injury_snapshot.bat" /F
```
Standalone: `cd /d C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work && venv\Scripts\python.exe -m src.injuries --snapshot`.

## Checklist
| Step | Status |
|---|---|
| 0 recon, probes, report, checkpoint, branch | done |
| 2.1-2.5 migration 0001, parser (3 layouts), archiver, sink, latest_status, CLI, scheduler scripts | done |
| 2.6 historical archive backfill 2019-10-22..2026-06-30 (1 report/day) | done (PDFs in data/raw/injury_reports) |
| 2.7 reparse (2019 layout) + rematch (overrides, schedule union) | in progress / re-run on resume |
| 1.1-1.5 migration 0002, player_store, collect_players, aliases, absences (with spells), wiring | done |
| 3.1-3.5 migration 0003 (+min_if_play), ratings (183 refits, alpha 10), minutes v1, worked example | done |
| 4.1-4.2 migration 0004, availability_features backfill (33,156 rows), tests | done |
| 5.1 evaluation script + realized-feature results | done |
| 5.2 live-like eval, GB, candidates CSV/metadata, saved artifacts, recommendation | todo (step 1 above) |
| 6.1-6.5 betting.py, scenarios, factors, availability_predict, predict.py hook, migration 0005, dry-run tests | done |
| 7.1 contract, api_availability, routes, budgets, migration 0006, API tests | done |
| 7.2 sample JSON with availability examples | todo (step 2 above) |
| 8 props groundwork | todo |
| 9 report and handoff | todo |

## Local data (git-ignored, already built in the worktree)
- `data/player_data/player_data.sqlite`: player_games 176,738; players 5,240; player_aliases 10,386;
  player_absences 33,620; player_ratings (183 as_of dates x 2 types); team_availability_features 33,156.
- `data/injuries/injury_snapshots.sqlite` (+ `injury_unmatched.csv`), `data/raw/injury_reports/*.pdf` (archive),
  `data/raw/nba_api/*.json` caches, `data/eval/` (features snapshot, eval outputs).

## Decisions (details in the report)
- New migrations in root `migrations/` (sequential), not `supabase/migrations/`.
- Own pdfplumber parser; snapshot mode "latest"; `latest_status` uses report_time <= as_of, newest listing per team.
- All new tables go through `src/player_store.py` (local SQLite default; `NBA_PLAYER_STORE=supabase` later).
- Ridge alpha fixed at 10 by pooled forward validation; RAPM beats box prior out of sample.
- team_availability_features PK includes rating_type (deviation).
- New pipeline steps are non-fatal; availability step in predict is shadow-only unless NBA_PRODUCTION_MODEL names the
  candidate. Candidates live in a separate CSV (+ metadata entry), not in the production leaderboard (its invariants:
  every row selectable, ranks by log loss).
- New API reads never flag migration_pending on existing routes.

## Open problems / traps
- Python heredocs (`python - <<'EOF'`) with backslashes mangle text (`\r`, `\a` become control chars). Use the
  Edit/Write tools for files with Windows paths; check `.bat` files keep CRLF (`file run_pipeline.bat`).
- `sed -i` on CRLF files drops CRLF in this Git Bash; re-normalize afterwards.
- Do not run `run_pipeline.bat`/`run_predict.bat`: other steps write to production Supabase.
- `src/collect.py` SEASONS ends at 2025-26 (production won't collect 2026-27 until Noel adds it).
- No preseason injury reports are published; no live 2026-27 snapshot yet.
- Realized-availability results are hindsight; only the live-like archive evaluation supports a recommendation.

## Last good commit
- see `git log -1` (docs commit "Pause: checkpoint and report for resume")
