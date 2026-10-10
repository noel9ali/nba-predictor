# Player data checkpoint

## Resume here
- Current: phase 2 done (historical injury backfill may still be running or finished, see below). Next: phase 1, step 1.1.
- Work only in `C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work` (branch `player-data-work`). Never touch
  the main checkout `C:\Users\noel9\Desktop\nba-predictor` (Task Scheduler runs production there).
- Python: `venv\Scripts\python.exe` in the worktree (its site-packages chains to the main venv via `_main_venv.pth`;
  `pdfplumber` is installed only here). Run modules from the worktree root: `venv\Scripts\python.exe -m src.injuries ...`.
- First commands on resume: `git status && git log -5 --oneline`, then
  `venv/Scripts/python.exe -m unittest tests.test_injuries` (fast, offline).
- Historical injury backfill (resumable): `venv/Scripts/python.exe -m src.injuries --backfill-from 2019-10-22 --to 2026-06-30`
  (log `logs/injury_backfill.log`; PDFs in `data/raw/injury_reports/`; rows in `data/injuries/injury_snapshots.sqlite`).
  Re-running skips cached PDFs and remembered misses.

## For Noel: start archiving before opening night (Tue Oct 20, 2026)
Register the snapshot job from the worktree (does not touch NBA-Predictor-Daily):
```
powershell -ExecutionPolicy Bypass -File C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work\scheduler\register_injury_snapshot_task.ps1
```
or with schtasks:
```
schtasks /Create /TN "NBA-Predictor-Injury-Snapshot" /SC DAILY /ST 11:00 /RI 30 /DU 12:00 /TR "cmd.exe /c C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work\scheduler\run_injury_snapshot.bat" /F
```
Standalone command it runs: `cd /d C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work && venv\Scripts\python.exe -m src.injuries --snapshot`.
After the branch is merged, re-run the .ps1 from the main checkout so the job points at main (and install `pdfplumber==0.11.10` in the main venv).

## Checklist
| Step | Status |
|---|---|
| 0.1-0.5 recon, probes, report, checkpoint, branch | done (commit 5b2c09c) |
| 2.1 migration 0001_injury_snapshots.sql | done |
| 2.2 config + name normalizer | done |
| 2.3 PDF fetch/cache + parser | done |
| 2.4 local sink, matching, latest_status, CLI, push path | done (commit 1da8778) |
| 2.5 scheduler wiring (branch only) | done (commit 8bb0bb0) |
| 2.6 historical backfill 2019-10-22..2026-06-30 | in progress (background run started 16:03 ET Oct 10) |
| 1.1 migration 0002_player_foundation.sql | todo |
| 1.2 collect_players.py (backfill + incremental) + tests | todo |
| 1.3 players + player_aliases seed, resolver switch | todo |
| 1.4 absences.py + tests | todo |
| 1.5 wire into run_pipeline.bat | todo |
| phases 3-9 | todo |

## Verification commands
- `venv/Scripts/python.exe -m unittest tests.test_injuries`
- Full suite (phase ends): `timeout 900 venv/Scripts/python.exe -m unittest discover -s tests` (316 OK at end of phase 2)

## Decisions (details in the report)
- New migrations in root `migrations/` (sequential), not `supabase/migrations/`.
- Injury parser: own pdfplumber parser (nbainjuries needs Java + pandas<3).
- Local SQLite sink for new tables until Noel applies migrations; `--push-supabase` exists but is never run here.
- Snapshot mode "latest" (one report per tick) to keep volume sane.
- `latest_status`: report_time <= as_of; per team, newest listing is current.

## Open problems / traps
- Python heredocs with backslashes mangle Windows paths (`\r` became CR). Use the Edit/Write tools for files with paths.
- `src/collect.py` SEASONS ends at 2025-26: production will not collect 2026-27 games until Noel adds it (not changed here).
- Preseason (Oct 2026) injury reports are not published, so no live 2026-27 snapshot yet.

## Last good commit
- 8bb0bb0 (plus the checkpoint/report commit after it)
