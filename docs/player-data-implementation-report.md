# Player data: implementation report

Branch `player-data-work` (worktree `C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work`), branched from `main` at `df2b615`.
Spec: `docs/player-data-backend-spec.md`. Resume point: `docs/player-data-checkpoint.md`.

## Phase checklist

| Phase | Name | Status |
|---|---|---|
| 0 | Recon and preconditions | done |
| 1 | Player data foundation | todo |
| 2 | Injury snapshot ingestion | in progress |
| 3 | Ratings and minutes projections | todo |
| 4 | Availability features and rest days | todo |
| 5 | Candidate model and walk-forward evaluation | todo |
| 6 | Predict-time integration | todo |
| 7 | API, contract, sample data | todo |
| 8 | Props groundwork | todo |
| 9 | Report and handoff | todo |

## Phase 0: recon and preconditions (done, Oct 10, 2026)

### Context documents
The `claude/...` project docs the spec refers to (`claude/agent-memory/noel-workflow.md`, `claude/integration-findings.md`,
`claude/design-state-and-backend-requirements.md`) are not in this repo. Work proceeded from the spec, `README.md` and
`design/hardwood/STATE.md`. No Projects tool was available to mirror the checkpoint to `claude/player-data-checkpoint.md`.

### Step 1: canonical branch
- Canonical backend branch is `main` (`df2b615`). The old `backend` branch (worktree `nba-model-integration-lstm-gb-rf`) is fully
  merged into main, and production deploys from main. `data/model_metadata.json` and `data/model_leaderboard.csv` are tracked on main.
- The main checkout `C:\Users\noel9\Desktop\nba-predictor` is where Task Scheduler runs production, so all work happens in a separate
  worktree on `player-data-work`. Nothing in the main checkout is modified.
- Python: the worktree has its own `venv` (git-ignored) whose `site-packages` chains to the main venv through a `.pth` file
  (`venv\Lib\site-packages\_main_venv.pth`), so the production venv is never modified. New packages (only `pdfplumber==0.11.10`
  so far) are installed into the worktree venv only and pinned in `requirements-pipeline.txt`.

### Spec drift reconciled
- **Baseline model.** The spec quotes `legacy-calibrated-logistic` at 68.2% / Brier 0.2089. Production is now
  `gradient-boosting-gridsearch` (since 2026-10-07). Baseline reference from the tracked `data/model_leaderboard.csv`
  (1,596 test games, 55.0% home base rate, cutoff 2025-02-25):

  | Model | Accuracy | Log loss | Brier | AUC | ECE |
  |---|---|---|---|---|---|
  | gradient-boosting-gridsearch (production) | 67.9% | 0.6075 | 0.2094 | 0.729 | 0.035 |
  | legacy-calibrated-logistic | 68.1% | 0.6325 | 0.2091 | 0.729 | 0.031 |

  Phase 5 compares candidates against both rows: the logistic row for an attributable same-family comparison, the GB row because it
  is what a promotion would replace.
- **Migrations folder.** The repo keeps applied schema in `supabase/migrations/` (timestamp names, 13 files, applied at Gate M on Oct 7).
  As instructed, new migrations go to a separate root `migrations/` folder with sequential names (`0001_...sql`) so nothing can be
  applied by accident with the Supabase CLI. When Noel applies them, they can be copied into `supabase/migrations/` with timestamp names.
- **Scheduler script.** `task_scheduler_setup.ps1` is at `scheduler/task_scheduler_setup.ps1` (with `scheduler/README_scheduler.md`
  and `scheduler/run_daily.bat`). There is only one scheduled job today (`NBA-Predictor-Daily`, 06:00, runs `daily_workflow.py`, which
  runs `run_pipeline.bat` then `run_predict.bat`). The "every 30 minutes 11:00 to 22:00 predict tick" the spec mentions does not exist.
  `daily_workflow.py` has no `--morning` / `--predict` modes; the morning steps live in `run_pipeline.bat`.

