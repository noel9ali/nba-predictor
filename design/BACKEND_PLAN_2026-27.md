# Backend plan: 2026-27 season

Drafted Oct 7, 2026 from `main` @ `b58fc98` (planning only, no code changed). Builds on `docs/player-data-backend-spec.md`
(untracked in Noel's main checkout; call it "the spec" below) and `design/hardwood/STATE.md` "Open items".

## 0. Who runs this plan

- **Run it from a top-level Opus session (the orchestrator).** Spawned subagents can't spawn their own subagents, so the
  orchestrator has to be the session that spawns every builder, `/security-review` and Playwright subagent.
- **The orchestrator** plans, briefs, reviews, approves, merges into the integration branch, asks Noel for the approvals in §6,
  and keeps the process doc (§7). It writes very little code: only one-line conflict fixes and the process doc.
- **Builders** are Sonnet subagents, one per work package (§4), each in its own worktree (`isolation: worktree`) on its own branch.
- **Branches:** the orchestrator creates `season-2026-27` from `main`. Packages branch from it and merge back into it after approval.
  `season-2026-27` reaches `main` only with Noel's approval, in batches (decision D4).

## 1. Baseline and facts

- **Production model:** `gradient-boosting-gridsearch`, retrained Oct 7, rank 1 of 6 on log loss. It was evaluated on 1,596 held-out
  games with a 55.0% home-win base rate: **accuracy 67.9%, log loss 0.6075, Brier 0.2094, AUC 0.729, ECE 0.035, 0.0% extreme
  predictions** (`data/model_leaderboard.csv`). This replaces the spec's baseline (legacy-calibrated-logistic, 68.2% / Brier 0.2089).
  The logistic model now scores 68.1% / log loss 0.6325 / Brier 0.2091. The top five models are within 0.002 log loss of each other.
- **Opener date is an assumption: Tue Oct 20, 2026.** Nothing in the repo confirms it. nba_api 1.11.4 ships no static schedule, and
  `ScheduleLeagueV2` needs a network call, which this session didn't make. `DESIGN_STATE.md`'s "Oct 21 – Nov 16" is sample data,
  not a source. **Orchestrator step 1:** confirm the date with one `ScheduleLeagueV2(season='2026-27')` call or with Noel. If it is
  Oct 21, every date below gains a day of buffer.
- **Readiness target:** green on the go/no-go checklist by **Mon Oct 19, 20:00**. The first scheduled run is Tue Oct 20 at 06:00.
- **Offline suite on `b58fc98`:** 291 tests, all OK.
- **Model artifacts** (`*.pkl`) are git-ignored and exist only in the main checkout's `data/`. Worktrees don't have them, so tests use fakes.

## 2. Workstream A: pipeline fixes (before the opener, highest priority)

Each item gives the root cause with file:line, the fix, the tests, and the acceptance criteria. Items (f) to (h) are new findings
from this session's read.

**(a) The 06:00 job has never run.**
- Root cause:
  - `schtasks /query /tn NBA-Predictor-Daily` returns "cannot find the file" on Oct 7, so the task was never registered.
  - `scheduler\run_daily.bat:13` redirects into `logs\workflow.log`, but only `task_scheduler_setup.ps1:18-21` creates `logs\`.
    When the folder is missing, cmd can't open the file and Python never starts.
  - `run_daily.bat:15-16` has no `exit /b`, so Task Scheduler always sees success.
  - `task_scheduler_setup.ps1:39-45` registers with no principal (the task runs only while Noel is logged on) and no `-WakeToRun`.
  - `daily_workflow.py:327-343` echoes the raw step output, unredacted, into `logs\workflow.log`.
  - `daily_workflow.py:372` logs every run as `kind='manual'`.
- Fix:
  - The bat does `if not exist logs mkdir logs`, rotates the log by date, and ends with `exit /b %ERRORLEVEL%`.
  - The setup script uses an S4U or "run whether logged on" principal (D5), sets `-WakeToRun`, and passes the `--trigger schedule` argument.
  - `daily_workflow.py` prints `redact_secrets(...)` output and adds `--no-sms` and `--trigger` flags.
- Tests (in `tests/test_daily_workflow.py`):
  - Static bat checks: mkdir, exit propagation, no bare `echo Done` exit.
  - The redaction applies to stdout.
  - `--no-sms` never constructs a Twilio client.
  - `kind` and `trigger` are recorded.
- Acceptance:
  - A forced-failure bat (fake step that exits 1) makes `run_daily.bat` exit 1.
  - After Noel registers the task, `Get-ScheduledTaskInfo` shows `LastTaskResult 0` for an approved manual run, `logs\` exists,
    and a `workflow_log` row says `trigger=schedule`.

**(b) Predict-time Elo skips the 25% season-start reversion.**
- Root cause:
  - `src/elo.py:116-146` (`get_current_ratings`) replays each team's latest stored pre-game row and keeps the first one seen
    (`setdefault`, :144-145). It never calls `apply_mean_reversion` (:29-34).
  - Training rows do get the reversion, because `compute_elo` applies it at :76-80 when the season changes.
  - Result: every team's first 2026-27 game is predicted on unreverted 2025-26 Elo, so a 1650 team carries an extra 37.5 points.
    `ELO_DIFF` holds 72% of the GB feature importance.
- Fix:
  - Add `get_current_ratings(season=None)`, which infers the season from the game date (October or later means `YYYY-(YY+1)`).
  - It replays history with the same `update_elo` and `apply_mean_reversion` that `compute_elo` uses (one pure function, used by
    both), then reverts any team whose last game was in an earlier season.
  - The call signature stays backward-compatible, so `predict.py` doesn't change.
- Tests (new `tests/test_elo.py`):
  - On a two-season fixture, the predict-time rating for each team's first new-season game equals the `HOME_ELO`/`AWAY_ELO`
    that `compute_elo` stores for that game.
  - Mid-season ratings are unchanged.
  - An unfinished game (WL null) is not counted as a loss (`elo.py:142` currently treats it as one).
- Acceptance: the parity test passes, and nothing else changes in the feature rows of mid-season games.

**(c) Predict-time rest days and rolling stats don't match training.**
- Root cause:
  - Training rolls within role: `features.py:45-46` builds `HOME_roll_*` from a team's previous 10 home games, and `AWAY_roll_*`
    likewise from away games.
  - Predict (`predict.py:48-62`) takes the latest `features` row where the team had that role. That row's rolling value was
    computed before that game, so tonight's input leaves out the team's most recent same-role game.
  - Rest days at predict time (`predict.py:65-80`) count from the last game in the same role. Training (`features.py:53-92`)
    counts from the last game in either role. The fallback at :77 is 2, and the unknown-team fallback at :171-172 is Elo 1500.
- Fix:
  - Split `features.py` into a pure `build_feature_frame(games, upcoming=None)`. Training calls it with no upcoming games.
  - Predict appends tonight's games as unplayed rows to the history from `games`, runs the same builder, and takes tonight's rows.
    Parity then holds by construction.
  - **The training definition doesn't change**, so no retrain is needed. Switching to all-games windows is a model change and is
    deferred (§9).
  - Predict refuses to run, with a loud step failure, when a team has fewer than 10 prior same-role games or when an Elo is missing.
- Leakage argument: the builder only reads rows with `GAME_DATE` strictly before the target game. Rolling values use `shift(1)`.
  Rest days use the previous game's date. An unplayed row carries no box-score values.
- Tests (new `tests/test_predict.py` plus `tests/test_features.py`):
  - Parity: for 20 historical games, rebuild each one as "upcoming" from games strictly before its date, and assert the features
    equal the training row (to 1e-9).
  - Leakage: mutating any same-day or later game must not change the output.
  - Rest days across roles.
- Acceptance: the parity and leakage tests pass, and the full suite stays green.

**(d) Silent failures in collect and odds.**
- Root cause in collect:
  - `collect.py:8-16` `SEASONS` stops at `'2025-26'`, so **2026-27 games would never be collected** (new finding). Elo and
    features would freeze at April 2026.
  - `collect.py:34-42` turns every exception into an empty frame, and `:61-66` returns normally when every season failed, so the
    step exits 0.
- Root cause in odds:
  - `odds.py:60-62` handles a non-200 response (bad key, quota 401/429) by printing and returning `{}`. `predict.py:208-225` then
    skips every game, exits 0, and the SMS says no predictions.
  - `odds.py:58` raises request exceptions whose message holds the full URL with `apiKey=`. That reaches the unredacted log file.
  - `odds.py:75-76` is dead code that raises IndexError when the markets list is empty.
  - `odds.py:100-101` keys by (home, away) only, so a second meeting of the same two teams overwrites the first.
- Fix in collect:
  - Derive the current season from the date. Daily mode fetches the current season only; `--backfill` fetches all seasons.
  - A failed current-season fetch raises, so the step exits 1. An empty result before the opener is fine.
- Fix in odds:
  - Raise `OddsError` with a sanitized message (no URL) on non-200 responses and exceptions.
  - Log quota headers, and warn below 50 remaining requests.
  - Key by (home, away, commence date).
  - Return the per-book grid for (f).
- Tests:
  - Collect: current-season failure exits 1; an empty preseason result exits 0; the season derived on 2026-10-20 is `2026-27`.
  - Odds: 401, 429 and timeout each raise `OddsError` and never contain the key; the dead code is gone; duplicate matchups are kept apart.
- Acceptance: all of the tests above pass, and a grep of the diff finds no `print(response.text)`.

**(e) Historical 2025-26 rows carry odds like +900 and +1000 with no saved book prices.**
- Evidence (read-only check of Noel's legacy `data/nba.db`): 174 real rows from Mar 9 to Apr 2026, plus 12 `TEST-` rows from Sep 15-17.
  - 25 rows are priced at +500 or longer (+700, +780, +950, +2500, ...) even though the model gave the pick about 57%.
  - 17 of those 25 got bets. 2 won, for P/L of −$92.68 on $1,089.92 staked.
  - 42 rows are priced at −500 or shorter.
  - 30 rows hold `home_win_prob` as float32 blobs.
  - No bookmaker was stored: `track.py:80-94` has no field for it.
- Root cause (hypothesis, to be verified in A7): `odds.py:67-106` has no `commence_time` filter, and The Odds API's `/odds` returns
  in-play events. Runs made after tip-off therefore captured live prices for teams that were trailing.
- Effect on the dashboard: `app.py:865-873` (`prediction_edge`) falls back to `prob − implied(odds)`, which shows edges of 40-50
  points on those past nights. They feed `top_edges` (:508), the edge buckets (:1313) and the Model-page walkthrough (:1715-1727).
  `MAX_DECIMAL_ODDS = 5.0` (`track.py:18`) now blocks such bets, but it doesn't stop the edges from being displayed.
- Fix going forward (A3): drop events whose `commence_time` is at or before now + 5 minutes. Predict also skips a pick when
  |model prob − implied| > 0.30 and records `skip_reason='odds_suspect'`.
- Fix for history (A7): migration `odds_quality` (`ok` / `suspect` / `unverified`), filled by an idempotent rule: no `bookmaker`
  and the 2025-26 season, or odds of +500 or longer / −500 or shorter. `prediction_edge` returns null for non-`ok` rows. P/L stays
  as recorded (D3).
- Tests: the commence-time filter; the suspect rule; edges come back null for flagged rows in `/api/slate`, the Model walkthrough and
  the performance edge buckets; contract shapes.
- Acceptance: Noel's read-only SQL count (A7 brief) matches the rows the migration flags, and the Playwright check shows no edge
  above 30 points on past nights.

**(f) New: the pipeline never writes the v2 columns.**
- Root cause: `track.py:80-94` inserts only the legacy columns. Nothing in `src/` writes `model_name`, `predicted_at`,
  `tip_time_utc`, `season`, `bookmaker`, `implied_prob`, `edge`, `bankroll_at_bet`, `kelly_full`, `kelly_fraction`, `status`,
  `home_score`, `away_score`, `skip_reason` or `book_odds`. `STATE.md:57-58` ("new nights fill them") is therefore wrong.
- Fix: predict writes every v2 field plus `book_odds` rows. Skipped games get a row with a `skip_reason`. Settling sets `status`,
  the scores, and `postponed`.
- Acceptance: a fake-DB test shows one predict-and-settle cycle fills every v2 column that the contract reads.

**(g) New: preseason games get predicted.**
- Root cause: `predict.py:27-45` keeps every scoreboard game. Once the task is live, preseason games (`001…`) would get predictions
  and bets.
- Fix: keep only game IDs starting `002` (regular season) or `004` (playoffs). Leave the play-in (`005`) and NBA Cup final as D-level config.

**(h) New: the daily retrain rewrites production.**
- Root cause: `run_pipeline.bat:8` includes `model`. `model.py:486-540` retrains, overwrites `model.pkl`, the leaderboard and the
  metadata, and publishes `model_runs` every morning. With no backup, that breaks rule 3 as soon as the task goes live.
- Fix (A8, per D1): drop `model` from the daily loop, add `model.py --backup` (timestamped copy of the artifacts into
  `data/backups/`) before any overwrite, and make retraining a manual, reported step.

## 3. Workstream B: player data (builds on the spec)

### 3.1 Corrections to the spec (apply them, don't re-litigate them)
- **Baseline:** use the GB numbers in §1. The candidate family is GB + availability. Logistic + availability is a second
  candidate, for attributing the gain.
- **Promotion rule (D8):**
  - log loss must improve by at least 0.002 on the 1,596-game test set;
  - Brier must not get worse;
  - ECE must stay at or below 0.040;
  - the walk-forward log loss must be better in at least 4 of 6 seasons (2020-21 to 2025-26).
  - Promotion is never automatic.
- **Paths:** migrations go in `supabase/migrations/<timestamp>_name.sql` with the timestamps pre-assigned in §4. The spec's
  `migrations/` and `NNNN_` names are superseded.
- **Phase 0 is mostly done.** The games composite PK (`…0200`), `bankroll` (`…0400`), `workflow_log` (`…0500`) and the numeric types
  (`…0300`) are already applied, and the canonical branch is `main`. The probes still need doing; they go into the B1 and B2 briefs.
- **Things that don't exist yet:** `daily_workflow.py --morning/--predict` modes, a 30-minute predict tick, and `src/config.py`.
  B1 adds its own scheduled task. Config constants go in `src/config.py`, created by the first package that needs it (B1).
- **Progress tracking:** the spec's §1b checkpoint and report files are replaced by the single process doc in §7.

### 3.2 Before the opener
1. **B1, injury archive, ASAP (target: running by Fri Oct 9).**
   - History can't be recovered, so archive to disk first. Each tick saves the raw PDF and the parsed JSON to `data/raw/injuries/`
     (git-ignored), with a manifest keyed by report time.
   - Snapshots load into `injury_snapshots` later, once Noel applies the migration. The load is idempotent and replays the whole
     archive, so the archive never waits on the schema.
   - B1 also checks one thing: if past PDFs turn out to be fetchable by URL pattern, a historical backfill becomes possible.
     Note what was found, but don't plan around it.
2. **B2, player box-score backfill:** spec phase 1 for 2019-20 to 2025-26.
   - Cache the raw data under `data/raw/players/`. Derive `player_absences`.
   - The DB load needs Noel's approval and the migration applied.
   - Daily incremental collection is wired in during the in-season window. It isn't urgent, because box scores can be recovered later.
3. **B3, ratings backfill:** spec phase 3, ratings half only.
   - Build `box_value_v1` first (cheap, the fallback). Build `rapm_lite_v1` if time allows.
   - Write a weekly `as_of` series for every season. Each rating uses games strictly before `as_of`.
4. **B4 (stretch), roster-based preseason Elo prior:** research only, with no production effect before the opener (D7).
   - Prior = (1−w)·reverted Elo + w·f(minutes-weighted returning-player ratings).
   - Judge it on the first 3 weeks of 2020-21 to 2025-26 by log loss and Brier, against the current 25% reversion. Also test plain
     reversion rates of 0.25, 0.33 and 0.40.
   - **Leakage trap:** don't use `CommonTeamRoster` for past seasons, because it returns an end-of-season roster that includes
     future trades. Point-in-time roster = the players who appeared for the team in the last 10 games before the opener,
     plus offseason moves only if they are dated before the opener. If that can't be built cleanly, report it and stop.

### 3.3 In season (about 4–6 weeks in, Nov 16 – Dec 4)
- **B5:** minutes projections and team availability features (spec phases 3–4).
- **B6:** walk-forward evaluation (spec phase 5) against the GB baseline.
- **B7:** predict-time integration behind `AVAILABILITY_ENABLED=false` (spec phase 6, plus `src/betting.py`).
- **B8:** API and contract additions (spec phase 7).
- **Later:** spec phase 8 (props groundwork) and phase 9 (handoff), after B8.

### 3.4 Training on realized absences vs predicting from the injury report
Training sees `p_play ∈ {0,1}` taken from realized absences. Live prediction sees report statuses hours before tip-off, and the
report misses late scratches and rest days. If nothing is done, the model trusts availability features more than it should at
predict time, and is overconfident on uncertain nights. The plan:
1. **Scenario blending at predict time (spec §9.2) is the main fix.** The model is conditional on the lineup, so averaging its
   predictions over lineup scenarios weighted by `p_play` gives the right expected probability, provided `p_play` is calibrated.
2. **Calibrate `p_play`.**
   - Fit `STATUS_TO_P_PLAY` from the B1 archive joined to realized absences, once there are 30+ nights.
   - Add a "no report" late-scratch rate per player tier, so that "available" doesn't mean 1.0.
   - Until then, use the spec's default map and call it uncalibrated.
3. **Match the timing.** Historical `as_of` is tip-off minus 60 minutes, but live predictions run at 06:00. B7 can't go live until
   D2 (predict timing) is decided. Live-like evaluation must use the archived snapshot closest to the actual predict time.
4. **Report the two results separately.** Realized-absence backtests are an upper bound. The only live expectation is the
   archive-replay result (30+ nights, so about late November). B6 reports both, and D8 is judged on archive replay too.
5. **Deferred:** noise-injection training, which masks realized absences at report-status rates. Try it only if (4) shows a gap
   larger than 0.003 in log loss.

## 4. Work packages

**COMMON preamble.** Paste this above every builder brief and fill in the `<…>` fields.
```
You are a Sonnet builder on the NBA predictor (Windows; Git Bash; repo in your isolated worktree off season-2026-27).
Branch: <id>-<slug>. Python: C:\Users\noel9\Desktop\nba-predictor\venv\Scripts\python.exe (run from your worktree).
Read only: README.md, design/BACKEND_PLAN_2026-27.md sections <§>, and the files listed below. Don't explore beyond them.
Hard rules: no calls to Supabase, The Odds API or Twilio. NBA endpoints only if this brief allows them (throttle at least 0.6 s, cache
to data/raw/). No DDL in Python; schema goes only in the migration file named here, unapplied. No retraining and no writes to
data/*.pkl, the leaderboard or the metadata. Never print .env values. force_utf8_stdio() stays first in __main__. Nothing app.py
imports may need more than requirements.txt. Pipeline steps exit non-zero on failure; DB-logging errors are reported, not raised.
Finish: add tests, run `python -m unittest discover -s tests` (it must stay green; the baseline is 291+), commit with the attribution
line your environment specifies, and `git push -u origin <branch>`. Never push, merge or touch main.
Report (under 200 words): branch + SHA | files changed | tests run/passed + names of new tests | each acceptance item met/not met with
evidence | deviations | needs from Noel (migrations, live calls) | not verified.
```

| ID | Files (each file owned by one package) | Depends on | Parallel group |
|---|---|---|---|
| A1 | `scheduler/run_daily.bat`, `scheduler/task_scheduler_setup.ps1`, `scheduler/README_scheduler.md`, `daily_workflow.py`, `tests/test_daily_workflow.py` | none | P1 |
| A2 | `src/collect.py`, `tests/test_collect.py` | none | P1 |
| A3 | `src/odds.py`, `tests/test_odds.py` | none | P1 |
| A4 | `src/elo.py`, `tests/test_elo.py` (new) | none | P1 |
| B1 | `src/injuries.py`, `src/config.py`, `run_injuries.bat`, `scheduler/injuries_task_setup.ps1`, `requirements-pipeline.txt`, `.gitignore`, `supabase/migrations/20261008000100_injury_snapshots.sql`, `tests/test_injuries.py`, `tests/fixtures/injuries/` | none | P1 |
| A5 | `src/features.py`, `src/predict.py`, `tests/test_features.py`, `tests/test_predict.py` (new) | A4 merged | P2 |
| A7 | `supabase/migrations/20261010000100_odds_quality.sql`, `app.py`, `tests/test_api_v2.py`, `tests/contract_shapes.py` | Noel's SQL result | P2 |
| B2 | `src/collect_players.py`, `src/absences.py`, `supabase/migrations/20261009000100_player_foundation.sql`, `tests/test_collect_players.py`, `tests/test_absences.py` | B1 merged (`.gitignore`, `config.py`) | P2 |
| A6 | `src/predict.py`, `src/track.py`, `tests/test_predict.py`, `tests/test_track.py`, `supabase/migrations/20261012000100_predictions_skip_reasons.sql` | A3, A5 merged | P3 |
| A8 | `run_pipeline.bat`, `src/model.py`, `tests/test_model_publish.py` | D1 | P3 |
| B3 | `src/ratings.py`, `supabase/migrations/20261013000100_player_ratings.sql`, `tests/test_ratings.py` | B2 merged | P3 |
| B4 | `scripts/eval_preseason_prior.py`, `tests/test_preseason_prior.py` | B3 merged | P4 (stretch) |

Run at most 5 builders at once. The groups don't share any files. Run a group's gates while the next group builds.

### A1 scheduler and exit codes
Brief:
```
Goal: make the scheduled daily run actually run, and fail loudly. Plan §2(a).
Tasks:
- run_daily.bat: create logs\ if it's missing; append to logs\workflow_YYYY-MM-DD.log; end with exit /b %ERRORLEVEL%.
- Setup script: S4U principal (no stored password), -WakeToRun, StartWhenAvailable, and the argument "--trigger schedule".
  Keep 06:00 and the 2h limit.
- daily_workflow.py: argparse with --no-sms and --trigger {schedule,manual,api}; log kind=daily and trigger correctly; print
  redact_secrets(step output) instead of raw output.
- README_scheduler: register / verify (Get-ScheduledTaskInfo) / unregister.
Do NOT register the task or run the workflow. Tests: static bat assertions; redaction on stdout; --no-sms never builds a Twilio
client; exit code is 1 when a fake step fails.
```
Acceptance: bat ends in `exit /b`, mkdir is present, no unredacted output reaches the print path, all new tests are green.
Noel then registers the task (§5, Oct 16).

### A2 collect: season roll-over and loud failures
Brief:
```
Goal: collect 2026-27 and stop exiting 0 when collection fails. Plan §2(d).
Tasks:
- current_season(today): October or later gives YYYY-(YY+1), otherwise the previous season.
- Default run fetches the current season only; --backfill fetches 2019-20 through current.
- fetch_season raises CollectError after its retries (no empty frame). An empty successful response before the opener is valid
  and is logged as "0 rows (preseason?)".
- __main__ exits 1 on CollectError.
Tests (fakes only, no network): the season boundary (2026-09-30 gives 2025-26, 2026-10-01 gives 2026-27); a failure exits 1;
empty-but-OK exits 0; the existing composite-PK hint test still passes.
```
Acceptance: the tests above pass; `SEASONS` isn't hard-coded at its upper end.

### A3 odds hardening
Brief:
```
Goal: no silent odds failures, no in-play prices, no key leaks. Plan §2(d)(e).
Tasks:
- OddsError (message without the URL or key) on non-200 responses and on requests exceptions.
- Skip events with commence_time <= now+5min (clock injectable).
- Key results by (home, away, commence date).
- Also return the per-book prices for PREFERRED_BOOKS ({book: (home, away)}) for book_odds.
- Log x-requests-remaining and warn below 50.
- Delete the dead code at lines 75-76.
- Keep get_tonights_odds() compatible: same top-level keys plus "books", "commence_time".
Tests with a fake requests module: 401, 429 and ConnectionError each raise and str(err) has no key; started events are dropped;
two meetings of the same pair are both kept; per-book grid correctness.
```
Acceptance: all of the above, plus `predict.py` needs no change to keep working (A6 consumes the new fields).

### A4 Elo season reversion at predict time
Brief:
```
Goal: predict-time Elo equals what training would assign. Plan §2(b).
Tasks:
- Extract a pure replay(games_df) -> (records, final_ratings, last_season_by_team) that compute_elo also uses.
- get_current_ratings(season=None) replays, then applies apply_mean_reversion to teams whose last season < target season
  (season inferred from today if None).
- Unfinished games (WL null) must not update ratings.
Keep the signature compatible.
Tests in a new tests/test_elo.py on a hand-built two-season fixture: each team's first new-season predict-time Elo equals the
stored pre-game Elo for that game; mid-season unchanged; WL null ignored.
```
Acceptance: the parity test passes; `compute_elo` output is byte-identical on the fixture before and after the change.

### B1 injury archive (start day 1)
Brief:
```
Goal: archive every official NBA injury report from now on. Disk first, DB later. Plan §3.2(1), spec §5.
Probe (NBA site allowed, max 10 requests, throttled): the current report URL pattern and cadence, whether past PDFs are
fetchable, and whether preseason reports exist. Record the findings in the report.
Tasks:
- src/injuries.py --snapshot: fetch the latest report, save the PDF + parsed JSON + manifest under data/raw/injuries/YYYY-MM-DD/.
  Idempotent per report_time.
- Parse with pdfplumber (pin it in requirements-pipeline.txt; no Java/tabula).
- Normalize statuses via STATUS_MAP in a new src/config.py.
- Keep unmatched names (no player table yet): store player_name_raw.
- --load: replay the archive into injury_snapshots (append-only, unique on source, report_time, team, name_raw) when the table
  exists; if it's missing, print the migration name and exit 0.
- run_injuries.bat plus scheduler/injuries_task_setup.ps1: hourly 09:00-23:00 ET, separate task "NBA-Predictor-Injuries".
  A failed tick logs and exits 1 but never touches the daily task.
- Write the migration file (unapplied).
Tests: status normalization table; parser on 2 recorded PDF fixtures; idempotent re-snapshot; --load against the fake DB.
```
Acceptance:
- The fixtures parse into more than 0 rows with correct statuses.
- The re-run adds nothing.
- The probe findings are in the report.
- `data/raw/` is git-ignored.
- After the merge, Noel registers the task, and the orchestrator checks that `data/raw/injuries/` gains files within 2 hours.

### A5 predict feature parity
Brief:
```
Goal: predict-time features built by the same code as training. Plan §2(c). The leakage rules are non-negotiable.
Tasks:
- Refactor features.py into a pure build_feature_frame(games, elo, upcoming=None) with run() calling it (stored output unchanged).
- predict.py builds tonight's rows by appending unplayed games to the history in `games` and using the builder, with Elo from
  get_current_ratings().
- Missing history or Elo -> skip the game with reason "missing_data" (A6 persists it) and print it loudly; any exception fails the step.
Do not change the training definition (rolling within role).
Tests: parity on 20 historical fixture games (rebuild as upcoming from strictly-earlier games, equal to 1e-9); leakage (mutate any
same-day or later game, output unchanged); rest days across roles; the stored features frame is identical before and after the refactor.
```
Acceptance: the orchestrator reruns the parity and leakage tests itself and reads their assertions (§6).

### A7 suspect historical odds
First, the orchestrator sends Noel this read-only SQL to run in the Supabase SQL editor:
`select count(*) filter (where odds >= 500 or odds <= -500), count(*) filter (where bookmaker is null), count(*) from predictions where season = '2025-26';`
Brief:
```
Goal: past nights stop showing fake edges. Plan §2(e). Noel's counts: <paste>.
Tasks:
- Migration 20261010000100_odds_quality.sql: add predictions.odds_quality text default 'ok' with a check constraint; an idempotent
  update flags 'suspect' (odds >= 500 or <= -500) and 'unverified' (no bookmaker, season 2025-26, not suspect).
- app.py: prediction_edge returns None unless odds_quality is 'ok' or missing (pre-migration safe); expose odds_quality on game
  items (additive, nullable); exclude flagged rows from top_edges, the edge buckets and the Model walkthrough. P/L unchanged.
- Update contract_shapes.
Tests: each consumer with a flagged row; a pre-migration row without the column behaves as before; the contract shape.
```
Acceptance: the flagged count in a fake DB equals the rule; requires a Playwright check (§6).

### B2 player foundation
Brief:
```
Goal: spec phase 1 tables + backfill + absences, built offline first. Plan §3.2(2), spec §4 (use supabase/migrations path and
timestamp 20261009000100). NBA allowed: LeagueGameLog P mode per season (7 calls) plus 3 probe calls (BoxScoreTraditionalV3 DNP
comment, CommonAllPlayers); cache to data/raw/players/.
Tasks: collect_players.py --backfill (cache -> normalized frame -> upsert via database.py); --load-only from cache; absences.py
(spec rules; config in src/config.py). Don't wire into run_pipeline.bat.
Tests: spec §4 test list. Report row counts per season and reconcile them against games (two teams per game).
```
Acceptance: the spec §4 tests pass; per-season counts are in the report; the DB load waits for Noel (migration plus approval to write).

### A6 predict v2 writes and the preseason guard
Brief:
```
Goal: every v2 column and book_odds filled on new nights; no preseason bets. Plan §2(e)(f)(g).
Tasks:
- predict keeps only game IDs starting 002/004.
- Writes model_name (NBA_PRODUCTION_MODEL), predicted_at, tip_time_utc, season, bookmaker, implied_prob, edge, bankroll_at_bet,
  kelly_full, kelly_fraction, and book_odds rows from A3's grid.
- Skipped games still get a row with skip_reason (no_odds, missing_data, odds_suspect when |prob-implied|>0.30).
- Migration 20261012000100 extends predictions_skip_reason_chk with 'odds_suspect' (idempotent drop/add).
- track.update_results sets status final/postponed and home_score/away_score.
- Keep the Kelly worked example: bankroll 1111.67, p 0.61, -105 -> 55.58.
Tests: one fake predict+settle cycle fills every column tests/contract_shapes.py reads; a preseason ID is ignored; each skip reason;
the Kelly example.
```
Acceptance: the cycle test passes; the orchestrator diff-checks that no edge is computed from a missing price.

### A8 retrain guard (after D1)
Brief:
```
Goal: production artifacts never change silently. Plan §2(h).
Tasks: remove model from run_pipeline.bat's daily loop (D1 default); model.py --backup copies model.pkl, scaler.pkl, leaderboard
and metadata to data/backups/<UTC timestamp>/ and run() always backs up before overwriting; print the before/after leaderboard
rows for the production model.
Tests: the backup happens before the save (fake fs); the bat no longer lists model.
```
Acceptance: the tests pass; README's "Daily usage" line updated.

### B3 ratings backfill
Brief:
```
Goal: point-in-time player ratings for 2019-20..2025-26. Plan §3.2(3), spec §6 ratings half (no minutes projection).
Tasks: src/ratings.py with box_value_v1 (required) and rapm_lite_v1 (if time allows), weekly as_of refit from the B2 cache;
write to data/raw/ratings/ plus --load into player_ratings (migration 20261013000100, unapplied).
Tests: ridge recovers synthetic effects; ratings at as_of use no games on or after as_of; shrinkage toward the mean for low minutes.
```
Acceptance: the as-of leakage test passes; a worked example (one team's top 8 on 2025-01-15) is in the report.

### B4 preseason prior (stretch)
Brief:
```
Goal: research whether a roster-based prior beats 25% reversion on season openers. Plan §3.2(4). No production change, no
DB writes, no retraining of the production model. Evaluate Elo-only win probability (expected_win_prob) and, separately, the
GB features with ELO swapped (score with the existing artifacts only if provided; otherwise Elo-only).
Output: a table per season (first 3 weeks) of log loss and Brier for reversion 0.25/0.33/0.40 and prior weights w ∈ {0.25,0.5}.
Tests: the point-in-time roster uses only games before the opener.
```
Acceptance: the table is in the report, and the leakage test passes. Changing production is a separate decision for Noel.

### In-season packages (briefs written at the time from the spec sections; there is too much to fix now)
| ID | Spec phase | Starts | Key acceptance |
|---|---|---|---|
| B2b | phase 1 daily incremental + wiring into `run_pipeline.bat` | Oct 26 | idempotent daily run; the step fails loudly |
| B5 | phases 3 (minutes) + 4 | Nov 2 | leakage guard on `as_of`; minutes conserve 240 |
| B6 | phase 5 | Nov 16 | D8 rule judged on the test set, walk-forward, and archive replay (30+ nights) |
| B7 | phase 6 + `betting.py` | after B6 | `AVAILABILITY_ENABLED=false` leaves predictions byte-identical |
| B8 | phase 7 | after B7 | contract tests; Playwright check |

## 5. Schedule to the opener (assumes Tue Oct 20)

Estimates are in builder-hours, with gates of about 1–2 h each on top. Noel's approvals are the real constraint.

| Day | Orchestrator / builders | Noel |
|---|---|---|
| Thu Oct 8 | Confirm the opener date. Create `season-2026-27` and the process doc. Spawn P1: A1 (3h), A2 (2h), A3 (3h), A4 (3h), B1 (5h) | Run the A7 SQL; answer D1–D5 |
| Fri Oct 9 | P1 gates (security review). Merge P1 to the integration branch. Spawn A5 (5h), B2 (5h), A7 (3h) | Apply `…_injury_snapshots`; register the injury task (**B1 live**) |
| Sat–Sun Oct 10–11 | A5, B2, A7 gates; A7 Playwright check | Apply `…_player_foundation`; approve the B2 load |
| Mon Oct 12 | Spawn A6 (5h), A8 (2h), B3 (6h) | |
| Tue Oct 13 | A6, A8 gates | Apply `…_odds_quality` and `…_skip_reasons` |
| Wed Oct 14 | B3 gate; **batch 1: Noel approves `season-2026-27` into `main`** (A1–A8, B1, B2) | Approve merge; deploy production from the main SHA (A7 changed `app.py`); prod Playwright re-check |
| Thu Oct 15 | **Dry run (A9)** on a preseason day: `daily_workflow.py --no-sms --trigger manual`. Expect: collect is OK with 0 new rows, preseason games ignored, 1 Odds API credit used, exit 0 | Approve that live run (Odds credit + prod DB writes) |
| Fri Oct 16 | Fix anything from the dry run; spawn B4 (stretch) | Register the 06:00 task (A1 setup, admin); approve one `Start-ScheduledTask` with `--no-sms` |
| Sat–Mon Oct 17–19 | Buffer; B3 load; **go/no-go checklist** Mon 20:00; batch 2 to main if B3/B4 changed anything | Approve batch 2 and the B3 load |
| Tue Oct 20 | 06:00 run: opener predictions. Check `workflow_log`, `logs\`, and the predictions' v2 columns | Read the SMS |
| Wed Oct 21 | First settle: check `status`, the scores, bankroll recompute, and one A4 Elo spot-check | |

**Critical path:** A4 → A5 → A6 (needs A3) → batch 1 merge → dry run → task registration. That's about 13 builder-hours plus 4 gates,
plus Noel's approval on Oct 14–16. B1 isn't on the opener's critical path, but it's the most urgent, because every day it isn't
running loses data for good.

**Go/no-go on Oct 19:**
- the suite is green on `main`;
- the dry-run `workflow_log` row says success;
- the task shows `LastTaskResult 0`;
- `data/raw/injuries/` is growing;
- the opener's game IDs start `002`;
- A4's parity test passes;
- 300+ Odds API requests remain.

**If time runs short, cut in this order:**
1. B4.
2. `rapm_lite_v1` (keep `box_value_v1`).
3. The B3 DB load (keep the disk series).
4. A7 (it only affects how history is displayed; new rows are clean thanks to A3/A6). It can ship in week 1.
5. The `book_odds` grid and `kelly_*` part of A6.

Never cut A1–A5, the preseason guard and skip rows in A6, or B1. If A5 isn't merged by Oct 16, run the opener anyway: the known bias
is home-only stats that are one game stale, and the alternative is no predictions at all.

## 6. Gates and approval

**Per package, in order:**
1. A Sonnet builder subagent builds it.
2. A Sonnet subagent runs `/security-review` on the branch diff against `season-2026-27`.
3. If `app.py`, `public/`, `templates/` or the API contract changed, a Sonnet Playwright-CLI subagent checks the branch's Vercel
   preview at 1440 and 400 px. That's the pages `/`, `/model`, one drawer and one past night, plus the console and network for 4xx/5xx.
   The preview is behind SSO, so use Noel's existing authenticated method, as in the Oct 7 release.
4. Orchestrator approval (rubric below).
5. The orchestrator merges into `season-2026-27` with `--no-ff`.

Builders, reviewers and Playwright agents are always spawned by the orchestrator.

**Noel's rules:**
- Nothing merges into `main`, nothing is pushed to `main`, and nothing is deployed to production without Noel's explicit approval.
- Migrations are files only, and Noel applies them by hand, in timestamp order.
- Production deploys are manual: create the deployment from the `main` SHA (pushes don't auto-deploy).
- Production stays behind Vercel SSO.
- Live calls to The Odds API, Twilio or a production DB write or backfill each need Noel's approval at the time.

**What the orchestrator checks itself before approving:**
- It reads the whole non-test diff and the new tests' assertions.
- It reruns the offline suite in the branch worktree and compares the count with the last recorded one.
- For A4, A5, B2, B3, B5 and B6, it reruns the leakage and parity tests by name, and confirms each one asserts strictly-before
  logic, not just that the function runs.
- It greps the diff for DDL in `.py` (`create table|alter table`), `print(` near the env or the key, new imports in `app.py`
  (sklearn, xgboost, torch, numpy beyond what's already there), `except Exception: pass`, and `exit 0` after a failure.
- Migrations: the timestamp matches §4, the SQL is idempotent (`if not exists`, guarded constraints), and nothing was applied.
- Model metrics (B6, and A8's before/after): it recomputes the numbers from the committed evaluation command and compares them
  with the GB baseline in §1.

**What it accepts from reports:**
- The live-probe shapes from B1 and B2.
- Backfill row counts (Noel's SQL verifies them later).
- Playwright screenshots and findings. It reads every finding rated medium or above.
- The security reviewer's "no confirmed findings". It reads any confirmed finding in full and sends it back to the builder.

**Rejecting:** send one consolidated list of fixes to the same builder (resume its worktree). Allow at most 2 rounds, then the
orchestrator decides or escalates to Noel.

## 7. Process doc and resume ("Continue")

On day 1 the orchestrator creates `design/backend/PROCESS_2026-27.md` on `season-2026-27`. It **rewrites** the file (it doesn't
append) and commits it after every gate. Template:
```
Resume here: <one line: next action + who is waiting on whom>
Opener: <date, source> | Integration branch HEAD: <sha> | main: <sha> | Suite: <N> OK
Packages: ID | branch | SHA | build | security | playwright | approved | merged-int | in-main      (todo/doing/done/blocked/n-a)
Noel queue: migrations to apply (in order) | live calls awaiting approval | decisions open (D#) | merges/deploys awaiting
Live checks: injury task last file <time> | daily task LastTaskResult <code> | Odds requests remaining <n>
Log (last 10 gates): <date> <ID> <gate> <result> <1-line reason>
```

**On "Continue":**
1. Read the process doc and this plan's §4–§6 only.
2. Run `git -C <main checkout> worktree list`, `git log --oneline -5 season-2026-27`, and `git branch -r`.
3. Reconcile: if the repo and the doc disagree, trust the repo and fix the doc.
4. Re-spawn only the packages that are `doing` and have no pushed SHA. For a package with a pushed SHA, resume at its next gate.

**Token discipline:**
- Briefs are COMMON plus the package block. Don't paste plan sections; give references to them.
- One report per package, under 200 words. The orchestrator doesn't re-read files the builder summarized, except the diff and the tests.
- Security and Playwright subagents get the branch name and a 3-line scope, not the plan.

## 8. Risks

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| The laptop is asleep or off at 06:00 | High / no predictions | `-WakeToRun`, `StartWhenAvailable`, plugged in; the SMS doubles as a heartbeat (D5) |
| The injury PDF format or URL changes | Medium / archive gap | Raw PDFs are kept; a failed tick exits 1; the orchestrator checks the archive daily for the first week |
| stats.nba.com rate-limits or blocks | Medium / collect fails | A2 fails loudly; throttling; cached backfills |
| The Odds API quota (free tier 500/month) | Low / no odds | About 1–2 calls a day; warning below 50; A3 surfaces errors |
| Opener-week features are thin (home-only windows straddle seasons) | Certain / weaker early picks | Matches training (parity); B4 researches a better prior |
| Undocumented S3 origin for live scores moves | Medium / stale live board | Already returns `stale:true` or a 503 (`STATE.md`); out of scope |
| Opener date assumption is wrong | Low / schedule shifts | Orchestrator step 1 confirms it |
| Supabase free-tier size | Low | player_games is about 190k rows; snapshots about 40k a season |

## 9. Decisions for Noel (recommended default in bold)

- **D1, daily retraining:** **freeze the model during the season**. Retraining becomes manual (roughly every 2 weeks), with a
  before/after report and a backup (A8). The alternative is to keep the daily silent retrain.
- **D2, predict timing:** **keep the single 06:00 run for the opener**. Decide on a second run (about 17:00 ET, updating
  predictions until tip-off) when B7 is designed.
- **D3, suspect 2025-26 odds:** **flag them and null their edges, keep P/L as recorded, add a footnote**. The alternative is to void
  those bets and recompute the bankroll.
- **D4, merge cadence:** **an integration branch with two batch merges into `main` (Oct 14, Oct 19)**. The alternative is a merge
  per package, which needs about 12 approvals.
- **D5, task principal:** **S4U ("run whether logged on", no stored password) plus `-WakeToRun`**. S4U can't reach network shares,
  but this setup doesn't need any.
- **D6, injury source:** **the official NBA PDF parsed with `pdfplumber`** (a pinned pipeline dependency).
- **D7, preseason prior:** **research only for the opener.** It goes into the model only through D8 later.
- **D8, promotion bar:** **the §3.1 rule.**
- **D9, 2026-27 bankroll:** **continue the single running ledger.** The dashboard already splits by season. The alternative is
  resetting to $1,000 on Oct 20.
- **D10, play-in and NBA Cup final (`005` / special IDs):** **predict the play-in, skip nothing else.**

## 10. Deliberately left out

- **Spec phase 8 (props groundwork)** and the spec's API phase before B7. No prop schema yet.
- **A retrain before the opener.** The Oct 7 GB stays live; A5 removes the need for one.
- **Switching rolling windows to all games** (a model change) and **noise-injection training**. Both are in-season candidates
  judged by D8.
- **Moving the scheduler off the laptop** (cron or GitHub Actions). That needs secrets handled elsewhere; revisit after the season starts.
- **The `nba_api` pin in `requirements.txt`** (the Vercel path). It's probably used by `live_scores`. It isn't verified, and it isn't
  a blocker.
- **Not verified in this session:** the opener date; whether production Supabase holds the same +500 rows as the legacy SQLite
  (A7's SQL settles it); whether The Odds API returned in-play prices (the hypothesis in (e)); whether past injury PDFs can still be
  fetched (B1's probe).
