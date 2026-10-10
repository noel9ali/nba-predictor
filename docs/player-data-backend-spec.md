# Player-level data: backend implementation spec (props-ready)

Status: drafted Oct 7, 2026. Audience: the Implementation Agent. Read `claude/agent-memory/noel-workflow.md`, `claude/integration-findings.md` and `claude/design-state-and-backend-requirements.md` first; this spec builds on them and does not repeat them.

## 0. Goal and non-goals

**Goal.** Add player-level data to the pipeline so the game model knows who is playing, and so the same data layer can later power player prop predictions without schema rewrites.

**In scope now.**
- Player box-score ingestion and history.
- Injury/availability snapshots.
- Player ratings and minutes projections.
- Availability-adjusted team features.
- A candidate game model trained on them, with a walk-forward comparison.
- Availability-aware predict-time logic and explanations.
- API and contract updates.
- Props groundwork: shared tables, a market-agnostic betting module, and reserved (unapplied) prop schema.

**Out of scope now.**
- Any prop predictions, prop UI or prop bets.
- Frontend implementation (only API shapes and sample JSON, so the frontend can build against them).
- Pushing, merging to main, or writing to the live Supabase project.

**Honest expectation.** Betting markets already price injuries. Expect better calibration and fewer blowups on star-out nights, not a large jump in raw accuracy. Success is judged on Brier score, log loss and edge quality, not accuracy alone.

## 1. Rules (apply to every phase)

