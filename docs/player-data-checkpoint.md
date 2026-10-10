# Player data checkpoint

## Resume here
- Current: phases 0, 1, 2 done. Next: phase 3, step 3.1 (migration `0003_player_ratings.sql` + ratings module).
- Work only in `C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work` (branch `player-data-work`). Never touch
  the main checkout `C:\Users\noel9\Desktop\nba-predictor` (Task Scheduler runs production there).
- Python: `venv\Scripts\python.exe` in the worktree (site-packages chain to the main venv via `_main_venv.pth`;
  `pdfplumber` installed only here). Run from the worktree root.
- First commands on resume: `git status && git log -5 --oneline`, then
  `venv/Scripts/python.exe -m unittest tests.test_injuries tests.test_player_data` (fast, offline).
- Local data (git-ignored, already built): `data/player_data/player_data.sqlite` (player_games 176,738 rows, players
  5,240, player_aliases 10,386, player_absences 20,194), `data/raw/nba_api/` caches,
  `data/injuries/injury_snapshots.sqlite`, `data/raw/injury_reports/*.pdf`.
- Historical injury backfill (resumable; started 16:03 ET Oct 10 in the background, ~1 h):
  `venv/Scripts/python.exe -m src.injuries --backfill-from 2019-10-22 --to 2026-06-30` (log `logs/injury_backfill.log`).
  If it was cut off, re-run the same command: cached PDFs and known misses are skipped.

## For Noel: start archiving before opening night (Tue Oct 20, 2026)
```
powershell -ExecutionPolicy Bypass -File C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work\scheduler\register_injury_snapshot_task.ps1
```
or
```
schtasks /Create /TN "NBA-Predictor-Injury-Snapshot" /SC DAILY /ST 11:00 /RI 30 /DU 12:00 /TR "cmd.exe /c C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work\scheduler\run_injury_snapshot.bat" /F
```
Standalone command: `cd /d C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work && venv\Scripts\python.exe -m src.injuries --snapshot`.

## Checklist
| Step | Status |
|---|---|
| 0.1-0.5 recon, probes, report, checkpoint, branch | done (5b2c09c) |
| 2.1-2.4 migration 0001, parser, archiver, sink, latest_status, CLI | done (1da8778) |
| 2.5 scheduler wiring (branch only) | done (8bb0bb0) |
| 2.6 historical injury backfill | in progress (background) |
| 1.1 migration 0002_player_foundation.sql + player_store | done (f29d2a4) |
| 1.2 collect_players backfill + incremental | done, verified vs games |
| 1.3 players + player_aliases, resolver switch | done |
| 1.4 absences.py | done |
| 1.5 run_pipeline.bat wiring | done (4f03344) |
| 3.1 migration 0003_player_ratings.sql | todo |
| 3.2 box_value_v1 ratings | todo |
| 3.3 rapm_lite_v1 ratings (ridge, time-ordered CV, weekly backfill) | todo |
| 3.4 minutes projection v1 | todo |
| 3.5 nightly refresh wiring + worked example | todo |
| phases 4-9 | todo |

## Verification commands
- `venv/Scripts/python.exe -m unittest tests.test_injuries tests.test_player_data`
- Full suite (phase ends): `timeout 900 venv/Scripts/python.exe scripts/run_offline_tests.py` (325 OK after phase 1)

## Decisions (details in the report)
- New migrations in root `migrations/` (sequential), not `supabase/migrations/`.
- Injury parser: own pdfplumber parser. Snapshot mode "latest". `latest_status` uses report_time <= as_of.
- All new tables go through `src/player_store.py` (local SQLite default; `NBA_PLAYER_STORE=supabase` after migrations).
- Absence typical minutes = average over games played in the previous 10 team games.
- New pipeline steps are non-fatal for now.

## Open problems / traps
- Python heredocs with backslashes mangle Windows paths. Use Edit/Write tools, or bash `cat <<'EOF'`.
- Do not run `run_pipeline.bat`/`run_predict.bat`: their other steps write to production Supabase.
- `src/collect.py` SEASONS ends at 2025-26 (production won't collect 2026-27 until Noel adds it).
- No preseason injury reports are published, so no live 2026-27 snapshot yet.
- `LeagueGameLog` MIN is an integer; `started` is null.

## Last good commit
- 4f03344 (+ the docs commit after it)
