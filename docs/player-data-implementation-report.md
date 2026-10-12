# Player data: implementation report

Branch `player-data-work` (worktree `C:\Users\noel9\Desktop\nba-predictor.worktrees\player-data-work`), branched from `main` at `df2b615`.
Spec: `docs/player-data-backend-spec.md`. Resume point: `docs/player-data-checkpoint.md`.

## Phase checklist

| Phase | Name | Status |
|---|---|---|
| 0 | Recon and preconditions | done |
| 1 | Player data foundation | done |
| 2 | Injury snapshot ingestion | done (historical archive backfilled 2019-10-22 to 2026-06-30) |
| 3 | Ratings and minutes projections | done |
| 4 | Availability features and rest days | done |
| 5 | Candidate model and walk-forward evaluation | done |
| 6 | Predict-time integration | done (code + dry-run tests; candidate artifact not yet saved) |
| 7 | API, contract, sample data | done |
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

## Phase 4: availability features and rest days (done, Oct 10, 2026)

### Built
- `migrations/0004_team_availability_features.sql` (file only). **Deviation:** the primary key is
  `(game_id, team_id, as_of, rating_type)`; `rating_type` was added so the rapm and box variants can be stored and
  evaluated side by side. Extra column `basis` (`realized` / `report`) as the spec asks.
- `src/availability_features.py`: `team_features(roster)` (one function for live and history), `rest_features`,
  `RatingLookup` (point-in-time ratings by day; the rapm variant falls back to box below 500 minutes; unrated players
  get -1.0), `historical_rows`/`backfill()` (realized availability, as_of = tip minus 60 minutes from the schedule's
  UTC tip time, else 7 PM ET), `build(game_id, as_of, ...)` for live use with injury-report probabilities, and
  `model_matrix(rating_type)` producing `home_*`, `away_*`, `*_diff` columns, joined in code (the `features` table is
  not modified). Runs nightly in `run_pipeline.bat` (non-fatal).
- Definitions chosen where the spec left room: "top" players (star_out, top3, key-uncertain) must have at least 15
  base minutes; `top3_avail` is the mean; `minutes_lost` is healthy minus expected minutes over the top 8 by healthy
  minutes; impact = rating x healthy minutes; `rest_days` = days since the previous game this season (1 = back-to-back),
  capped at 7, and the season opener gets the cap. (The production `features.rest_diff` is uncapped and crosses
  seasons; the new columns do not replace it.)