- **Safety.** No writes to the live Supabase project. No applying migrations: write them as files in `migrations/` with sequential names and let Noel apply them. Read-only inspection of Supabase is fine. Never print `.env`. No push, no merge to main.
- **Idempotent.** Every migration, collector and backfill is safe to re-run.
- **IDs.** `game_id` is TEXT, zero-padded exactly as nba_api returns it (for example `0022500001`). `player_id` and `team_id` are bigint. Do not repeat the bigint-GAME_ID mistake from the integration findings.
- **Primary keys.** Every new table has a real primary key or unique constraint that matches the upsert conflict target. (The `games` table's PK bug is the cautionary tale.)
- **Point in time.** Anything used as a model input carries an `as_of` timestamp, and feature builders may only read rows with `as_of` strictly before the prediction's tip time. This is tested (see section 9).
- **Vercel stays light.** The Flask/Vercel API reads precomputed tables only. numpy, scipy, scikit-learn and torch belong in the pipeline requirements, never in the API requirements.
- **Keep old routes working.** Additive API changes only.
- **Config over constants.** Thresholds, status-to-probability maps and Kelly settings live in one importable `src/config.py` section, not scattered literals.
- **Speed.** Use `timeout` on long commands, throttle nba_api calls (at least 0.6s apart, with retry and backoff), and run the full suite only at phase ends.
- **Progress.** After each phase, tick it off in `docs/player-data-implementation-report.md` (created in phase 0) with what was done, what was verified, and anything deviating from this spec. Also follow the progress-safety process in section 1b at all times.

## 1b. Progress safety (protects against session token or context limits)

This is a long build. Assume any session can end abruptly, so progress must always live on disk and in git, never only in the conversation. These rules apply from the first action.

1. **Checkpoint file.** Maintain `docs/player-data-checkpoint.md` as the single resume point. Create it in phase 0 and rewrite it (not append) after every completed step. It must contain: current phase and step, a checklist of every phase and step with status (`todo`, `in progress`, `done`, `blocked`), the exact next action, files created or changed since the last commit, commands to re-run verification, decisions made and why, open problems, and the commit hash of the last good state. A fresh agent reading only this file plus this spec must be able to continue with no other context.
2. **Commit early and often.** Commit on a dedicated branch (for example `player-data-work`, branched from the canonical backend branch; never main) at the end of every step, and always before any long-running command. Small commits with clear messages, each including the checkpoint file. No push and no merge, per the rules. If a step is half done when you must stop, commit it as `WIP: <step>` and say so in the checkpoint.
3. **Small steps.** Break each phase into steps that finish in well under a quarter of the budget, such as one table plus its collector plus its tests. Finish and commit a step before starting the next. Do not hold large uncommitted changes across steps.
4. **Resumable by design.** Backfills and long jobs must write progress as they go (per season, per batch), skip work already done on re-run, and log what they completed. Cache raw API responses to `data/raw/` (git-ignored) so a retry after a crash does not re-hit nba_api.
5. **Budget watch.** Keep a rough count of how much of the session's token or context budget remains. When roughly 70% is used, stop starting new steps: finish the current step, commit, and update the checkpoint. When roughly 85% is used, only commit and write the handoff (item 6), nothing else.
6. **Handoff note.** Before ending a session for any reason, including an error, write a "Resume here" section at the top of the checkpoint: what is done and verified, what is half done and where its code lives, the first command to run next, and any traps found (rate limits hit, parser quirks, failing tests with their cause).
7. **Keep it out of the conversation.** Do not rely on remembering earlier tool output. Write findings from the phase 0 probes, evaluation tables and chosen config values into the report or checkpoint when you get them, so they survive.
8. **Verify on resume.** On starting or resuming, read the checkpoint, run `git status` and `git log -5`, run the fast tests for completed steps, and reconcile any difference between the checkpoint and reality before doing new work. If the checkpoint and the repo disagree, trust the repo and fix the checkpoint.
9. **Mirror to the Claude project.** At the end of each phase, copy the checkpoint's current status to the project doc `claude/player-data-checkpoint.md` (if the Projects tool is available), so progress is visible and recoverable even if the working directory is lost. Overwrite the same path each time.

## 2. Phase order and dependencies

| Phase | Name | Depends on |
|---|---|---|
| 0 | Recon and preconditions | none |
| 1 | Player data foundation | 0 |
| 2 | Injury snapshot ingestion | 0 (can run alongside 1) |
| 3 | Ratings and minutes projections | 1 |
| 4 | Availability features and rest days | 1, 2, 3 |
| 5 | Candidate model and walk-forward evaluation | 4 |
| 6 | Predict-time integration | 2, 4, 5 |
| 7 | API, contract, sample data | 6 |
| 8 | Props groundwork | 1, 3 (finish after 6) |
| 9 | Report and handoff | all |

**Time-sensitive: start phase 2 first.** The NBA season starts in late October and historical injury statuses may not be recoverable. Every day of archived snapshots is training and evaluation data that cannot be recreated. Get the snapshot collector working and scheduled before anything else is polished.

## 3. Phase 0: recon and preconditions

1. Identify the canonical backend branch/worktree (the integration findings leave this open: `model_metadata.json` exists only in `nba-model-integration-lstm-gb-rf`). Record the choice in the report. Do not merge anything.
2. Confirm the state of the integration blockers, because phases 1 and 4 depend on them: `games` primary key (should be GAME_ID + TEAM_ID), `collect.py` upsert conflict target, missing `bankroll` and `workflow_log` tables, TEXT-typed numeric columns in `features` and `predictions`. If they are unresolved, either do the minimal fix as a migration file plus code change in this branch, or list them in the report as a blocker and build the new work to not depend on them. Prefer the first.
3. Read `src/database.py` and match its select/insert/upsert/update/filter conventions. New code must go through it, so SQLite-vs-Supabase is not re-litigated.
4. Probe each external source with one real call and record shape, field names and quirks in the report:
   - nba_api `LeagueGameLog` with `player_or_team_abbreviation='P'`. It returns one row per player per game for players who played (no DNP rows).
   - nba_api box score endpoints (for example `BoxScoreTraditionalV3`) and whether they expose a DNP comment/reason.
   - nba_api roster endpoints (`CommonTeamRoster`, `CommonAllPlayers`).
   - The official NBA injury report. It is published as hourly PDFs on the NBA site. Verify the current URL pattern and cadence, and whether a maintained Python parser exists before writing your own. If scraping the PDF is unreliable, document the fallback.
   - Whether the existing odds provider offers player-prop endpoints and what plan/quota they need (informational only, for phase 8).
5. Create `docs/player-data-implementation-report.md` with the phase checklist, and create `docs/player-data-checkpoint.md` and the `player-data-work` branch per section 1b. Make the first commit now.

**Done when:** the report names the branch, the blocker status and the probe results, and nothing else has changed except migration/code fixes you chose to include.

## 4. Phase 1: player data foundation

**Tables** (migration `NNNN_player_foundation.sql`):

- `players`: `player_id` PK, `full_name`, `first_name`, `last_name`, `position` (nullable), `birth_date` (nullable), `is_active`, `updated_at`.
- `player_aliases`: `provider` text, `provider_name` text, `player_id`; PK (`provider`, `provider_name`). Odds and injury feeds identify players by name, so this table is the join key for both the injury report now and prop odds later. Seed it with `nba_api` full names and a normalizer (lowercase, strip punctuation and suffixes like Jr./III, fold accents).
- `player_games`: PK (`game_id`, `player_id`). Columns: `team_id`, `game_date`, `season`, `is_home`, `started` (nullable), `minutes` (numeric), `pts`, `reb`, `oreb`, `dreb`, `ast`, `stl`, `blk`, `tov`, `pf`, `fgm`, `fga`, `fg3m`, `fg3a`, `ftm`, `fta`, `plus_minus`. Index on (`player_id`, `game_date`) and (`team_id`, `game_date`).
- `player_absences` (derived): PK (`game_id`, `player_id`). Columns: `team_id`, `game_date`, `basis` (`inferred` / `boxscore_comment` / `report`), `reason` (nullable), `typical_minutes` (the player's trailing average, for filtering to meaningful absences).

**Code:**

- `src/collect_players.py`: backfill seasons 2019-20 through the latest, then incremental daily collection (new games since the max `game_date`). The backfill is about one `LeagueGameLog` call per season, which is cheap. Parse `MIN` ("34:12" or numeric) to decimal minutes. Upsert on the PK.
- `src/absences.py`: derive `player_absences` using only game-log data. A player counts as absent from a team game if he averaged at least `ABSENCE_MIN_TYPICAL_MINUTES` (config default 15) over his team's previous 10 games, appeared in at least 5 of them, and has no `player_games` row for this game. Flag `basis='inferred'`. If phase 0 found a usable DNP comment, enrich `reason` and use `basis='boxscore_comment'`. Handle trades (use team at the time) and season boundaries (do not carry absences across seasons).
- Wire both into the morning pipeline in `daily_workflow.py --morning`, after `collect`, before features.

**Tests:** minutes parsing; upsert idempotency (run twice, same row count); absence inference on a hand-built fixture (player with 30 min average vanishes for one game, a bench player at 5 min does not trigger, a traded player is not marked absent for his old team); zero-padded game IDs preserved.

**Done when:** backfill produces rows for every season with counts that reconcile against `games` (each game has players on both teams), the second run changes nothing, and tests pass.

## 5. Phase 2: injury snapshot ingestion

**Tables** (migration `NNNN_injury_snapshots.sql`):

- `injury_snapshots`: `snapshot_id` PK, `captured_at` timestamptz (when we fetched), `report_time` timestamptz (the report's own timestamp), `game_id` (nullable until matched), `game_date`, `team_id`, `player_id` (nullable until matched), `player_name_raw`, `status_raw`, `status` (normalized: `out`, `doubtful`, `questionable`, `probable`, `available`), `reason`, `source`. Unique on (`source`, `report_time`, `team_id`, `player_name_raw`).
- Append-only. Never update or delete snapshots: the history of changes is the point.

**Code:**

- `src/injuries.py`: fetch the latest report, normalize statuses, match names via `player_aliases` (log unmatched names to a `injury_unmatched` report file rather than dropping silently), match to `game_id` via team and date, upsert.
- Idempotent per `report_time`: re-fetching an unchanged report inserts nothing.
- A CLI: `python -m src.injuries --snapshot` for the scheduler and `--backfill-from <date>` if phase 0 found a historical archive.
- Scheduling: call a snapshot on every predict-mode scheduler tick (the existing every-30-minutes, 11:00 to 22:00 job in the requirements doc) and once in the morning run. Update `task_scheduler_setup.ps1` and the scheduler README accordingly. A failed snapshot must not fail the pipeline: log it and continue.
- `GET`-side view or helper `latest_status(game_id, as_of)`, returning the newest snapshot row per player at or before `as_of`.

**Tests:** status normalization table (including odd strings like "GTD", "Day-To-Day", "Out for season" mapped sensibly and logged); name matching with suffixes and accents; idempotent re-fetch; `latest_status` honoring `as_of` (a later snapshot must not leak into an earlier `as_of`).

**Done when:** a live snapshot (or a recorded fixture if the season has not started) lands rows, the scheduler job is updated, and unmatched-name reporting works.

## 6. Phase 3: ratings and minutes projections

These two outputs are the shared core of both the game model now and props later. Build them cleanly and generically.

**Tables** (migration `NNNN_player_ratings.sql`):

- `player_ratings`: PK (`player_id`, `as_of`, `rating_type`). Columns: `value` (points per 100 possessions relative to average), `minutes_basis` (sample size), `se` (nullable), `version`. One row per player per `as_of` date, written nightly.
- `player_minutes_projection`: PK (`game_id`, `player_id`, `as_of`). Columns: `team_id`, `p_play` (0 to 1), `exp_min` (expected minutes), `min_p10`, `min_p90`, `role` (`starter` / `rotation` / `bench` / `inactive`), `basis` (text describing the method), `version`.

**Ratings (two pluggable types, evaluated against each other in phase 5):**

1. `rapm_lite_v1`: ridge regression on game-level data. One row per game; features are each player's share of the game's minutes (+ for home-team players, − for away-team players); target is final margin per 100 possessions (estimate possessions from team box-score data). Use a trailing window (default 2 seasons of games, exponentially down-weighted with a half-life in config), with last season's rating as a shrinkage prior at season start. Fit with scikit-learn's `Ridge`, with the penalty chosen by time-ordered cross-validation. This is the main candidate and is entirely buildable from `player_games`.
2. `box_value_v1`: a cold-start fallback from per-minute box-score production (a transparent composite such as scaled points, rebounds, assists, steals, blocks, turnovers and shooting efficiency per minute), shrunk toward the league mean by minutes played (empirical-Bayes style). Used where `rapm_lite_v1` has too few minutes, and as a baseline.

Write a point-in-time rating series: `as_of` is the date the rating was computed, using games strictly before that date. Backfill historically with a rolling or weekly refit (not a fit-per-day, which is too slow), then refresh nightly.

**Minutes projection (v1, deliberately simple):**

- `p_play` comes from the latest injury status through `STATUS_TO_P_PLAY` in config (defaults: out 0.0, doubtful 0.05, questionable 0.5, probable 0.9, available or no report 1.0). If the injury archive later has enough history, add `fit_status_p_play.py` to estimate these from outcomes (inferred absences) and write the fitted values to config. Report both.
- `exp_min` for a healthy player is an exponentially weighted average of minutes in games he played (half-life in config), then redistributed: when teammates have `p_play < 1`, spread their expected minutes across the remaining rotation proportionally to current minutes, with a per-player cap (default 40) and a team total of 240.
- `min_p10` / `min_p90` from the player's historical minutes spread when playing (empirical quantiles of the trailing window, shifted by the redistribution).
- Store one row per rostered player per upcoming game each time predictions run.

Design for props: keep these as functions of (`player_id`, `game_id`, `as_of`) with no dependence on the game-level model. Props will consume `exp_min`, the minute distribution and per-minute rates directly.

**Tests:** ridge recovers known synthetic player effects within tolerance; ratings for a date use no games on or after that date; minutes redistribution conserves the team total and respects the cap; `p_play` map applied correctly; a player with `out` status gets `exp_min = 0`.

**Done when:** historical ratings exist for the full backfill range, the nightly refresh runs, and a worked example (one real game, with the top rotation players, their ratings and projected minutes) is written into the report.

## 7. Phase 4: availability features and rest days

**Table** (migration `NNNN_team_availability_features.sql`): `team_availability_features`, PK (`game_id`, `team_id`, `as_of`). Columns:

- `rating_baseline`: minutes-weighted rating of the team's full healthy rotation.
- `rating_expected`: the same, using projected minutes (`exp_min / 240 × rating`, summed).
- `value_out`: baseline minus expected (the rating points lost to absences).
- `star_out`: 1 if any of the team's top 2 players by rating has `p_play < 0.5`.
- `top3_avail`: product or mean of `p_play` across the top 3 by rating.
- `minutes_lost`: total projected minutes missing from the usual top-8 rotation.
- `n_key_uncertain`: number of top-5-by-impact players with `p_play` strictly between 0.1 and 0.9.
- `rest_days`, `is_b2b`, `games_last_7`.
- `feature_version`.

**Builder:** `src/availability_features.py` with `build(game_id, as_of)` for live use and `backfill()` for history. For history, `p_play` comes from realized absences (a player with an inferred absence gets 0, everyone else 1) because historical statuses will not exist except from the new archive. Mark each row's `basis` (`realized` or `report`) so evaluation can separate them. `as_of` for history is the game's tip time minus 60 minutes, for consistency with live use.

Rest days and back-to-back flags are also required by the game drawer; compute them once here from `games` and expose them to both consumers.

Join into the model matrix as `home_*`, `away_*` and `*_diff` columns. Do not modify the existing `features` table. Join in code, so the TEXT-column cleanup in the integration work is not a blocker.

**Tests:** the leakage guard (see section 9); a hand-computed example with three players and known ratings; `star_out` toggles correctly at the 0.5 boundary; `rest_days` handles season opener, All-Star break and back-to-backs.

**Done when:** features exist for every historical game in the training range, row counts reconcile, and the leakage test passes.

## 8. Phase 5: candidate model and walk-forward evaluation

1. **Do not touch the production model.** Add the new model as a candidate with a distinct `model_name` (for example `lr-calibrated-availability-v1`), alongside `legacy-calibrated-logistic`.
2. **Features:** the existing set (Elo and rolling stats) plus the phase 4 diffs. Keep the same calibrated-logistic family first, so any gain is attributable to the features and not the algorithm. Optionally try gradient boosting as a second candidate after.
3. **Evaluation:** `scripts/evaluate_availability.py`. Walk-forward by season (train on earlier seasons, test on the next), plus the existing 1,596-game test set for direct comparison with the leaderboard (68.2% accuracy, 0.2089 Brier, 0.729 AUC, 55.0% home base rate). Report accuracy, Brier, log loss, AUC and a calibration table for: baseline, baseline plus rest days only, baseline plus availability (`rapm_lite_v1`), baseline plus availability (`box_value_v1`), and all. Also report the same metrics on the subset of games where a top-2 player was out (the place we expect the gain), and on live-like games using archived snapshots once at least 30 nights exist.
4. **Leakage and distribution shift.** Training on realized absences and predicting with report probabilities is a known mismatch. State it in the report, evaluate on the archived subset when possible, and never present realized-absence results as the live expectation.
5. **Promotion rule.** Promote the candidate to production only if, on the leaderboard test set, Brier improves by at least 0.001 and log loss is no worse, and the calibration table shows no new bias. Otherwise keep production unchanged and ship the data and features anyway. Never promote automatically: write the proposal and results to the report and `data/model_leaderboard.csv`, and let Noel decide.
6. **Registry.** Update `data/model_metadata.json` and the leaderboard with the new candidate, its feature-set version and training date. `predictions.model_name` already records which model made each pick.

**Done when:** the evaluation table, the star-out subset results and the promotion recommendation are in the report and leaderboard, reproducible with one command.

## 9. Phase 6: predict-time integration

1. **Order of operations in `--predict` mode:** take an injury snapshot, compute `player_minutes_projection` and `team_availability_features` for tonight's games with the new `as_of`, then predict.
2. **Scenario blending.** For each team, take up to `MAX_SCENARIO_PLAYERS` (default 3) players with `0.1 < p_play < 0.9` and the largest impact (`rating × exp_min`). Enumerate the up-to-2^k present/absent combinations, compute the features and win probability for each, and blend with weights from the product of `p_play`s. Store the blended probability as `home_win_prob`. Store each scenario in `prediction_scenarios` (migration: PK (`game_id`, `model_name`, `scenario_key`), columns `weight`, `home_win_prob`). Add `prob_range_low` and `prob_range_high` to `predictions` (migration, additive and nullable).
3. **Uncertainty gate (behind `AVAILABILITY_GATE`, default off).** If `prob_range_high − prob_range_low` exceeds `UNCERTAINTY_RANGE` (default 0.06), either halve the Kelly fraction or skip the bet. Config chooses which, with skip logged as `skip_reason = 'availability_uncertain'` (extend the allowed values). Ship it off, and report what turning it on would have done on archived data.
4. **Status-change flag.** On each later predict tick or morning settle run, compare the latest status of the key players with the snapshot used at prediction time; set `predictions.status_changed_after_pred` (boolean, additive) when any key player (top 5 by impact) changed. Informational only: no re-betting in this version.
5. **Betting module.** Move edge and sizing into `src/betting.py`, market-agnostic: `implied_prob(american)`, `edge(prob, price)`, `kelly_fraction(prob, price)` and `stake(bankroll, prob, price, fraction=KELLY_FRACTION, cap=KELLY_CAP, exposure_left=None)`. Keep the current rule (bet only if edge is above 0, quarter Kelly, 5% cap) and the worked-example test: bankroll 1,111.67, probability 0.61, price −105 gives 55.58. Update `predict.py` and `track.py` to import from it. The `exposure_left` parameter is a hook for props (same-game correlation and a per-game exposure cap), unused for now.
6. **Factor contributions (drawer option B).** Populate `prediction_factors` (migration: PK (`game_id`, `model_name`, `factor_key`); columns `label`, `group` (`base` / `form` / `availability` / `rest`), `prob_points`, `sort_order`). For the logistic model, each factor's contribution is its coefficient times its standardized deviation from the league average, in logit space, converted to probability points using the local slope p(1 − p), then reconciled so the base rate (55.0% home) plus all contributions equals the stored probability (put any rounding remainder in an `other` row, never silently). Availability factors get human labels built from names, for example "Jokić out: −4.2 pts".

**Tests:** scenario weights sum to 1; a key player with `p_play` 0.5 yields a blended probability between the two scenario probabilities; gate off leaves bets unchanged; gate on halves or skips as configured; contributions plus base equal the stored probability within rounding; the Kelly worked example.

**Done when:** a dry-run of `--predict` against a recorded slate writes predictions, scenarios, factors and flags without errors, and the old behavior is unchanged when the candidate model is not the production model.

## 10. Phase 7: API, contract and sample data

Update `tests/contract_shapes.py` first, since it is the source of truth, then the routes, then `public/sample/*.json`.

- `GET /api/injuries?date=`: latest snapshot per game, grouped by team: `player_id`, `name`, `status`, `reason`, `p_play`, `rating`, `exp_min`, `impact_pts`, `report_time`.
- `GET /api/game/<game_id>`: add `availability: { home: [...], away: [...] }` (same player shape), `rest_days` and `is_b2b` for both teams (this closes the drawer's rest-days gap), `scenarios` (list of `{label, weight, home_win_prob}`), `prob_range`, and `factors` (from `prediction_factors`, empty list if absent).
- `GET /api/slate`: per game add `availability_summary: { home_out, away_out, key_out: [names], uncertain: bool, status_changed: bool }`.
- `GET /api/model`: add `feature_set_version`, the candidate list from the leaderboard, and whether `AVAILABILITY_GATE` is on.
- Performance splits: add a "star out" split to the box-score table data in `/api/performance` (bets, W–L, staked, P/L, ROI), alongside book, confidence and edge.
- All additions are additive and nullable. Old consumers keep working. If a table is empty (before the first snapshot), return empty lists and `null`, never errors, in the same "migration-pending payload" spirit as the integration plan.
- Update the sample season JSON with plausible availability data (a few `out`, `questionable` and `status_changed` examples) so the frontend can build the injury chips and "why the pick" views before real data exists. Label it as sample data.

**Tests:** shape tests for every new field; empty-table behavior; sample JSON validates against the contract.

## 11. Phase 8: props groundwork (no user-facing props yet)

The point is that when props arrive, they add rows and one model, not a redesign.

1. **Generic odds table** (migration `NNNN_market_odds.sql`): `market_odds` with `odds_id` PK, `game_id`, `captured_at`, `bookmaker`, `market` (`moneyline`, `spread`, `total`, `player_points`, `player_rebounds`, `player_assists`, `player_threes`, ...), `selection` (`home`, `away`, `over`, `under`), `player_id` (nullable), `line` (nullable numeric), `price_american`. Unique on (`game_id`, `captured_at`, `bookmaker`, `market`, `selection`, `player_id`, `line`). Dual-write moneyline prices here and to the existing `book_odds` until the frontend moves over; do not remove `book_odds`.
2. **Per-minute rate stats** (migration `NNNN_player_rates.sql`): `player_rate_stats` PK (`player_id`, `as_of`, `stat`), columns `rate_per_min` (shrunk estimate), `minutes_basis`, `version`; stats cover pts, reb, ast, fg3m, stl, blk, tov. Compute nightly with the same shrinkage idea as `box_value_v1`. Together with `player_minutes_projection`, this gives a first-order prop mean (rate times expected minutes) with no new data collection.
3. **Reserved prop prediction schema.** Write `migrations/reserved/NNNN_prop_predictions.sql` for a `prop_predictions` table (PK (`game_id`, `player_id`, `stat`, `line`, `model_name`); columns `mean`, `dist` (negative-binomial or normal parameters as jsonb), `p_over`, `p_under`, `bookmaker`, `price_over`, `price_under`, `edge`, `bet_side`, `bet_amount`, `result_value`, `profit_loss`, `predicted_at`). Put it in the `reserved/` folder, clearly marked not to be applied. Same for a `prop_*` section in the sample contract file, marked reserved.
4. **Interface stub.** Create `src/props/__init__.py` and `src/props/README.md` describing the planned flow (project minutes, project per-minute rates, form a distribution, compare to the line, size with `betting.stake` using `exposure_left` for same-game limits) and the open issues: same-game correlation between game bets and props, prop line churn, voiding rules when a player does not play, and name matching quality via `player_aliases`. No prediction code.
5. **Odds-provider note.** From phase 0, record in the README which prop markets and quotas the current odds provider offers, so the next step is decided with real constraints.
6. **Naming rule for new code.** Use "market" and "entity" in generic names. Never hard-code "game" into a table or function that props will reuse, such as `betting.py` and `market_odds`.

**Done when:** `betting.py` has no game-specific assumptions, `market_odds` is populated for tonight's moneylines, `player_rate_stats` is produced nightly, and the reserved files exist and are unapplied.

## 12. Phase 9: report and handoff

Finish `docs/player-data-implementation-report.md` with: what was built per phase, the evaluation tables, the promotion recommendation, config values chosen and why, anything that deviated from this spec, known risks (injury-report parsing fragility, realized-absence vs report mismatch, name-matching misses), and the exact commands to run the backfill, the evaluation and each new scheduled job. List the migration files in the order Noel should apply them, with a one-line description each. Do not apply them yourself.

## 13. Defaults to proceed on (do not block on these)

- Injury source: the official NBA injury report, unless phase 0 shows a better maintained source.
- Primary rating: `rapm_lite_v1`, with `box_value_v1` as the fallback and baseline.
- Candidate model family: calibrated logistic first.
- Uncertainty gate: shipped off.
- No automatic promotion.
- If something is ambiguous and the choice is reversible, pick the simpler option, note it in the report, and continue. Stop and ask only for irreversible actions (anything touching the live database, or merging).