### Step 2: integration blockers (resolved upstream)
Read-only checks against Supabase (row counts and one row per table through `src/database.py`, no writes) plus the applied
migrations in `supabase/migrations/`:
- `games` PK: `20260923000200_games_composite_pk.sql` (GAME_ID, TEAM_ID), applied at Gate M; `collect.py` upserts with
  `GAMES_CONFLICT_COLUMNS = ["GAME_ID", "TEAM_ID"]`. `games` has 16,578 rows, `GAME_ID` is text (`'0022501188'`).
- `bankroll` (18 rows) and `workflow_log` (0 rows) exist.
- `features` numeric columns come back as int/float (`20260923000300_numeric_and_date_types.sql` applied).
- No blocker remains. PK definitions themselves cannot be read through PostgREST; the evidence is the applied migration plus the
  working upsert.
- **New risk found (not a spec blocker, flagged for Noel):** `src/collect.py` has a hard-coded `SEASONS` list ending at `2025-26`.
  The 2026-27 season opens Tue Oct 20, 2026, and the morning pipeline will not collect any 2026-27 games until `'2026-27'` is added.
  This branch does not change `collect.py` (production code path); new player collectors derive the season list from the date.

### Step 3: database conventions
`src/database.py` exposes `select_rows`, `insert_rows`, `upsert_rows(conflict_columns=...)`, `update_rows`, `count_rows`,
`select_page`, `call_rpc` and `normalize_game_id`. It is Supabase-only (no SQLite path). Errors map to `MissingTableError` /
`MissingColumnError` / `DuplicateRecordError`. Modules in `src/` import each other flat (`from database import ...`) with `src/` on
`sys.path`. New code follows the same pattern. Because new tables do not exist until Noel applies migrations, collectors also write
to a local SQLite sink (see phase 2).

### Step 4: probe results

**nba_api `LeagueGameLog` (player mode, 2025-26 regular season).** One call, 1.4 s, 26,651 rows, 32 columns:
`SEASON_ID, PLAYER_ID, PLAYER_NAME, TEAM_ID, TEAM_ABBREVIATION, TEAM_NAME, GAME_ID, GAME_DATE, MATCHUP, WL, MIN, FGM, FGA, FG_PCT,
FG3M, FG3A, FG3_PCT, FTM, FTA, FT_PCT, OREB, DREB, REB, AST, STL, BLK, TOV, PF, PTS, PLUS_MINUS, FANTASY_PTS, VIDEO_AVAILABLE`.
Quirks: `GAME_ID` is a zero-padded string (`'0022500002'`); `MIN` is an **integer** (whole minutes, already rounded) in nba_api 1.11.4,
so the "34:12" form must still be parsed defensively but will rarely appear; `MATCHUP` is `'GSW @ LAL'` / `'LAL vs. GSW'` (home flag
from `vs.`); no DNP rows; no `started` flag.

**nba_api `BoxScoreTraditionalV3`.** One call per game. Player frame columns include `personId, firstName, familyName, position,
comment, jerseyNum, minutes` plus the stat columns. `comment` is populated for dressed players who did not play, for example
`"DNP - Coach's Decision"`; `position` is non-empty only for starters (so it gives `started`). Inactive players (the usual injury
"Out" cases) are not in this frame at all. Conclusion: the DNP comment is usable to separate coach's decisions from injuries for
dressed players, but it needs one call per game (~1,230 per season, about 15 minutes per season at 0.6 s), so it is an optional
enrichment for phase 1, not the main absence source.

**nba_api `CommonTeamRoster` (DEN, 2026-27).** 21 rows; columns `TeamID, SEASON, LeagueID, PLAYER, NICKNAME, PLAYER_SLUG, NUM,
POSITION, HEIGHT, WEIGHT, BIRTH_DATE ('DEC 10, 2001'), AGE, EXP, SCHOOL, PLAYER_ID, HOW_ACQUIRED, SUPPLEMENTAL_STATUS`.
Already returns 2026-27 rosters.

**nba_api `CommonAllPlayers` (all seasons).** 5,240 rows, 622 with `ROSTERSTATUS=1`; columns `PERSON_ID, DISPLAY_LAST_COMMA_FIRST,
DISPLAY_FIRST_LAST, ROSTERSTATUS, FROM_YEAR, TO_YEAR, PLAYERCODE, PLAYER_SLUG, TEAM_ID, ..., TEAM_ABBREVIATION, GAMES_PLAYED_FLAG`.
One cheap call; used as the name list for injury matching until `player_aliases` exists.