- `src/absences.py` now keeps an absence spell flagged until the player plays again (typical minutes from the
  spell's start). Without this, a star out for 15 games stopped being "absent" after about 6 games because the
  10-game window emptied, and the realized features called him available. Absences: 33,620 (was 20,194).
- `src/collect_players.py`: neutral-site games (NBA Cup knockout games, Paris/Mexico City) list both teams with '@',
  so the home team now comes from the schedule (112 player rows over 10 games fixed). Every game has exactly one home team.

### Verified
- 33,156 rows = 16,578 team-games x 2 rating types (reconciles with `games`). 8,289 games in the wide matrix.
- 342 early 2019-20 games (before the first rating refit on 2019-12-09) have null rating features; rest features exist.
- Realized `star_out` rate about 32% of team-games (a top-2 player by rating missing); back-to-back rate 16%.
  `n_key_uncertain` is always 0 in history (realized p_play is 0 or 1): it only carries information live.
- Leakage tests pass (see Tests).

### Tests
`tests/test_availability.py` (9): hand-computed six-player example (value_out 1.0, top3_avail 2/3, minutes_lost 40),
three-player redistribution with known ratings, star_out boundary (0.5 is not out, 0.49 is), low-minute players are
never stars, rest days for opener, back-to-back and All-Star break, and two leakage guards: features for a game are
identical when every later game's minutes, absences and ratings are tampered with, and when the game's own box score
changes.

## Phase 5: candidate model and walk-forward evaluation (IN PROGRESS)

One command: `venv\Scripts\python.exe scripts\evaluate_availability.py` (first run needs
`NBA_DOTENV_PATH=C:\Users\noel9\Desktop\nba-predictor\.env` to read the production `features` table once, read only;
it is then cached in `data/eval/features_snapshot.json`). Flags: `--no-archive`, `--no-gb`, `--write-candidates`
(writes `data/model_leaderboard_candidates.csv` + a `candidates` entry in `data/model_metadata.json`),
`--save-candidates` (saves `data/candidates/lr-calibrated-availability-v1.pkl` and `...-rest-v1.pkl` for predict-time
shadow use).

Sanity check: the baseline calibrated logistic reproduces the production leaderboard row exactly
(68.11% accuracy, log loss 0.6325, Brier 0.2091, AUC 0.7293 on the 1,596 test games).

### Preliminary results (realized availability, i.e. hindsight; NOT the live expectation)
Run of Oct 10 with `--no-archive --no-gb`. Availability inputs here come from who actually played, so they overstate
what injury reports will deliver live. The live-like run below is the honest number.

Leaderboard split (train 6,348, test 1,596 from 2025-02-25; 931 test games had a top-2 player out):

| Feature set | Subset | Accuracy | Log loss | Brier | AUC | ECE |
|---|---|---|---|---|---|---|
| baseline | all | 0.6811 | 0.6325 | 0.2091 | 0.7293 | 0.0310 |
| baseline+rest | all | 0.6786 | 0.6046 | 0.2082 | 0.7292 | 0.0273 |
| baseline+avail_rapm | all | 0.6886 | 0.5834 | 0.1998 | 0.7534 | 0.0157 |
| baseline+avail_box | all | 0.6779 | 0.5878 | 0.2024 | 0.7433 | 0.0281 |
| all_rapm | all | 0.6892 | 0.5834 | 0.2000 | 0.7529 | 0.0165 |
| baseline | star_out | 0.6821 | 0.6459 | 0.2064 | 0.7417 | 0.0267 |
| baseline+avail_rapm | star_out | 0.6928 | 0.5776 | 0.1978 | 0.7615 | 0.0184 |

Walk-forward by season, pooled 2021-22 to 2025-26 (6,140 games): Brier baseline 0.2184, +rest 0.2177,
+avail_rapm 0.2119, +avail_box 0.2134, all 0.2117; log loss 0.6307 / 0.6258 / 0.6119 / 0.6144 / 0.6109. Every season
improves with availability (largest 2025-26: 0.2111 to 0.2023). rapm beats box in 4 of 5 seasons.

Preliminary promotion check (all_rapm vs production GB: Brier +0.0094, log loss +0.0242; vs same-family baseline:
Brier +0.0091, log loss +0.0491) passes the rule ON REALIZED FEATURES ONLY. No recommendation is made until the
live-like (archived report) evaluation is in; nothing has been promoted.

### Pending
- Live-like evaluation on archived injury reports (the archive now covers every regular-season day from 2019-10-22;
  first `--reparse` and `--rematch` must finish so 2019-20 reports and late-2020 games are matched).
- Gradient-boosting second family, candidate CSV/metadata, saved candidate artifacts.

## Phase 6: predict-time integration (code done; Oct 10, 2026)
- `src/betting.py` (market-agnostic `implied_prob`, `edge`, `kelly_fraction`, `stake(..., exposure_left=None)`; worked
  example 1,111.67 / 0.61 / -105 -> 55.58 unchanged). `track.kelly_bet` and `predict.implied_prob` use it.
- `src/scenarios.py` (uncertain players, 2^k enumeration, blend, range, gate default off, status-change compare),
  `src/factors.py` (logistic contributions reconciled to base rate + other row; availability split per player),
  `src/availability_predict.py` (per-game projections + features + candidate shadow prediction, stored locally in
  `prediction_scenarios`, `prediction_factors`, `prediction_availability_inputs`; `--flag-status-changes`).
- `src/predict.py`: availability step per game inside try/except; production picks change only when
  `NBA_PRODUCTION_MODEL` names the candidate (then blended prob, prob range, gate). `track.save_prediction(extra=None)`
  keeps the original row unless extra is given. `run_pipeline.bat` runs the status-change flag (non-fatal).
- `migrations/0005_predict_availability.sql`: `prediction_scenarios`, `prediction_factors`,
  `prediction_availability_inputs`, predictions `prob_range_low/high`, `status_changed_after_pred`, skip_reason
  `availability_uncertain`.
- Tests: `tests/test_betting.py`, `tests/test_scenarios.py`, `tests/test_factors.py`,
  `tests/test_predict_availability.py` (dry run of `predict.run()` on a recorded slate: shadow mode leaves production
  unchanged; candidate-as-production uses the blend and range; gate; status-change flag).

## Phase 7: API, contract and sample data (IN PROGRESS)
- Done: `tests/contract_shapes.py` first (all additions `Maybe`), `src/api_availability.py`, `app.py` routes:
  `GET /api/injuries?date=`, `/api/game/<id>` adds `availability`, `rest`, `scenarios`, `prob_range`, `factors`;
  `/api/slate` games add `availability_summary` (null when no data); `/api/performance` adds `splits.star_out` (v2
  only); `/api/model` adds `feature_set_version`, `candidates`, `availability_gate`. New reads never flag
  `migration_pending` on existing routes (only `/api/injuries` does). Query budgets updated: slate 5->8, game 7->11,
  performance 3->4 (constant in slate size). `migrations/0006_model_runs_candidates.sql`; `model.publish_model_run`
  retries without the optional columns if 0006 is not applied. Tests: `tests/test_api_availability.py` (12).
- Pending: sample JSON with plausible availability data (`scripts/build_sample_data.py` is deterministic: rerunning it
  today only adds the new null/empty fields; still need to add sample injury/scenario/factor rows and an
  `injuries-2026-11-17.json` file plus its `shape_for` entry in `tests/test_sample_data.py`).

## Migrations to apply, in order (none applied by the agent)
1. `migrations/0001_injury_snapshots.sql` - injury report snapshots (append-only).
2. `migrations/0002_player_foundation.sql` - players, player_aliases, player_games, player_absences.
3. `migrations/0003_player_ratings.sql` - player_ratings, player_minutes_projection (with min_if_play).
4. `migrations/0004_team_availability_features.sql` - team availability features and rest.
5. `migrations/0005_predict_availability.sql` - scenarios, factors, availability inputs, predictions columns.
6. `migrations/0006_model_runs_candidates.sql` - model_runs candidates + feature_set_version.
7. `migrations/0007_market_odds.sql` - generic captured market odds; retain `book_odds` during dual-write.
8. `migrations/0008_player_rates.sql` - point-in-time shrunk per-minute player rates.
9. `migrations/reserved/0009_prop_predictions.sql` - **reserved; do not apply**.

## Phase 8: props groundwork (done)

Added the generic market-odds sink (`src/market_odds.py`) and a best-effort
moneyline dual-write hook in `src/odds.py`; the existing odds dictionary and
`book_odds` path remain unchanged. Added `src/player_rates.py`, which computes
365-day, strictly point-in-time rates for pts/reb/ast/fg3m/stl/blk/tov with a
400-minute league-prior shrinkage. Added the reserved prop schema and a
`src/props/README.md` describing the planned minutes/rates/distribution/staking
flow, The Odds API markets and quota considerations, and open issues.

Focused offline tests cover strict point-in-time rate filtering, empty inputs,
and deterministic market-odds normalization. The sample-data suite and Python
compile checks also pass. No migration was applied and no live data was written.

## Phase 9: final verification and handoff (done)

The live-like archived-report evaluation completed for all 1,596 leaderboard
games. The availability candidate improves Brier score from 0.2091 to 0.1989
and log loss from 0.6325 to 0.5815 against the production baseline on report
features; `all_rapm` reaches 0.1984 Brier and 0.5803 log loss. These are
candidate results only: the production model remains
`gradient-boosting-gridsearch`, and no automatic promotion was performed.

Final verification completed on the dedicated worktree:

```text
python -m unittest discover -s tests -q
Ran 380 tests ... OK
python -m unittest tests.test_sample_data tests.test_odds -v
Ran 37 tests ... OK
```

The sample generator was rerun and the generated fixtures are committed. The
player-data work remains isolated to `player-data-work`; migrations are files
only and still require Noel's review/application process.
