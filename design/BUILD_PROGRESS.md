# Dashboard build: progress log

Brief: `..\agent-prompts\05-dashboard-build-agent.md` (the approved plan is in `C:\Users\noel9\.claude\plans\pasted-content-id-390e-you-re-building-goofy-castle.md`).
Branch `dashboard-build`, worktree `C:\Users\noel9\Desktop\nba-predictor.worktrees\dashboard-build`. Never merge to `main`, never `vercel deploy --prod`, never push `main` until Noel approves.

## How to resume
1. Read this file, then `design/DESIGN_STATE.md` and the approved canvas boards snapshotted in `design/canvas/` (Nav-Final, Nav-Pipeline, Games, Games-Controls, Games-Transitions, Edge-Hero, Edge-Cards, Edge-Page, Detail-A, Perf-Final). The live canvas is https://claude.ai/code/artifact/a702b1d5-c99f-4bf4-b134-aa7cb93049c2 (read with the Artifact tool).
2. Tests: `venv\Scripts\python scripts\run_offline_tests.py` (network blocked, pipeline spawn guard, dummy env; INC-1). Never run two suites in the same tree at once.
3. Venv: `py -3.12 -m venv venv` + `venv\Scripts\pip install -r requirements.txt`.

## Done
| Step | What | Commit |
|---|---|---|
| 0 | Worktree off main d4fd9b6; excludeFiles fix carried over | a944a26 |

## Next
- Step 0: commit this log, `design/canvas/`, `scripts/run_offline_tests.py`.
- Step 1: read endpoints (B5/B6) in `app.py` + `tests/test_api_v2.py`, `tests/contract_shapes.py`.
- Step 2: serving (B9): `/` → `public/index.html`, `/legacy`, `/sample/*`, vercel.json header rules, move legacy tests to `/legacy`.
- Steps 3–9: shell, sample data, Games, drawer, Performance, a11y, verification.
- Step 10: preview deploy, smoke test, STOP for review.

## Decisions / deviations so far
- Pre-Gate M `record`/`l10` are null ("—"): `games` holds only home rows until the re-collect, so computed records would be wrong.
- `/api/slate` adds `offseason` and `last_slate_date`; `no_games` vs `before_predictions` uses "latest prediction within 7 days" until a schedule source exists.
- Pipeline pill shows "status unavailable" while `workflow_log` is missing (not a designed state).
- `/api/predictions` paginates in pandas (season ≤ 1,230 rows) instead of `select_page`.
- Sample mode adds `&scene=` to review every hero/page state.

## Open questions
- None yet.