**nba_api `ScheduleLeagueV2` (2026-27).** 1,274 games including preseason (`0012600009` on 2026-10-03), with `gameId`, `gameDateEst`,
`gameDateTimeEst`, `gameDateTimeUTC`, `homeTeam_teamId/teamTricode`, `awayTeam_teamId/teamTricode`. One call per season (7 s). Used to
map an injury report's (date, matchup) to `game_id`, including future games.

**Official NBA injury report.**
- URL: `https://ak-static.cms.nba.com/referee/injury/Injury-Report_<YYYY-MM-DD>_<slot>.pdf`, times in ET.
  - Until about 2025-12-20 the slot is hourly: `_05PM`. From about 2025-12-25 (confirmed on 2026-01-01 onwards) it is every 15 minutes:
    `_05_00PM`, `_05_15PM`, `_05_30PM`, `_05_45PM`. Missing files return HTTP 403 (not 404).
  - The PDF header carries the true report time, which can differ from the slot name (the hourly `_05PM` file on 2021-12-01 and
    2025-01-15 says `05:30 PM`). The parser uses the header time as `report_time` and falls back to the slot.
  - **Historical archive exists**: reports back to at least 2020-12-23 are still served. So `--backfill-from <date>` is implemented.
  - No reports found for 2026-10-05 to 2026-10-10 (preseason) at the slots probed; the regular season opens Oct 20. Teams must file
    by 5 p.m. local the day before a game and a game-day report between 11 a.m. and 1 p.m. local (8 to 10 a.m. for tips at 5 p.m. or earlier).
- Layout: landscape, columns `Game Date | Game Time | Matchup | Team | Player Name | Current Status | Reason`. Date, time, matchup and
  team appear only on the first row of each group (carry forward, including across pages). Reasons wrap to two lines that sit above and
  below the player row. Names are `Last, First` (`Moore Jr., Wendell`). Teams that have not filed show `NOT YET SUBMITTED`.
  `extract_text()` drops spaces; `extract_words(x_tolerance=1.5)` keeps them, so the parser works on word positions.
- Parser choice: own parser on `pdfplumber` (MIT, pure Python). Alternatives checked on PyPI:
  `nbainjuries` 1.1.1 (needs Java via `jpype1`/`tabula-py` and `pandas<3.0`; this repo pins pandas 3.0.1, so it cannot be installed),
  `nba-injury-report` 0.1.0 (single release Jan 2026, AGPL dependency `pymupdf`),
  `nba-injury-report-pdf-to-df` 0.1.7 (pdfplumber, last release Feb 2025, built for the Jan 2025 layout). The own parser follows the
  same pdfplumber approach but uses header-derived column positions so both layouts parse.
- Fallback if PDF parsing breaks: keep caching the raw PDFs (the irreplaceable part), log a parse failure without failing the pipeline,
  and re-parse the cache later with a fixed parser (`python -m src.injuries --reparse`).

**Odds provider prop markets (documentation only; The Odds API was not called).**
- The provider is The Odds API (`ODDS_API_KEY`). NBA prop market keys include `player_points`, `player_rebounds`, `player_assists`,
  `player_threes`, `player_blocks`, `player_steals`, `player_turnovers`, `player_points_rebounds_assists` and combos, `_q1` variants,
  `_alternate` lines, first basket, double/triple double.
- Props are only available per event through `/v4/sports/{sport}/events/{eventId}/odds` ("one event at a time"), not the bulk odds endpoint.
- Cost: `markets returned x regions` credits per call (so 4 prop markets x 1 region = 4 credits per game per poll; a 10-game night is
  about 40 credits per poll). Empty responses are free. Coverage is mainly US bookmakers.
- Historical props exist from 2023-05-03 but historical endpoints need a paid plan. Whether the free plan includes current props was not
  stated in the docs.

### Step 5
This report, `docs/player-data-checkpoint.md` and the `player-data-work` branch were created; first commit made.
