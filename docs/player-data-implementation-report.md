# Player data: implementation report

Branch `player-data-work` (worktree `C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work`), branched from `main` at `df2b615`.
Spec: `docs/player-data-backend-spec.md`. Resume point: `docs/player-data-checkpoint.md`.

## Phase checklist

| Phase | Name | Status |
|---|---|---|
| 0 | Recon and preconditions | done |
| 1 | Player data foundation | done |
| 2 | Injury snapshot ingestion | done (historical backfill running) |
| 3 | Ratings and minutes projections | done |
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

## Phase 2: injury snapshot ingestion (done, Oct 10, 2026)

### Built
- `migrations/0001_injury_snapshots.sql` (file only, not applied): `injury_snapshots` with `snapshot_id` identity PK,
  unique `(source, report_time, team_id, player_name_raw)` (the writer's conflict target), `game_id` text with a
  10-digit check, RLS on, anon/authenticated revoked. Extra additive columns beyond the spec: `game_time_et`,
  `matchup`, `raw_file`. `team_id` is NOT NULL because NULLs would defeat the unique key; rows whose team cannot be
  resolved go to the unmatched report instead.
- `src/injury_report_pdf.py`: word-position parser (pdfplumber) for both layouts, header time as `report_time`,
  carry-forward across pages, wrapped reasons, `NOT YET SUBMITTED` teams; slot-name helpers for both URL eras.
- `src/injuries.py`: fetch + raw PDF cache (`data/raw/injury_reports/`), parse, team match (nickname suffix, longest
  wins), game match (`ScheduleLeagueV2` per season, LeagueGameLog fallback, cached in `data/raw/nba_api/`), player
  match, local append-only SQLite sink (`data/injuries/injury_snapshots.sqlite`), unmatched CSV
  (`data/injuries/injury_unmatched.csv`), `latest_status(game_id, as_of)`, `push_to_supabase` (dry run unless `--yes`;
  uses `upsert_rows(..., ignore_duplicates=True)`, i.e. ON CONFLICT DO NOTHING). Not run against production.
- `src/player_names.py`: `normalize_name` (lowercase, `Last, First` flip, accents folded incl. ø/ł/đ, punctuation and
  Jr./Sr./II-V removed) and `NameResolver` (exact, compact, same-team last-name + first-initial; ties broken by team,
  then active roster). Today it is built from a cached nba_api `CommonAllPlayers`; phase 1 switches it to `player_aliases`
  via `NameResolver.from_rows`.
- `src/config.py`: status map (GTD, Day-To-Day, Out for season, Not With Team, ...), unknown fallback `questionable`
  (logged to stdout and `injury_events`), `STATUS_TO_P_PLAY`, paths, snapshot mode/lookback.
- `src/nba_client.py`: throttled (0.6 s), retrying (3 tries, 2 s doubling backoff), JSON-cached nba_api calls that keep
  zero-padded IDs as strings.
- `src/database.py`: `upsert_rows` gained an optional `ignore_duplicates` flag (default off, old calls unchanged).
- Scheduling (branch only, nothing registered): `run_pipeline.bat` (morning) and `run_predict.bat` take a snapshot;
  new `scheduler/run_injury_snapshot.bat` + `scheduler/register_injury_snapshot_task.ps1` for a separate
  every-30-minutes 11:00-23:00 job; `scheduler/README_scheduler.md` documents it. The command always exits 0.

### Decisions
- **Snapshot mode "latest".** Each tick archives only the newest published report (probing 15-minute slots newest
  first over the last 3 hours). Archiving every 15-minute report would be about 60 reports and 12,000 rows a day
  (about 2 million rows a season), too much for Supabase; with 30-minute ticks it is about 25 reports a day. Missed slots
  can be fetched later (`--all-slots`, or `--backfill-from` with `--slots`) because nba.com keeps its archive.
- **`latest_status` semantics.** Only rows with `report_time <= as_of` count (`report_time` is the publication time
  from the PDF header, so backfilled rows are point-in-time correct even though `captured_at` is later). Per team, the
  newest report listing that team is current; a player listed earlier but missing from it is treated as removed from
  the report (no row returned, i.e. available). Known gap: if a team drops off the report entirely, its last listing
  stands.
- Naive `as_of` values are read as US Eastern.
- Historical backfill uses one report per day (the 5 PM ET slot, which the old hourly file often fills with the
  5:30 PM version).

### Verified
- Real reports parsed: 2026-04-10 5:00 PM (206 rows, 30 teams, 0 unmatched players, 0 unknown statuses) and
  2021-12-01 5:30 PM (102 rows, 6 not-submitted teams, 2 unmatched two-way players: RJ Nembhard Jr., Daulton Hommes).
  All rows got a zero-padded `game_id`.
- Live snapshot at 16:00 ET on Oct 10, 2026: 13 slots probed, all 403 (no preseason reports published), exit 0. A
  replayed snapshot (`--now 2026-04-10T17:20-04:00`) fetched real archived reports and re-running it inserted nothing.
- `scheduler\run_injury_snapshot.bat` runs from the worktree and logs to `logs\injury_snapshot.log`; the PowerShell
  registration script parses cleanly (not executed).
- Tests: `tests/test_injuries.py` (25 tests: status table, names with suffixes/accents, parser on synthetic words and
  both real layouts, idempotency, unmatched file, `latest_status` leakage and boundaries, CLI never failing, backfill
  resumability, push dry-run, cache round trip). Full suite 316/316 OK, also under `scripts/run_offline_tests.py`.

## Phase 1: player data foundation (done, Oct 10, 2026)

### Built
- `migrations/0002_player_foundation.sql` (file only): `players` (PK `player_id`), `player_aliases`
  (PK `provider, provider_name`), `player_games` (PK `game_id, player_id`, indexes on `(player_id, game_date)` and
  `(team_id, game_date)`, 10-digit text `game_id` check), `player_absences` (PK `game_id, player_id`). RLS on.
- `src/player_store.py`: storage for all new player-data tables. `NBA_PLAYER_STORE=local` (default) writes a SQLite
  mirror at `data/player_data/player_data.sqlite` with the same tables and primary keys; `NBA_PLAYER_STORE=supabase`
  goes through `src/database.py` (`upsert_rows` on the PK, `select_rows`). `push_local_to_supabase(table)` copies
  rows up later (dry run by default; never run here). Booleans are 0/1 locally and converted on push.
- `src/collect_players.py`: `--backfill` (one `LeagueGameLog` player-mode call per regular season from 2019-20 to the
  current season, completed seasons cached in `data/raw/nba_api/`), default incremental mode (from the newest stored
  `game_date`, re-reading that day; rolls over to a new season), `--players` (players + aliases from
  `CommonAllPlayers`). The season list is derived from today's date, so 2026-27 is collected automatically.
- Aliases: provider `nba_api` (display name) and `normalized` (`normalize_name`) for every player; 94 duplicate
  historical names resolve to the most recent player. `NameResolver` now builds from `players` + `player_aliases`
  (+ each player's latest team from `player_games`), falling back to the nba_api list. Manual fixes for unmatched
  injury names go into `player_aliases` with provider `nba_injury_report` or `manual`.
- `src/absences.py`: inferred absences per the spec (typical minutes = average over the games he played among the
  team's previous 10; at least 5 appearances; at least 15 minutes). Trade rule: a player counts for team T only if his
  previous appearance was for T and his next appearance that season, if any, is also for T. Windows never cross
  seasons. `typical_minutes` stored.
- `run_pipeline.bat`: `collect_players` and `absences` run after `collect` and before `elo`/`features`. They are
  non-fatal for now (a failure is logged and does not change the exit code). The batch file now uses a `:step`
  subroutine for the existing steps (same behaviour, verified with a dummy batch file; the real pipeline was not run
  because it writes to production).

### Verified (real data)
- Backfill: 176,738 player-game rows (2019-20: 22,393; 2020-21: 23,054; 2021-22: 26,039; 2022-23: 25,894;
  2023-24: 26,401; 2024-25: 26,306; 2025-26: 26,651; 2026-27: 0 so far).
- Reconciliation against Supabase `games` (read only): 16,578 team-games in both, zero missing either way, identical
  per-season counts. Every game has players on both teams (min 6, median 10 players per team-game; team minutes sum
  median 240). All `game_id` values are 10-character text.
- Second backfill and an incremental run changed nothing (row counts 176,738 / 5,240 players / 10,386 aliases).
- 20,194 inferred absences (about 1.2 per team-game; 2021 is highest, consistent with the COVID protocol season).

### Deviations
- `started` is null: `LeagueGameLog` has no starter flag. `BoxScoreTraditionalV3` has it (non-empty `position`), but
  needs one call per game; deferred with the DNP-comment enrichment (`basis='boxscore_comment'`), which phase 0 showed
  is possible but costs about 1,230 calls per season. All absences are `basis='inferred'` for now.
- `minutes` are whole numbers: nba_api 1.11.4 returns `MIN` as an integer in `LeagueGameLog`.
- `players.position` and `birth_date` are null (would need one `CommonPlayerInfo` call per player).
- Regular season only, matching `games`.

### Tests
`tests/test_player_data.py` (9 tests): minutes parsing (`34:12`, `PT34M12.00S`, ints, blanks), zero-padded ids,
upsert idempotency, alias clash handling and resolver, absence fixture (30-minute player absent, 5-minute bench
player not, traded player not absent for his old team, 5-appearance rule, no carry-over across seasons), rebuild
idempotency. Full offline suite 325/325 OK.

## Phase 3: ratings and minutes projections (done, Oct 10, 2026)

### Built
- `migrations/0003_player_ratings.sql` (file only): `player_ratings` (PK `player_id, as_of, rating_type`; `as_of` is a
  date) and `player_minutes_projection` (PK `game_id, player_id, as_of`; `as_of` timestamptz).
- `src/ratings.py`:
  - `rapm_lite_v1`: one row per game, features = 5 x player minutes / team minutes (+ home, - away), target = margin
    per 100 possessions (possessions = FGA - OREB + TOV + 0.44 FTA, averaged over both teams), trailing 730 days,
    half-life 365 days, ridge toward a prior (last season's final rapm rating, else the player's `box_value_v1`, else 0),
    intercept = home-court advantage.
  - `box_value_v1`: Hollinger Game Score per minute, shrunk toward the league mean with 400 prior minutes, centred,
    x48, then scaled to margin-per-100 units by one weighted regression of game margins on minutes-weighted team sums.
  - Backfill: weekly refits during seasons (183 as_of dates, 2019-12-09 to 2026-04-13; the first refit needs 300 games
    in the window, so games before Dec 9, 2019 have no ratings). Nightly refresh in `run_pipeline.bat` (non-fatal); it
    skips when no game was played since the last refit. `ratings_as_of(day, type)` and `combined_ratings(day)`
    (primary where `minutes_basis` >= 500, else fallback) are the point-in-time readers.
- `src/minutes.py`: `p_play` via `STATUS_TO_P_PLAY`; base minutes = EWMA (half-life 10 games played); minutes-if-playing
  = min(40, s x base) with one scale s per team so the expected total is 240; `exp_min = p_play x minutes-if-playing`;
  p10/p90 from the last 30 games played x s (conditional on playing); roles; inferred roster (players seen in the
  team's last 20 games whose latest appearance was for the team) or an explicit roster. CLI worked example:
  `python src/minutes.py --game <id> --as-of <iso>`.

### Choice of ridge penalty (honest note)
Per-refit time-ordered validation (last 20% of the window) was unstable: it jumped between 10 and 1000 across refits.
A pooled forward validation instead (19 windows, Jan/Mar/Nov 2020-2026; fit on the window before the date, predict the
next 28 days' margins per 100) gave mean squared error: alpha 3: 191.4, **10: 185.2**, 30: 185.9, 100: 189.3,
300: 193.3, 1000: 196.9, 3000: 198.6; the box prior alone: 199.4. So `RATING_RIDGE_ALPHAS = (10.0,)` is fixed in config
(per-refit CV comes back if several values are listed), and RAPM adds real out-of-sample signal over the box prior.

Sanity check (2026-03-01, players with more than 1,500 minutes): rapm top = Gilgeous-Alexander 10.5, Jokić 10.0,
Antetokounmpo 8.4, Wembanyama 8.1, Leonard 8.0; box top = Jokić 13.4, Gilgeous-Alexander 12.6, Antetokounmpo 11.8.
Correlation between the two types about 0.8; standard deviation about 3 points per 100 for both.

### Worked example: DEN at ORL, 2021-12-01 (game `0022100320`), as_of 18:00 ET (tip 19:00 minus 60 minutes)
Archived injury report of 17:30 ET: DEN Murray and Porter Jr. out (long-term, so not in the inferred rotation),
JaMychal Green questionable; ORL Suggs, Fultz, Isaac, Carter-Williams, Moore out.

| Team | Player | Status | p_play | Rating | Source | Base min | Exp min | p10-p90 | Role | Actual |
|---|---|---|---|---|---|---|---|---|---|---|
| DEN | Will Barton | - | 1.0 | -2.3 | rapm | 33.1 | 37.5 | 31.7-42.2 | starter | 32 |
| DEN | Nikola Jokić | - | 1.0 | 6.4 | rapm | 32.5 | 36.9 | 29.4-41.0 | starter | 36 |
| DEN | Aaron Gordon | - | 1.0 | 3.1 | rapm | 31.1 | 35.2 | 27.0-41.0 | starter | 38 |
| DEN | Monte Morris | - | 1.0 | -0.1 | rapm | 27.9 | 31.7 | 21.4-36.5 | starter | 34 |
| DEN | Jeff Green | - | 1.0 | -2.3 | rapm | 26.1 | 29.6 | 19.2-38.6 | starter | 29 |
| DEN | Facundo Campazzo | - | 1.0 | -1.2 | rapm | 21.5 | 24.4 | 10.1-38.8 | rotation | 27 |
| DEN | JaMychal Green | questionable | 0.5 | 0.3 | rapm | 16.9 | 9.6 | 12.4-26.3 | rotation | 12 |
| ORL | Cole Anthony | - | 1.0 | -3.2 | rapm | 32.0 | 28.4 | 20.3-32.0 | starter | 37 |
| ORL | Franz Wagner | - | 1.0 | -1.6 | rapm | 31.4 | 27.8 | 24.0-31.0 | starter | 33 |
| ORL | Wendell Carter Jr. | - | 1.0 | 2.3 | rapm | 28.1 | 24.9 | 16.7-30.1 | starter | 33 |
| ORL | Mo Bamba | - | 1.0 | -2.3 | rapm | 27.2 | 24.0 | 18.5-30.2 | starter | 27 |
| ORL | Gary Harris | - | 1.0 | -1.9 | rapm | 25.4 | 22.5 | 13.2-28.5 | starter | 35 |

Observation: base minutes average only games played, so deep-bench players who play garbage time carry inflated
bases and the team scale drops below 1 (ORL here), under-projecting the starters. A later version could weight
DNPs as zero; v1 follows the spec.

### Tests
`tests/test_ratings_minutes.py` (8): ridge recovers synthetic effects (correlation > 0.98, mean abs error < 0.6,
home advantage about 2), large penalty returns the prior, ratings unchanged when games on/after as_of are tampered
with, box value ordering, redistribution conserves 240 and respects the cap, cap binding, status map, out player gets
0 expected minutes and a future game does not change a projection.
