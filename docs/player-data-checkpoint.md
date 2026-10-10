# Player data checkpoint

## Resume here
- Current: phase 2, step 2.1 (migration file `migrations/0001_injury_snapshots.sql`) not started. Phase 0 is done.
- Work only in `C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work` (branch `player-data-work`). Never touch the main checkout.
- Python: `venv\Scripts\python.exe` in the worktree (chains to the main venv; `pdfplumber` installed here only).
- First command on resume: `git status && git log -5 --oneline`.

## Checklist
| Step | Status |
|---|---|
| 0.1 canonical branch | done (main df2b615) |
| 0.2 blockers | done (resolved upstream; collect.py SEASONS lacks 2026-27, flagged) |
| 0.3 database conventions | done |
| 0.4 probes | done (see report) |
| 0.5 report, checkpoint, branch, first commit | done |
| 2.1 migration 0001_injury_snapshots.sql | todo |
| 2.2 config + name normalizer | todo |
| 2.3 PDF fetch/cache + parser | todo |
| 2.4 local sink, matching, latest_status, CLI | todo |
| 2.5 scheduler wiring (branch only) + tests + live/fixture run | todo |
| phases 1, 3-9 | todo |

## Decisions
- New migrations in root `migrations/` (sequential), not `supabase/migrations/`.
- Injury parser: own pdfplumber parser (nbainjuries needs Java + pandas<3).
- Local sink for injury rows until Noel applies the migration.

## Open problems
- None yet.

## Last good commit
- (see git log)
