# Backend plan: 2026-27 season

Drafted Oct 7, 2026 from `main` @ `b58fc98` (planning only, no code changed). Updated the same day with Noel's decisions (§9).
Builds on `docs/player-data-backend-spec.md` (untracked in Noel's main checkout; called "the spec" below) and on the
"Open items" in `design/hardwood/STATE.md`.

## 0. Who runs this plan

- **The orchestrator must be a top-level Opus session.** Spawned subagents can't spawn their own subagents, so it has to be the
  session that spawns every builder, `/security-review` and Playwright subagent.
- **The orchestrator's job:** it plans, briefs, reviews, approves, merges into the integration branch, asks Noel for the approvals
  in §6, and keeps the process doc (§7). It writes almost no code: one-line conflict fixes and the process doc only.
- **Builders** are Sonnet subagents, one per work package (§4), each on its own branch in its own worktree (`isolation: worktree`).
- **Branches:** the orchestrator creates `season-2026-27` from `main`. Packages branch from it and merge back into it after approval.
  It reaches `main` only in two batches that Noel approves (D4): around Oct 14 and around Oct 19.

## 1. Baseline and facts

- **Production model:** `gradient-boosting-gridsearch`, retrained Oct 7, rank 1 of 6 on log loss.
  - Held-out set: 1,596 games, 55.0% home-win base rate.
  - **Accuracy 67.9%, log loss 0.6075, Brier 0.2094, AUC 0.729, ECE 0.035, 0.0% extreme predictions** (`data/model_leaderboard.csv`).
  - This replaces the spec's baseline (legacy-calibrated-logistic, 68.2% / Brier 0.2089). The logistic model now scores
    68.1% / 0.6325 / 0.2091.
  - The top five models are within 0.002 log loss of each other.
- **Opening night is Tue Oct 20, 2026** (confirmed by Noel on Oct 7). The readiness target is the go/no-go check on
  **Mon Oct 19 at 20:00**. The first scheduled morning run is Tue Oct 20 at 06:00, and the first pre-tip run is about 1 hour
  before that night's first tip-off.
- **Offline suite on `b58fc98`:** 291 tests, all OK.
- **Model artifacts:** the `*.pkl` files are git-ignored and exist only in the main checkout's `data/`. Worktrees don't have them,
  so tests use fakes.
- **No retrain before the opener.** The first weekly gated retrain (D1) runs Mon Oct 26 at 03:00.

## 2. Workstream A: pipeline fixes (before the opener, highest priority)

Each item gives the root cause (file:line), the fix, the tests and the acceptance criteria. Items (f) to (h) are new findings from
this session's read.

### (a) The 06:00 job has never run

**Root cause:**
- `schtasks /query /tn NBA-Predictor-Daily` says "cannot find the file" on Oct 7, so the task was never registered.
- `scheduler\run_daily.bat:13` redirects into `logs\`, but only `task_scheduler_setup.ps1:18-21` creates that folder. Without it,
  cmd can't open the log file and Python never starts.
- `run_daily.bat:15-16` has no `exit /b`, so Task Scheduler always records success.
- `task_scheduler_setup.ps1:39-45` registers the task with no principal, so it runs only while Noel is logged on, and it doesn't
  set `-WakeToRun`.
- `daily_workflow.py:327-343` echoes the raw step output, unredacted, into `logs\workflow.log`.
- `daily_workflow.py:372` logs every run as `kind='manual'`.
- **Constraint to respect:** `workflow_log` only allows `kind` values morning, predict and manual, and `trigger` values schedule
  and manual (`…000500_workflow_log.sql`).

**Fix (A1):**
- The bat creates `logs\` if it's missing, writes one log per day, and ends with `exit /b %ERRORLEVEL%`.
- A shared `scheduler/_task_common.ps1` sets the S4U principal, `-WakeToRun`, `StartWhenAvailable` and restart-on-failure. Every
  setup script dot-sources it.
- `daily_workflow.py` gets `--no-sms`, `--trigger {schedule,manual}` and `kind='morning'`, and prints step output through
  `redact_secrets`.

**Tests:**
- Static checks on the bat files.
- Redaction applies to stdout.
- `--no-sms` never builds a Twilio client.
- A forced step failure makes the process exit 1.

**Acceptance:** all of those pass. After registration, `Get-ScheduledTaskInfo` shows `LastTaskResult 0`, and `workflow_log`
records `kind=morning` and `trigger=schedule`.

### (b) Predict-time Elo skips the 25% season-start reversion

**Root cause:**
- `src/elo.py:116-146` (`get_current_ratings`) replays each team's latest stored pre-game row (`setdefault`, :144-145) and never
  calls `apply_mean_reversion` (:29-34).
- Training rows are reverted: `compute_elo` does it at :76-80.
- Result: each team's first 2026-27 game is predicted on unreverted Elo. A 1650 team, for example, gets +37.5 points, and
  `ELO_DIFF` carries 72% of the GB model's feature importance.
- `elo.py:142` also counts an unfinished game (WL null) as a loss.

**Fix (A4):**
- One pure replay function, shared by `compute_elo` and `get_current_ratings(season=None)`.
- It reverts any team whose last game was in an earlier season than the target season.
- The signature stays compatible.

**Tests (new `tests/test_elo.py`):**
- On a two-season fixture, each team's first new-season predict-time Elo equals the stored pre-game Elo.
- Mid-season ratings are unchanged.
- A WL-null game is ignored.

**Acceptance:** the tests pass, and `compute_elo` output is identical on the fixture.

### (c) Predict-time rest days and rolling stats differ from training

**Root cause:**
- Training rolls within role: `features.py:45-46` builds `HOME_roll_*` from the team's previous 10 home games, and `AWAY_roll_*`
  likewise from away games.
- `predict.py:48-62` reads the team's latest `features` row in that role. That row's value was computed before the game, so the
  team's most recent same-role game is missing.
- Predict-time rest days (`predict.py:65-80`) count from the last game in the same role. Training (`features.py:53-92`) counts
  from the last game in either role.
- Silent fallbacks: rest days default to 2 (:77) and Elo defaults to 1500 (:171-172).

**Fix (A5):**
- Add a pure `build_feature_frame(games, elo, upcoming=None)`. Training calls it without upcoming games.
- Predict appends tonight's games as unplayed rows and takes their output, so the two paths match by construction.
- The training definition doesn't change, so no retrain is needed.
- Missing history or Elo means the game is skipped with `missing_data` and a loud message. It doesn't fall back to defaults.

**Why it can't leak:** the builder reads only rows with `GAME_DATE` strictly before the target game. Rolling stats use `shift(1)`.
Rest days use the previous game's date. Unplayed rows carry no box-score values.

**Tests:**
- Parity: for 20 historical games, rebuilding each as "upcoming" from strictly earlier games matches the stored training row
  to 1e-9.
- Leakage: changing any same-day or later game doesn't change the output.
- Rest days work across home and away roles.

**Acceptance:** the orchestrator reruns the parity and leakage tests itself (§6).

### (d) Silent failures in collect and odds

**Root cause in `collect.py`:**
- `collect.py:8-16` `SEASONS` stops at `'2025-26'`, so **2026-27 is never collected**.
- `collect.py:34-42` turns every exception into an empty frame.
- `collect.py:61-66` exits 0 even when every season failed.

**Root cause in `odds.py`:**
- `odds.py:60-62` prints and returns `{}` on a non-200 response (bad key, 401/429 quota). `predict.py:208-225` then skips every
  game and still exits 0.
- `odds.py:58` request exceptions carry the full URL, including `apiKey=`, into the log file.
- `odds.py:75-76` is dead code that raises IndexError on an empty markets list.
- `odds.py:100-101` keys results by (home, away) only.

**Fix:**
- A2: derive the current season from the date. The daily run fetches only the current season; `--backfill` fetches all seasons.
  A failed current-season fetch exits 1.
- A3: raise `OddsError` with a sanitized message, log the remaining quota, key results by (home, away, commence date), and return
  the per-book grid.

**Tests:**
- The season boundary.
- A failure exits 1, and an empty preseason result exits 0.
- 401, 429 and timeout each raise without the key in the message.
- Duplicate matchups are kept apart.

**Acceptance:** all of the above pass, and the diff has no `print(response.text)`.

### (e) Historical 2025-26 rows carry odds like +900 or +1000 with no book prices saved

**Evidence** (read-only look at Noel's legacy `data/nba.db`):
- 174 real rows (Mar 9 – Apr 2026) plus 12 `TEST-` rows (Sep 15–17).
- 25 rows have odds of +500 or longer (+700, +950, +2500, …) where the model gave the pick about 57%. 17 of them were bet:
  2 won, P/L −$92.68 on $1,089.92 staked.
- 42 rows have odds of −500 or shorter.
- No bookmaker was stored: `track.py:80-94` has no such field.

**Likely cause** (a hypothesis that A7 verifies): `odds.py:67-106` doesn't filter on `commence_time`, and `/odds` also returns
in-play events. A run after tip-off therefore stored live prices.

**Effect:**
- `app.py:865-873` falls back to `prob − implied(odds)`, so past nights show edges of 40–50 points.
- Those feed `top_edges` (:508), the edge buckets (:1313) and the Model walkthrough (:1715-1727).

**Fix:**
- A3 drops events with `commence_time` ≤ now + 5 min.
- A6 skips any pick with |prob − implied| > 0.30 and logs `odds_suspect`.
- A7 adds an `odds_quality` flag and nulls the edge for flagged rows. P/L is kept (D3).

**Acceptance:** Noel's read-only SQL count matches the flagged rows, and the Playwright check shows no past-night edge above 30 points.

### (f) New: the pipeline never writes the v2 columns

**Root cause:**
- `track.py:80-94` inserts only the legacy columns.
- Nothing writes `model_name`, `predicted_at`, `tip_time_utc`, `season`, `bookmaker`, `implied_prob`, `edge`, `bankroll_at_bet`,
  `kelly_*`, `status`, the scores, `skip_reason` or `book_odds`.
- So `STATE.md:57-58` ("new nights fill them") is wrong.
- Saving is also insert-once (`track.py:71-79`), which blocks D2's re-predict.

**Fix (A6):** an upsert per `game_id` that writes every v2 field, plus `book_odds`, a `prediction_runs` history row, skip rows, and
the settle fields.

### (g) New: preseason games get predicted

**Root cause:** `predict.py:27-45` keeps every scoreboard game, including preseason games (`001…`).

**Fix (A6):** keep only game IDs starting with `002` (regular season), `004` (playoffs) or `005` (play-in).

### (h) New: the daily retrain silently rewrites production

**Root cause:**
- `run_pipeline.bat:8` includes `model`.
- `model.py:486-540` retrains, overwrites `model.pkl`, the leaderboard and the metadata, and publishes `model_runs` every morning,
  with no backup and no gate.

**Fix (A8, D1):** `model` comes out of the daily loop, and the weekly gated retrain in §2.1 replaces it.

## 2.1 Decided designs (D1 and D2)

### Weekly auto-gated retrain (D1)

**When:**
- Task `NBA-Predictor-Retrain` runs Mondays at 03:00 (S4U, wake, 2h45m limit), starting Oct 26.
- It runs `daily_workflow.py --mode retrain`: collect → elo → features → `model.py --weekly-gate`.
- The daily run never trains.

**Challenger and incumbent:**
- **Challenger:** a fresh fit of the incumbent's model family (`NBA_PRODUCTION_MODEL`) on the standard chronological 80/20 split
  of the current `features`, using the same `FEATURES`.
- **Incumbent:** the live `model.pkl`/`scaler.pkl`, scored on the **same** new test split.
- The gate checks that the incumbent's training cutoff (from metadata) is on or before the start of the test split, so the
  incumbent never sees test games. If that fails, the result is `kept`, with reason `overlap`.

**Promote only if all of these hold** (challenger c vs incumbent i, same test games, n ≥ 1,000):

| Check | Threshold |
|---|---|
| Log loss | c ≤ i − 0.0010 |
| Brier | c ≤ i + 0.0005 |
| ECE | c ≤ i + 0.010, and c ≤ 0.050 |
| Extreme predictions (≤10% or ≥90%) | c ≤ 1.0% |
| Probabilities | no NaN; `probability_std` of c within 0.5×–1.5× of i (guards against collapse) |

**When promoted:**
1. Back up the four artifacts to `data/backups/<UTC ts>/`.
2. Write the new files to temp and `os.replace` them under `data/model.lock`. Predict loads under the same lock.
3. Write the leaderboard and metadata, and publish `model_runs`.

**When kept:**
- The challenger and its full 6-model leaderboard go to `data/candidates/<UTC ts>/` with `decision.json`. Production files and
  `model_runs` stay untouched.
- If a **different** family beats production by this bar two weeks running, the notes say "family switch suggested". Only Noel
  can switch families.

**Always:**
- Write a `workflow_log` row `kind='retrain'` with notes like `promoted|kept: LL 0.6075→0.6061, Brier …, ECE …, n=…, reason`.
- The next morning SMS carries that line.
- Rollback: `python src\model.py --restore <ts>`.

### Morning plus pre-tip predictions (D2)

**Morning run (06:00):** as today, with `run_kind='morning'`. It writes `data/state/<date>.json` with the game IDs,
`tip_time_utc` for each game, and `first_tip_utc`.

**Pre-tip run:**
- Task `NBA-Predictor-PreTip` (S4U, wake) ticks every 15 min from 09:45 to 23:30.
- Each tick runs `daily_workflow.py --mode pretip`.
- It does nothing and exits 0 in under 2 s, with no Odds API call and no `workflow_log` row, if any of these is true:
  - no state file (one ScoreboardV3 call rebuilds it);
  - no eligible games;
  - today's `pretip_done` marker exists;
  - the time is outside the window [first tip − 75 min, first tip − 20 min].
- Inside the window it:
  1. takes an injury snapshot (a failure is logged, not fatal);
  2. runs `predict --run-kind pretip`, which costs 1 Odds credit;
  3. writes the marker;
  4. writes a `workflow_log` row `kind='pretip'`;
  5. sends an SMS **only if** a bet was placed, changed or cancelled.

**Locking and upserts:**
- One predictions row per `game_id`, upserted.
- A game whose `tip_time_utc` ≤ now + 10 min, or whose status isn't `scheduled`, is **locked**: it is never re-predicted or re-bet.
- An open game's bet fields are **overwritten, never added to**. A bet can be placed, resized or cancelled
  (`bet_amount` 0, `bet_placed` null).
- So each game's bet is the one from the last run before its tip.
- Every run appends to `prediction_runs` (including the price grid), so the morning-vs-pre-tip history survives for evaluation.
- Bankroll is recomputed from settled P/L only, so a resized bet can't double-count.

**Odds API budget:** 2 calls per game day, about 62 a month, plus a few dry runs. The free tier is 500 a month. The warning fires
below 50 remaining, and the go/no-go check needs ≥ 300.

## 3. Workstream B: player data (builds on the spec)

### 3.1 Corrections to the spec

- **Baseline:** use the GB numbers in §1.
- **Candidates:** GB + availability is the main candidate. Logistic + availability is a second candidate to attribute the gain.
- **Promotion is manual (D8):** an availability model changes the feature set, so it is **not** eligible for D1's auto-gate. It
  must clear all of these:
  - log loss improves by at least 0.002 on the 1,596-game test set;
  - Brier no worse;
  - ECE ≤ 0.040;
  - walk-forward wins in ≥ 4 of 6 seasons;
  - archive-replay results reported.
- **Migrations** go in `supabase/migrations/<timestamp>_name.sql`, using the timestamps pre-assigned in §4.
- **Phase 0 blockers are already resolved** (`…0200`, `…0300`, `…0400`, `…0500`), and `main` is the canonical branch. The probes
  are part of B1 and B2.
- **What the spec assumes but doesn't exist yet:**
  - `--morning`/`--predict` modes: A1 and A9 add `--mode morning|pretip|retrain`.
  - A 30-minute tick: B1 adds an hourly injury task, and A9 adds the pre-tip tick.
  - `src/config.py`: B1 creates it.
- **Progress tracking:** the spec's §1b checkpoint and report files are replaced by the process doc (§7).

### 3.2 Before the opener

1. **B1 injury archive: running by Fri Oct 9.**
   - History can't be recovered later, so B1 archives raw PDFs and parsed JSON to `data/raw/injuries/` from day one.
   - It loads that archive into `injury_snapshots` idempotently once Noel applies the migration.
   - B1 also probes whether past PDFs can be fetched. The plan doesn't count on it.
2. **B2 player box-score backfill:** spec phase 1 for 2019-20 to 2025-26. Raw data is cached in `data/raw/players/`, and
   `player_absences` is derived from it. Loading into the DB needs Noel's approval.
3. **B3 ratings backfill:** `box_value_v1` first, then `rapm_lite_v1` if time allows. It produces a weekly `as_of` series for each
   season, using only games strictly before `as_of`.
4. **B4 roster-based preseason Elo prior (stretch, research only):**
   - Judged on the first 3 weeks of 2020-21 through 2025-26 against 25% reversion. It also tries reversion of 0.33 and 0.40.
   - **Leakage trap:** past `CommonTeamRoster` data is the end-of-season roster. Use only players who appeared in the team's last
     10 games before the opener, plus moves dated before the opener.

### 3.3 In season (about 4–6 weeks in, Nov 16 – Dec 4)

- **B2b:** daily incremental box scores, wired into the pipeline.
- **B5:** minutes projections and availability features (spec phases 3–4).
- **B6:** walk-forward evaluation (spec phase 5).
- **B7:** predict-time integration behind `AVAILABILITY_ENABLED=false`, plus `src/betting.py` (spec phase 6).
- **B8:** API and contract (spec phase 7).

### 3.4 Train on realized absences, predict from the injury report

**The mismatch:**
- Training sees `p_play ∈ {0,1}` from realized absences.
- Live prediction sees report statuses, which miss late scratches and rest days.
- Without correction, the model over-trusts availability features and is overconfident on uncertain nights.

**What the plan does about it:**
1. **Scenario blending (spec §9.2) is the main fix.** The model is conditional on the lineup, so averaging its output over
   scenarios weighted by `p_play` gives the right expected probability, as long as `p_play` is calibrated.
2. **Calibrate `p_play`** from the B1 archive joined to realized absences once there are 30+ nights. "No report" gets a
   late-scratch rate for each player tier instead of 1.0. Until then, the spec's default map applies and is labelled uncalibrated.
3. **Match the timing (D2 shrinks the gap).** Live bets lock at the pre-tip run, about 1 hour before the first tip. So historical
   `as_of` stays at tip − 60 min, and archive replay uses the snapshot closest to the actual `prediction_runs.predicted_at`.
4. **Report two results.** Realized-absence backtests are an upper bound. The archive replay (30+ nights) is the live expectation,
   and D8 is judged on both.
5. **Deferred:** noise-injection training. Revisit only if (4) shows a log-loss gap above 0.003.

## 4. Work packages

**COMMON preamble.** Paste it above every builder brief and fill in the `<…>` fields.
```
You are a Sonnet builder on the NBA predictor (Windows; Git Bash; repo in your isolated worktree off season-2026-27).
Branch: <id>-<slug>. Python: C:\Users\noel9\Desktop\nba-predictor\venv\Scripts\python.exe (run from your worktree).
Read only: README.md, design/BACKEND_PLAN_2026-27.md sections <§>, and the files listed below. Don't explore beyond them.
Hard rules: no calls to Supabase, The Odds API or Twilio. NBA endpoints only if this brief allows them (at least 0.6 s apart,
cached to data/raw/). No DDL in Python; schema goes only in the migration file named here, unapplied. No real training runs, and
no writes to data/*.pkl, the leaderboard or the metadata. Never print .env values. force_utf8_stdio() stays first in __main__.
Nothing app.py imports may need more than requirements.txt. Pipeline steps exit non-zero on failure; DB-logging errors are
reported, not raised.
Finish: add tests, run `python -m unittest discover -s tests` (it must stay green; the baseline is 291+), commit with the attribution
line your environment specifies, and `git push -u origin <branch>`. Never push, merge or touch main.
Report (under 200 words): branch + SHA | files changed | tests run/passed + names of new tests | each acceptance item met/not met with
evidence | deviations | needs from Noel (migrations, live calls) | not verified.
```

| ID | Files (each owned by one package) | Depends on | Group |
|---|---|---|---|
| A1 | `scheduler/run_daily.bat`, `scheduler/task_scheduler_setup.ps1`, `scheduler/_task_common.ps1` (new), `scheduler/README_scheduler.md`, `daily_workflow.py`, `tests/test_daily_workflow.py` | none | P1 |
| A2 | `src/collect.py`, `tests/test_collect.py` | none | P1 |
| A3 | `src/odds.py`, `tests/test_odds.py` | none | P1 |
| A4 | `src/elo.py`, `tests/test_elo.py` (new) | none | P1 |
| B1 | `src/injuries.py`, `src/config.py`, `run_injuries.bat`, `scheduler/injuries_task_setup.ps1`, `requirements-pipeline.txt`, `.gitignore`, `supabase/migrations/20261008000100_injury_snapshots.sql`, `tests/test_injuries.py`, `tests/fixtures/injuries/` | A1's `_task_common.ps1` (B1 can stub it and rebase) | P1 |
| A5 | `src/features.py`, `src/predict.py`, `tests/test_features.py`, `tests/test_predict.py` (new) | A4 | P2 |
| A7 | `supabase/migrations/20261010000100_odds_quality.sql`, `app.py`, `tests/test_api_v2.py`, `tests/contract_shapes.py` | Noel's SQL | P2 |
| A8 | `src/model.py`, `src/retrain_gate.py` (new), `run_pipeline.bat`, `tests/test_retrain_gate.py` (new), `tests/test_model_publish.py` | none | P2 |
| B2 | `src/collect_players.py`, `src/absences.py`, `supabase/migrations/20261009000100_player_foundation.sql`, `tests/test_collect_players.py`, `tests/test_absences.py` | B1 (`.gitignore`, `config.py`) | P2 |
| A6 | `src/predict.py`, `src/track.py`, `tests/test_predict.py`, `tests/test_track.py`, `supabase/migrations/20261012000100_predictions_rerun.sql` | A3, A5 | P3 |
| B3 | `src/ratings.py`, `supabase/migrations/20261013000100_player_ratings.sql`, `tests/test_ratings.py` | B2 | P3 |
| A9 | `daily_workflow.py`, `run_retrain.bat`, `scheduler/pretip_task_setup.ps1`, `scheduler/retrain_task_setup.ps1`, `supabase/migrations/20261013000200_workflow_log_kinds.sql`, `tests/test_daily_workflow.py`, `tests/test_pretip.py` (new) | A1, A6, A8 | P4 |
| B4 | `scripts/eval_preseason_prior.py`, `tests/test_preseason_prior.py` | B3 | P4 (stretch) |

Run at most 5 builders at a time. Packages in the same group don't share files. A5 → A6 share `predict.py`, and A1 → A9 share
`daily_workflow.py`, so each pair runs in sequence. Run one group's gates while the next group builds.

### A1 scheduler and exit codes
```
Goal: the scheduled daily run actually runs, and fails loudly. Plan §2(a).
- run_daily.bat: create logs\ if missing; append to logs\workflow_YYYY-MM-DD.log; end with exit /b %ERRORLEVEL%.
- New scheduler/_task_common.ps1: New-NbaTask(name, triggers, argument, limit) using
  New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited, plus settings
  -WakeToRun -StartWhenAvailable -RestartCount 2 -RestartInterval 10min. Don't use -RunOnlyIfNetworkAvailable: Modern Standby
  wakes with the network off, so the script retries the network itself.
- task_scheduler_setup.ps1 uses it for NBA-Predictor-Daily at 06:00 with "--mode morning --trigger schedule", limit 2h.
- daily_workflow.py: argparse --mode {morning} (A9 adds the other modes), --no-sms, --trigger {schedule,manual}; kind='morning';
  print redact_secrets(output).
- README_scheduler: register / verify / unregister. Do NOT register tasks or run the workflow.
Tests: static bat and ps1 assertions (S4U, WakeToRun, exit /b); stdout redaction; --no-sms builds no Twilio client; a fake failing
step gives exit code 1; kind and trigger are within the workflow_log check constraint.
```
Acceptance: as in §2(a).

### A2 collect: season roll-over and loud failures
```
Goal: collect 2026-27; never exit 0 when collection failed. Plan §2(d).
- current_season(today): October or later gives YYYY-(YY+1). Default run = current season; --backfill = 2019-20 through current.
- fetch_season raises CollectError after its retries. An empty successful response is valid ("0 rows, preseason?").
  __main__ exits 1 on CollectError.
Tests (fakes): 2026-09-30 gives 2025-26 and 2026-10-01 gives 2026-27; failure exits 1; empty-but-OK exits 0; the composite-PK
hint test still passes.
```

### A3 odds hardening
```
Goal: no silent odds failures, no in-play prices, no key leaks. Plan §2(d)(e).
- OddsError (message without the URL or key) on non-200 responses and on requests exceptions.
- Skip events with commence_time <= now+5min (clock injectable).
- Key by (home, away, commence date). Each entry also carries "books" {book: (home, away)} for PREFERRED_BOOKS and "commence_time".
- Log x-requests-remaining and warn below 50. Delete lines 75-76.
Tests (fake requests): 401, 429 and ConnectionError each raise with no key in str(err); started events dropped; repeat matchups kept;
the book grid.
```

### A4 Elo season reversion
```
Goal: predict-time Elo equals what training assigns. Plan §2(b).
- Pure replay(games) -> (records, final_ratings, last_season_by_team), used by compute_elo and get_current_ratings(season=None).
  The latter reverts teams whose last season < target (target inferred from today). WL null never updates.
Tests in a new tests/test_elo.py on a two-season fixture: first new-season predict-time Elo == stored pre-game Elo; mid-season
unchanged; WL null ignored; compute_elo output identical.
```

### B1 injury archive (start day 1)
```
Goal: archive every official NBA injury report from now on; disk first, DB later. Plan §3.2(1), spec §5.
Probe (NBA site, max 10 requests, throttled): current URL pattern and cadence, whether past PDFs are fetchable, whether preseason
reports exist.
- src/injuries.py --snapshot saves PDF + parsed JSON + manifest to data/raw/injuries/YYYY-MM-DD/, idempotent per report_time.
  pdfplumber, pinned. STATUS_MAP lives in the new src/config.py. Keep player_name_raw.
- --load replays the archive into injury_snapshots (append-only; unique on source, report_time, team, name_raw). If the table is
  missing, print the migration name and exit 0.
- run_injuries.bat + scheduler/injuries_task_setup.ps1 (dot-source _task_common.ps1; hourly 09:00-23:00). A failed tick exits 1.
- Write the migration file, unapplied.
Tests: status normalization; parser on 2 recorded PDFs; idempotent re-snapshot; --load against the fake DB.
```
Acceptance: the fixtures parse to rows with correct statuses, a re-run adds nothing, `data/raw/` is git-ignored, and the probe
findings are reported. After the task is registered, `data/raw/injuries/` grows within 2 hours.

### A5 predict feature parity
```
Goal: predict-time features built by the same code as training. Plan §2(c). The leakage rules are non-negotiable.
- features.py: pure build_feature_frame(games, elo, upcoming=None); run() calls it, and the stored output is unchanged.
- predict.py: append tonight's unplayed games to the history from `games`, build them, use Elo from get_current_ratings().
  Missing history or Elo -> skip with reason "missing_data" (A6 persists it) and a loud print.
Don't change the training definition (rolling within role).
Tests: parity on 20 fixture games (1e-9); leakage (mutating same-day or later games changes nothing); rest days across roles;
stored features frame identical before and after.
```

### A7 suspect historical odds
The orchestrator first sends Noel this read-only SQL for the Supabase SQL editor:
`select count(*) filter (where odds >= 500 or odds <= -500), count(*) filter (where bookmaker is null), count(*) from predictions where season = '2025-26';`
```
Goal: past nights stop showing fake edges (D3: flag, hide edges, keep P/L). Plan §2(e). Noel's counts: <paste>.
- Migration 20261010000100_odds_quality.sql: predictions.odds_quality text default 'ok' with a check constraint (ok, suspect,
  unverified); an idempotent update sets suspect (odds >= 500 or <= -500) and unverified (no bookmaker, season 2025-26, not suspect).
- app.py: prediction_edge returns None unless odds_quality is ok or missing (safe before the migration); expose odds_quality
  (additive, nullable); exclude flagged rows from top_edges, the edge buckets and the Model walkthrough. P/L unchanged.
- Update contract_shapes.
Tests: each consumer with a flagged row; a row without the column behaves as before; the contract shape.
```
Acceptance: the tests pass, and a Playwright check (§6) is required.

### A8 weekly retrain gate (D1)
```
Goal: production artifacts change only through the weekly gate. Plan §2(h), §2.1 "Weekly auto-gated retrain".
- run_pipeline.bat: remove model from the daily loop.
- New src/retrain_gate.py: pure decide(incumbent_metrics, challenger_metrics, incumbent_cutoff, test_start) ->
  {decision: promoted|kept, reasons[], deltas}, using the §2.1 thresholds as named constants.
- model.py --weekly-gate: fit the challenger (NBA_PRODUCTION_MODEL family) plus the other candidates for the report; score the
  incumbent artifacts on the same test split; decide. If promoted: back up to data/backups/<ts>/, atomic os.replace under
  data/model.lock, write the leaderboard and metadata, publish_model_run(). If kept: write to data/candidates/<ts>/ only.
  Always print one line "RETRAIN_DECISION {json}". Also --dry-run (decide, no swap) and --restore <ts>.
- predict's artifact load takes the same lock (shared helper in model_metadata.py or a tiny new module).
Tests (synthetic metrics only, never a real fit): each threshold boundary (promote, and keep on log loss, Brier, ECE, extreme,
std, n<1000, overlap); backup happens before replace (fake fs); kept leaves production files and model_runs untouched;
--restore round-trip; the bat no longer lists model.
```
Acceptance: the orchestrator reads `decide()` against the §2.1 table line by line, and reruns the gate tests.

### B2 player foundation
```
Goal: spec phase 1 tables, backfill and absences, built offline first. Plan §3.2(2), spec §4 (use supabase/migrations with
timestamp 20261009000100). NBA allowed: LeagueGameLog in P mode per season (7 calls) plus 3 probe calls (BoxScoreTraditionalV3
DNP comment, CommonAllPlayers); cache to data/raw/players/.
- collect_players.py --backfill (cache -> frame -> upsert via database.py) and --load-only; absences.py (spec rules, config in
  src/config.py). Don't wire into run_pipeline.bat.
Tests: the spec §4 list. Report row counts per season, reconciled against games (two teams per game).
```

### A6 predict v2 writes, re-predict and locking (D2)
```
Goal: every v2 column filled; idempotent per game_id; morning/pre-tip safe. Plan §2(e)(f)(g), §2.1 "Morning plus pre-tip".
- predict.py --run-kind {morning,pretip,manual}; keep game IDs 002/004/005 only.
- Upsert predictions on game_id with model_name, predicted_at, tip_time_utc (ScoreboardV3 gameTimeUTC), season, bookmaker,
  implied_prob, edge, bankroll_at_bet, kelly_full, kelly_fraction, run_kind; first_predicted_at set once. Upsert book_odds on
  (game_id, bookmaker). Append prediction_runs (with the books grid).
- Lock: never touch a row whose tip_time_utc <= now+10min or whose status != scheduled (skip_reason 'started' only when no row
  exists yet). Bet fields are overwritten (place / resize / cancel), never added to.
- Skip rows: no_odds, missing_data, odds_suspect (|prob-implied| > 0.30), started.
- The morning run writes data/state/<date>.json (game ids, tip_time_utc, first_tip_utc).
- track.update_results sets status final/postponed and the scores.
- Migration 20261012000100_predictions_rerun.sql: extend predictions_skip_reason_chk (+odds_suspect, started); add run_kind (check
  morning|pretip|manual) and first_predicted_at; create prediction_runs (identity PK, game_id, run_kind, predicted_at,
  home_win_prob, pick, odds, bookmaker, implied_prob, edge, bet_amount, books jsonb, model_name; unique (game_id, run_kind,
  predicted_at); RLS on like book_odds). Idempotent.
Tests (fake DB, injectable clock): a predict+settle cycle fills every column contract_shapes reads; running morning twice = one
row, one bet; pretip resizes/cancels an open bet without a second bet; a started game is never re-predicted or re-bet;
preseason IDs ignored; each skip reason; Kelly example (bankroll 1111.67, p 0.61, -105 -> 55.58).
```
Acceptance: the orchestrator reruns the idempotency, no-duplicate and started-game tests, and checks the diff for edges computed
from a missing price.

### B3 ratings backfill
```
Goal: point-in-time player ratings for 2019-20 to 2025-26. Plan §3.2(3), spec §6, ratings half only.
- src/ratings.py: box_value_v1 (required), rapm_lite_v1 (if time allows), weekly as_of refit from the B2 cache; write
  data/raw/ratings/ and --load into player_ratings (migration 20261013000100, unapplied).
Tests: ridge recovers synthetic effects; ratings at as_of use no games on or after as_of; low-minute shrinkage.
```

### A9 workflow modes and the pre-tip and retrain tasks (D1, D2)
```
Goal: run the morning, pre-tip and retrain modes on schedule. Plan §2.1.
- daily_workflow.py --mode {morning,pretip,retrain}.
  - pretip: read data/state/<date>.json (or one ScoreboardV3 call); exit 0 fast with no Odds call and no log row outside
    [first_tip-75min, first_tip-20min], when the marker exists, or when there are no eligible games. Inside the window:
    injuries --snapshot (non-fatal) -> run_predict.bat with --run-kind pretip -> marker -> workflow_log kind='pretip' ->
    SMS only on bet changes.
  - retrain: collect, elo, features, model --weekly-gate; parse RETRAIN_DECISION; workflow_log kind='retrain' with metrics.
  - morning SMS appends the latest retrain decision line.
- run_retrain.bat; scheduler/pretip_task_setup.ps1 (every 15 min, 09:45-23:30, limit 30 min) and retrain_task_setup.ps1
  (Mon 03:00, limit 2h45m), both via _task_common.ps1.
- Migration 20261013000200_workflow_log_kinds.sql: extend the kind check with pretip and retrain (idempotent).
Tests (fake clock, fake bats): window edges (-76, -75, -20, -19 min); the marker prevents a second run; no Odds call outside the
window; SMS only on change; retrain notes parsed; a failed step -> exit 1.
```

### B4 preseason prior (stretch)
```
Goal: research whether a roster-based prior beats 25% reversion on season openers. Plan §3.2(4). No production change, no DB
writes, no training of the production model. Elo-only win probability per season (first 3 weeks): log loss and Brier for
reversion 0.25/0.33/0.40 and prior weights 0.25/0.5. Test: the point-in-time roster uses only games before the opener.
```

### In-season packages (briefs written at the time from the spec)

| ID | Spec phase | Starts | Key acceptance |
|---|---|---|---|
| B2b | phase 1, daily incremental + wiring | Oct 26 | idempotent; fails loudly |
| B5 | phases 3 (minutes) + 4 | Nov 2 | `as_of` leakage guard; minutes sum to 240 |
| B6 | phase 5 | Nov 16 | D8 on the test set, walk-forward and archive replay |
| B7 | phase 6 + `betting.py` | after B6 | flag off leaves predictions byte-identical; scenario blending at the pre-tip run |
| B8 | phase 7 | after B7 | contract tests; Playwright check |

## 5. Schedule to opening night (Tue Oct 20)

Hours are builder-hours. Each gate adds about 1–2 h. Noel's approval windows are the real constraint.

| Day | Orchestrator / builders | Noel |
|---|---|---|
| Thu Oct 8 | Create `season-2026-27` and the process doc. Spawn P1: A1 (3h), A2 (2h), A3 (3h), A4 (3h), B1 (5h) | Run the A7 SQL |
| Fri Oct 9 | P1 gates; merge P1 into the integration branch. Spawn P2: A5 (5h), A7 (3h), A8 (5h), B2 (5h) | Apply `…injury_snapshots`; admin steps 1–3 and the injury task (§5.1). **B1 live** |
| Sat–Sun Oct 10–11 | P2 gates; A7 Playwright check. Spawn A6 (7h) on Sunday once A5 is merged | Apply `…player_foundation`; approve the B2 load |
| Mon Oct 12 | A6 builds; spawn B3 (6h) | |
| Tue Oct 13 | A6 gates; spawn A9 (6h) | Apply `…odds_quality` and `…predictions_rerun` |
| Wed Oct 14 | **Batch 1 to `main`** (A1–A8, B1, B2); B3 gate; A9 builds | Approve the merge; deploy production from the main SHA (A7 changed `app.py`); production Playwright re-check |
| Thu Oct 15 | **Dry run (DR):** `daily_workflow.py --mode morning --no-sms --trigger manual` from the main checkout. Expect 0 new games collected, preseason ignored, 1 Odds credit used, exit 0. A9 gates | Approve the live run; register the daily task (admin step 4) |
| Fri Oct 16 | Fix anything the dry run found; spawn B4 (stretch). From here the daily SMS is a heartbeat | Apply `…workflow_log_kinds` |
| Sat–Sun Oct 17–18 | **Batch 2 to `main`** (A9, B3, fixes). Watch the pre-tip ticks on a no-game day: they must exit 0 with no Odds call | Approve batch 2; register the pre-tip and retrain tasks (admin step 5) |
| Mon Oct 19 | **Go/no-go at 20:00** | |
| Tue Oct 20 | 06:00 morning run; the pre-tip run about 1h before the first tip. Check rows, `prediction_runs` and the SMS | |
| Wed Oct 21 | First settle: status, scores, bankroll; spot-check A4's Elo for one opener | |
| Sun Oct 25 | `model.py --weekly-gate --dry-run`, watched | Approve the live training run |
| Mon Oct 26 | 03:00, the first gated retrain; the decision line is in the 06:00 SMS | Read it |

**Critical paths:**
- **Opener (morning run):** A4 → A5 → A6 (needs A3) → batch 1 → dry run → daily task. That's about 15 builder-hours plus 4 gates,
  plus Noel's approvals on Oct 13–15.
- **Pre-tip run:** A6 → A9 → batch 2 → pre-tip task. Slack is about 1 day.
- **B1** isn't on the opener path, but it's the most urgent work: every day it isn't running loses data for good.

**Go/no-go checklist (Mon Oct 19):**
- The suite is green on `main`.
- The dry-run `workflow_log` row reads success.
- The daily, pre-tip, retrain and injury tasks are registered as S4U with WakeToRun.
- The daily task's `LastTaskResult` is 0.
- `data/raw/injuries/` is growing.
- The opener's IDs start with `002`.
- A4's parity test passes.
- The pre-tip ticks on Mon Oct 19 exited 0 with no Odds calls.
- At least 300 Odds requests remain.

**If time runs short, cut in this order:**
1. B4.
2. `rapm_lite_v1`.
3. The B3 DB load.
4. A7 (history display only; it can ship in week 1).
5. A9's retrain mode and task (not needed until Oct 26).
6. **A9's pre-tip mode.** Opening night then runs on the morning predictions alone, and pre-tip ships in week 1. The morning bets
   stand either way, so a missing or failed pre-tip run is safe.
7. A6's `book_odds` grid and `kelly_*` columns.

**Never cut:**
- A1–A5.
- A6's upsert, lock and preseason guard.
- A8's removal of the daily retrain (it must be in batch 1).
- B1.

If A5 slips past Oct 16, run the opener anyway. The known cost is home-only stats that are one game stale.

### 5.1 One-time admin setup (Noel, D5)

1. **Power.** This laptop uses Modern Standby (S0, network disconnected when asleep), so wake timers aren't fully reliable.
   - In an Administrator PowerShell, keep it awake on AC for the season: `powercfg /change standby-timeout-ac 0`.
   - Enable wake timers on AC and battery:
     `powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1`, then
     `powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1`, then
     `powercfg /setactive SCHEME_CURRENT`.
   - Leave it plugged in.
2. **Update the code.** `cd C:\Users\noel9\Desktop\nba-predictor`, then `git pull` on `main` after the batch merge.
3. **Injury task (Oct 9, from the merged integration build).**
   `powershell -ExecutionPolicy Bypass -File scheduler\injuries_task_setup.ps1`
4. **Daily task (Oct 15, after the dry run).**
   `powershell -ExecutionPolicy Bypass -File scheduler\task_scheduler_setup.ps1`
5. **Pre-tip and retrain tasks (after batch 2).** Run the same command with `scheduler\pretip_task_setup.ps1`, then with
   `scheduler\retrain_task_setup.ps1`.
6. **Verify.**
   - `Get-ScheduledTask -TaskName 'NBA-Predictor-*' | ft TaskName,State,@{n='Logon';e={$_.Principal.LogonType}},@{n='Wake';e={$_.Settings.WakeToRun}}`
     should show S4U and True for every task.
   - `powercfg /waketimers` lists the next wake.
   - After the first run, `Get-ScheduledTaskInfo NBA-Predictor-Daily` should show `LastTaskResult` 0.
7. **Rollback.** `Unregister-ScheduledTask -TaskName <name> -Confirm:$false`. S4U stores no password, so there's nothing to rotate.

## 6. Gates and approval

**Per package, in order:**
1. A Sonnet builder builds it.
2. A Sonnet `/security-review` subagent reviews the branch diff against `season-2026-27`.
3. If `app.py`, `public/`, `templates/` or the contract changed (A7, B8), a Sonnet Playwright-CLI check of the Vercel preview runs
   at 1440 and 400 px: `/`, `/model`, one drawer, one past night, the console, and 4xx/5xx responses. The preview is behind SSO,
   so use Noel's existing authenticated method.
4. Orchestrator approval.
5. `--no-ff` merge into `season-2026-27`.

The orchestrator spawns every builder, reviewer and Playwright agent.

**Noel's rules:**
- No merge into `main`, no push to `main`, and no production deploy without Noel's approval.
- Migrations are files only. Noel applies them by hand, in timestamp order.
- Production deploys are manual: create the deployment from the main SHA.
- Production stays behind Vercel SSO.
- Live Odds API, Twilio, production-DB write, backfill or real training runs each need Noel's approval at the time. The
  scheduled tasks are pre-approved once Noel registers them.

**What the orchestrator verifies itself:**
- It reads the whole non-test diff and the new tests' assertions.
- It reruns the suite in the branch worktree and compares the test count with the last recorded count.
- **Leakage and parity (A4, A5, B2, B3, B5, B6):** it reruns the tests by name and confirms they assert strictly-before.
- **Gate logic (A8):** it checks `decide()` against the §2.1 table and reruns the boundary tests.
- **Bet safety (A6, A9):** it reruns the idempotent re-predict, no-duplicate-bet, started-game and window-edge tests.
- **Diff greps:** DDL in `.py`; `print(` near env or key values; heavy imports in `app.py`; `except Exception: pass`; exit 0 after
  a failure.
- **Migrations:** the timestamp matches §4, the SQL is idempotent, and nothing has been applied.
- **Metrics:** for A8's first live decision and for B6, it recomputes the numbers against the GB baseline in §1.

**What it trusts from reports:**
- Live-probe shapes (B1, B2).
- Backfill counts. Noel's SQL checks them later.
- Playwright findings. It reads anything rated medium or higher.
- A security reviewer's "no confirmed findings". Any confirmed finding is read in full and sent back to the builder.

**Rejection:** send one consolidated fix list to the same builder. After 2 rounds, the orchestrator decides or escalates to Noel.

## 7. Process doc and resume ("Continue")

On day 1 the orchestrator creates `design/backend/PROCESS_2026-27.md` on `season-2026-27`. After every gate it **rewrites** the
file (it doesn't append to it) and commits.
```
Resume here: <next action + who is waiting on whom>
Opener: Tue Oct 20 (Noel) | Integration HEAD: <sha> | main: <sha> | Suite: <N> OK
Packages: ID | branch | SHA | build | security | playwright | approved | merged-int | in-main      (todo/doing/done/blocked/n-a)
Noel queue: migrations to apply (in order) | live calls awaiting approval | merges/deploys awaiting | admin steps (§5.1) done
Live checks: injury last file <time> | daily/pretip/retrain LastTaskResult | Odds requests remaining <n> | last retrain decision
Log (last 10 gates): <date> <ID> <gate> <result> <1-line reason>
```

**On "Continue":**
1. Read the process doc and §4–§6 of this plan.
2. Run `git worktree list`, `git log --oneline -5 season-2026-27` and `git branch -r`.
3. If the repo and the doc disagree, trust the repo and fix the doc.
4. Re-spawn only packages marked `doing` that have no pushed SHA. Everything else resumes at its next gate.

**Token discipline:**
- Each brief is COMMON plus the package's own block. Don't paste plan sections; refer to them.
- One report per package, under 200 words.
- The orchestrator reads diffs and tests, not files a builder has already summarized.
- Reviewer and Playwright agents get the branch name and a 3-line scope, not the plan.

## 8. Risks

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| Laptop asleep at run time (Modern Standby; network is off when it wakes) | High / missed runs | Never sleep on AC, wake timers on, no `RunOnlyIfNetworkAvailable` plus network retries, `StartWhenAvailable` catch-up; the SMS is a heartbeat |
| The gate promotes a model that only won by noise | Medium / slightly worse live model | 0.001 log-loss margin, Brier and ECE guards, same family only, backups, `--restore`, the decision in the SMS |
| Retrain overlaps the 06:00 run | Low / torn artifacts | 03:00 start, 2h45m limit, lock plus atomic replace. Real training time is **not measured**: check it on Oct 25 |
| Pre-tip changes erase the morning record | Medium / evaluation gaps | `prediction_runs` is append-only, and `first_predicted_at` is kept |
| Pre-tip window missed (laptop off, PDF slow) | Medium / morning bets stand | Safe default: morning bets remain; the miss shows in `workflow_log` |
| The injury PDF format or URL changes | Medium / archive gap | Raw PDFs are kept; a failed tick exits 1; the orchestrator checks the archive daily in week 1 |
| stats.nba.com rate-limits or blocks | Medium / collect fails | A2 fails loudly; throttling; cached backfills |
| The Odds API quota | Low | About 62 calls a month against a 500 free tier; warning below 50 |
| Thin opener-week features | Certain / weaker early picks | They match training (parity); B4 researches a prior |
| Supabase free-tier size | Low | About 190k `player_games` rows, about 40k snapshots a season, and `prediction_runs` about 2.5k |

## 9. Decisions (Oct 7, Noel)

- **D1, retraining:** weekly and auto-gated, not frozen. The daily run stops training. Thresholds and mechanics are in §2.1, and
  the work is in A8 + A9. Only same-family swaps are automatic; a family switch, or any change to the feature set, stays manual (D8).
- **D2, predict runs:** a morning run plus one pre-tip run about 1h before the first tip (time from `tip_time_utc`). A game's bet
  locks at the last run before its tip. Predictions are upserted per `game_id`, with no double bets and no bets on started games.
  The budget is 2 Odds calls per game day. Details in §2.1, the work in A6 + A9.
- **D3, suspect odds:** flag them, hide their edges, keep P/L as recorded (A7).
- **D4, merges:** two batches into `main`, around Oct 14 and Oct 19 (planned for Wed Oct 14 and Sat–Sun Oct 17–18).
- **D5, scheduling:** tasks run while Noel is logged off (S4U) and wake the PC. Noel does the one-time admin setup in §5.1.

**Still open (the default applies unless Noel objects):**
- **D6:** injury reports come from the official NBA PDF, parsed with `pdfplumber`.
- **D7:** the preseason prior is research only for the opener.
- **D8:** availability-model promotion uses the manual rule in §3.1.
- **D9:** keep a single running bankroll ledger into 2026-27.
- **D10:** predict the play-in (`005`).
- **New, D11:** a pre-tip SMS goes out only when a bet changes.

## 10. Deliberately left out

- **Spec phase 8 (props) and the spec's API phase before B7.**
- **Retraining before the opener.** The Oct 7 GB model stays live until the Oct 26 gate.
- **All-games rolling windows and noise-injection training.** Both are in-season candidates that go through D8.
- **More than one pre-tip run a day, or a run per tip.** That would double the Odds API usage. Revisit with B7's data.
- **Moving the scheduler off the laptop.**
- **The `nba_api` pin in `requirements.txt`.** It's probably used by `live_scores`. Not verified, and not a blocker.
- **Not verified:**
  - that production Supabase has the same suspect rows (A7's SQL settles this);
  - the in-play-price hypothesis in (e);
  - whether past injury PDFs can still be fetched (B1);
  - how long a full weekly retrain takes;
  - whether Modern Standby wake timers fire on this laptop (§5.1 avoids depending on them while it's on AC).
