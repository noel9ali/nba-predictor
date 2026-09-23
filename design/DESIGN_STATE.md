# NBA Predictor dashboard: design state and backend requirements

Status as of Sept 22, 2026. Rounds 1–7 are approved. Mobile (Round 8) is on hold. Logo source (Round 9) is still open.
Canvas: https://claude.ai/code/artifact/a702b1d5-c99f-4bf4-b134-aa7cb93049c2
Decisions log (Claude project): `claude/design-session-decisions.md`

This file replaces the conversation as the source of truth. The final `DESIGN_SPEC.md` and `BUILD_PLAN.md` will be built from it.

---

## 1. Approved design

### Visual tokens

| Token | Value | Use |
|---|---|---|
| bg | `#0a1630` | page |
| panel | `#102244` | cards, tiles |
| deep | `#0d1d3b` | card footers, inputs, tooltips |
| divider | `#1d3461` | 2px gaps between tiles, hairlines, grid |
| edge | `#3a5185` | outline chips, neutral bars |
| accent | `#ffc72c` | brand block, pick, bet placed, bet-price cell, section heads |
| muted | `#b7c4dd` | secondary text |
| win | `#3ee08f` | hit, positive P/L |
| loss | `#ff8a95` | miss, negative P/L |
| live | `#d62839` | LIVE chip, live card top bar |
| dim score | `#7f8fb0` | trailing team's score |

- **Type:** Barlow Condensed 600–800, uppercase, for display text, numbers and labels; Barlow 400–600 for body text.
- **Shape:** square edges.
- **Spacing:** tiles sit in 2px `divider` gaps; sections are 24–28px apart; desktop page padding is 48px; artboards are 1440 wide.
- **Numbers:** use tabular figures in columns and tables only; big hero figures use proportional figures.
- **Green and red** fail red-green colorblind separation (deutan ΔE 3.5). Every P/L carries a +/− sign, and every Hit/Miss carries a text label. Bars grow left or right from zero, so color is never the only cue.
- **Touch targets** are at least 44px. Icon-only buttons have an `aria-label`. Toasts are announced with `role="status"`. The drawer traps focus and closes on Esc.
- **Motion:** 300ms cross-fade for the hero hand-off, and a 10s outline flash at tip-off and at the final buzzer. With `prefers-reduced-motion`, there's no flash, only the toast.

### Site map (Round 3)

- **Tabs:** two tabs, **Games** and **Performance**.
- **Game detail:** a **drawer** (620px, right side) with its own link (`#game/<game_id>`). It opens from Games cards, Last night rows, the night recap and Performance log rows.
- **Past nights:** these live inside Games (see Round 4). There is no separate history page.
- **Model:** a strip inside Performance. The model leaderboard page is deferred.
- **System:** there is no page. A pipeline pill plus a popover sits in the top bar.
- **Audience:** Noel plus **public viewers**. Everything is read-only except for Run now / Retry, which only show on the computer that runs Flask.

### Top bar (every page)

- **Left:** the brand block and a "Paper trading" tag, then the Games | Performance tabs.
- **Right:**
  - refresh status (Games tonight only)
  - the pipeline pill: OK · 6:02 AM, running, failed, or no run today
  - a "Sample data" tag, only in design and sample builds
- **Popover views:**
  - local: last runs plus a **Run now** button
  - running: the button is disabled and shows the elapsed time
  - failed: a **Retry** button
  - public: read-only, no buttons

### Games page (Round 2 draft plus Rounds 4–6)

**Tonight**

- **Header:** the "Tonight's slate" title, the date, counts (final / live / upcoming) and a **Past nights** button. Stat tiles: Bets placed, Total staked, Settled P/L, Live picks ahead.
- **Hero, "Next up · biggest edge":** the unstarted game with a placed bet and the biggest edge. It hands off at each tip-off with a cross-fade, and shows a countdown in the last hour.
  - When every bet has tipped off, it becomes **"Tonight so far"**: settled P/L and record, money still open, open picks ahead, "if it ended now", and a list of open bets.
  - When every game is final, it becomes the **tonight recap**, tagged "Unofficial until the 6 AM run".
  - With no bets on the slate, it shows **"No bets tonight"** plus the game that came closest to a bet.
- **All games:**
  - **Toolbar:** filter tabs with counts (All / Bets / Live / Upcoming / Final) and sort tabs (Tip-off, the default / Edge / Bet size). A filter with no matches shows an empty state with "Show all games".
  - **Layout:** 2-up cards in tip-off order. Cards never reorder when their state changes.
  - **Card:**
    - a status chip and the pregame edge
    - a Details › button; the whole card also opens the drawer
    - one row per team: logo, abbreviation and name, record, L10 strip, pregame %, score
    - the "Odds at time of bet" 5-book grid: the price taken is filled yellow, and the other side's best price has yellow text
    - a footer with the pick, odds, book, live margin or final result, and the bet tag
  - **Bet tag:** "Placed $X" with a lock while open, "Hit +$X" / "Miss −$X" once final (tagged unofficial until the 6 AM run), or "No bet placed".
- **Card edge cases:**
  - overtime clock (OT, 2OT) and Final/OT
  - **postponed:** the bet shows "Void · $X returned"
  - some books with no price: a dash, and the best price comes from the rest
  - **no odds:** the model still picks, with a "No odds · no bet" tag
  - missing team data: same as no odds, with a different reason
  - live with no score in the feed: shows "—"
- **Last night:** rows plus a summary, with an "All past nights ›" link.
- **Explainers:** an info button next to Pregame win prob, Odds taken (implied probability), Edge and Bet placed opens a popover with this game's numbers worked through. Only one is open at a time.
- **Refresh:**
  - polls every 30s while any game is live, with a manual refresh button
  - "Refreshing…" while a poll is in flight
  - **stale** after 2 failed polls: "Scores delayed · last update HH:MM", a Retry button, and live chips lose their fill and show "as of HH:MM"
  - a **feed-down banner** after 5 minutes
  - "All games final · updates stopped" at the end of the night
- **Toasts:** at tip-off ("X is live · moved to All games; Y is next up") and at the final buzzer ("SAC 118, GSW 110. Bet hit, +$52.93. Settled P/L now …").

**Past night** (from Past nights, All past nights, the rail or a Performance timeline click)

- The **date rail** shows only here: 7 past days, each with its pick record and P/L, a red-topped "Tonight" cell, an earlier-days arrow and a date picker.
- The title becomes the date, with a yellow "Back to tonight" button.
- The hero becomes the **night recap**: net P/L, bankroll before → after, picks and bets records, staked, ROI, and the best and worst bet.
- Cards show final scores, and there is no Last night section.

**Page states**

- **Before the prediction run:** schedule only, with the message "Picks post an hour before the first tip · Prediction run 6:00 PM".
- **Prediction run failed:** a red banner (Retry in the local view only). Scores keep updating.
- **No games (offseason, All-Star break):** a "No games tonight" / "Offseason" page with links to Season performance and the last slate. Offseason is today's real state.

### Game detail drawer (Round 5: option A now, option B later)

- **Header:** status chip, close button, and the matchup with logos, sides and records.
- **Win probability:** the pregame probability bar, with a yellow mark where the bet price's implied probability sits.
- **Summary tiles:** Pick, Odds · book, Edge, Bet placed.
- **Tale of the tape:** both teams side by side with a split bar each for:
  - Elo and rest days
  - last-10 points, FG%, rebounds, assists, turnovers (lower is better) and stocks

  The better side is shown in yellow.
- **Odds at time of bet:** the 5-book grid.
- **Footer:** "Predicted <time> · <model>", and the result after the final.
- **Later, option B ("Why the pick"):** starts from the 55.0% home-win base rate and adds each factor's contribution in probability points. This needs per-prediction contributions stored.

### Performance page (Round 7: option C, refined)

- **Header:** the title and a season picker (2025–26 / 2024–25 / All seasons).
- **Scorebug:** Bankroll (yellow cell, with "+$X since <season start>"), ROI, Bet record, Pick accuracy.
- **Season timeline:**
  - the bankroll line (yellow, 10% area fill, $1,000 start line, peak marked, max drawdown shaded and bracketed)
  - nightly P/L columns on the **same date axis** (two charts, never one chart with two axes)
  - a W/L strip for the last ~33 bets
  - a risk line: max drawdown with dates, and the longest win and losing streaks
  - **interaction:** hover or arrow keys move a crosshair through both charts; the tooltip shows the date, bankroll, nightly P/L, bets W–L and picks W–L; clicking opens that night on Games
- **Box score table:** grouped by book, by confidence bucket (high 65%+, medium 58–65%, low under 58%) and by edge size (0–3, 3–6, 6–10, 10%+). Columns: Bets, W–L, Staked, P/L, ROI.
- **Model strip:**
  - the live model (read from `production_model`) and when it was trained
  - test accuracy with the number of test games
  - accuracy this season with the number of picks
  - Brier score
  - a calibration mini-chart (actual vs. predicted by probability bucket)
- **Prediction log:**
  - **filters:** team text, All picks / Bets only (all picks is the default), result (Any / Hit / Miss / Pending), book, minimum edge
  - **columns:** Date, Matchup, Pick · pregame %, Odds · book, Edge, Bet, Result, P/L
  - newest first, 25 per page; a row opens the drawer
- **Empty states:** early season with nothing settled yet, and log filters with no match.

### Sample data fixes for the build

- The SAC bet is **$55.58**, not $59.38: quarter-Kelly is 5.0%, and it's capped at 5% of $1,111.67. The SAC hit pays +$52.93.
- In Last night, TOR is a no-bet at −150 (edge −2.0%).
- The sample season runs Oct 21 – Nov 16 and ends at $1,111.67 bankroll, $4,275.40 staked, bets 54–41, picks 124–65. The rail, the recap and Performance all agree.

### Deferred or open

- **Mobile (on hold):** needs phone versions of Games and Performance, plus how the 2-up cards, 5-book grid, drawer and timeline collapse.
- **Logo source (open):** a local folder vs. an image link pattern, files named by tricode, and a fallback (the team-color circle with the tricode that the placeholders already use).
- **Open questions:**
  - How public viewers reach the site: Flask exposed from the laptop, a hosted server, or a static snapshot. This decides how Run now is locked.
  - Which worktree is canonical for the model. `model_metadata.json` only exists in `nba-model-integration-lstm-gb-rf`.
- **Model leaderboard page:** deferred.
- **Drawer option B:** deferred.

---

## 2. What the current backend has (verified)

- **Flask routes:** `/`, `/api/dashboard-state`, `/api/ytd-summary`, `/api/recommendations` and `/api/bankroll-series`. All filter by **calendar year** (`substr(game_date,1,4)`). `details{}` in recommendations has Elo plus rolling PTS, FG%, REB, AST, TOV and STOCKS per side, but **no rest days**.
- **Tables:**
  - `predictions` (game_id, game_date, home_team, away_team, home_win_prob, away_win_prob, predicted_winner, actual_winner, correct, bet_placed [team TEXT], bet_amount, odds, profit_loss)
  - `bankroll` (date, balance)
  - `workflow_log` (id, run_date, started_at, finished_at, status, pipeline_ok, predict_ok, sms_sent, notes)
  - `games`: leaguegamefinder rows, one per team per game, with `SEASON` like '2025-26' and WL. It covers 2019-10-22 to 2026-04-12, 16,578 rows.
  - `features`: HOME_/AWAY_ columns plus roll_* columns
  - `elo` (GAME_ID, GAME_DATE, HOME_TEAM_ID, AWAY_TEAM_ID, HOME_ELO, AWAY_ELO, ELO_DIFF)
- **Data gaps:**
  - The model worktree's `data/nba.db` has **no** predictions or bankroll tables yet.
  - The frontend worktree has no `data/` folder.
- **`odds.py`:** keeps only the single best price per side, plus the book. There's an unused `bookmaker = game['bookmakers'][0]` line and two `if __name__ == '__main__'` blocks.
- **`predict.py`:** `continue`s past games with no odds or missing team data, so they never get logged. It doesn't store the bookmaker, edge, implied probability, bankroll at bet time, tip time or model name. `game_date = date.today()`.
- **`track.py`:**
  - quarter-Kelly with a 5% cap, both hard-coded
  - `update_results()` settles yesterday only
  - games missing from the scoreboard stay pending forever, so postponed games are never handled
  - it doesn't save final scores
- **Scheduling:** one Task Scheduler job at 6:00 AM runs `daily_workflow.py` (the full pipeline, predictions and SMS). `run_predict.bat` is manual and ends in `pause`. `daily_workflow.py` mentions `POST /api/run-workflow` and has `run_workflow_async()` / `workflow_is_running()`, but **app.py has no such route**.
- **Model numbers:** `model_metadata.json` names `legacy-calibrated-logistic` as the production model. The leaderboard shows 68.2% accuracy, Brier 0.2089 and AUC 0.729 on 1,596 test games, with a 55.0% home-win base rate. The README's 71.1% isn't backed by the leaderboard.

---

## 3. Backend changes needed (the brief for the engineer agent)

The order follows dependencies. Items with the same number prefix can run in parallel.

1. **Config and data location.**
   - Read the DB path from `NBA_DB_PATH`, defaulting to `data/nba.db`.
   - Read the metadata and leaderboard paths from env, and document them.
   - Add `seed_sample_season.py` to build a labelled sample season DB for frontend work, since it's the offseason. Match the sample numbers in section 1.
2. **Schema migrations.** These must be idempotent and use `ALTER TABLE ... ADD COLUMN` guarded by a PRAGMA check.
   - `predictions` gains:
     - `season` TEXT
     - `tip_time_utc` TEXT
     - `bookmaker` TEXT
     - `implied_prob` REAL
     - `edge` REAL
     - `bankroll_at_bet` REAL
     - `kelly_full` REAL
     - `kelly_fraction` REAL
     - `model_name` TEXT
     - `predicted_at` TEXT
     - `status` TEXT: scheduled / final / postponed / void
     - `home_score` INT
     - `away_score` INT
     - `skip_reason` TEXT: NULL / no_odds / missing_data
   - New table `book_odds`: game_id, captured_at, bookmaker, home_price, away_price, UNIQUE (game_id, bookmaker).
   - `workflow_log` gains `kind` (morning / predict / manual), `trigger` (schedule / manual), `log_tail` TEXT.
   - Backfill `season` from `games.SEASON` by GAME_ID.
3. **odds.py.** Return every preferred book's prices per game, and derive the best price per side from those. Remove the dead code.
4. **predict.py.**
   - Log **every** game: set skip_reason for no odds or missing data, with bet_amount 0 and odds NULL.
   - Store bookmaker, implied probability, edge, bankroll at bet time, full Kelly, the fraction used, model name, predicted_at, tip_time_utc (from scoreboardv3 `gameTimeUTC`) and season.
   - Write per-book rows to `book_odds`.
   - Keep the betting rule unchanged: bet only when edge > 0; quarter-Kelly capped at 5%.
5. **track.py.**
   - Settle any unsettled past date, not only yesterday, and store final scores.
   - **Postponed games:** if the scoreboard says postponed, or the game is missing past a cutoff, set status to void, profit_loss 0, correct NULL.
   - Recompute bankroll as it does today.
   - Make the Kelly fraction and cap constants importable.
6. **Scheduling and workflow.**
   - Split `daily_workflow.py` into a `--morning` mode (collect, features, Elo, retrain, settle, results SMS) and a `--predict` mode (tonight's predictions plus a picks SMS).
   - Run the predict mode **about 60 minutes before the first tip**. For example, a Task Scheduler job every 30 minutes from 11:00 to 22:00 that predicts once when now ≥ first tip − 60 min and today isn't predicted yet.
   - Log each run with its `kind`.
   - Update `task_scheduler_setup.ps1` and the scheduler README.
7. **API.** Keep the old routes working. Add `season` alongside `year`. New routes:
   - `GET /api/slate?date=`, everything the Games page needs:
     - **per game:** ids, tip time, teams (tricode, name), record and L10 string as of that date (from `games`, same season), pregame probabilities, pick, odds, bookmaker, implied probability, edge, bet, bankroll at bet time, full Kelly, fraction, status, scores, skip_reason, the per-book grid with the best index per side, and which side was bet
     - **summary:** counts, bets placed, staked, settled P/L
     - **past dates:** the night recap (net P/L, bankroll before and after, records, staked, ROI, best and worst bet)
   - `GET /api/live-scores?date=`
     - nba_api `live.nba.endpoints.scoreboard`, server-side cache for 20–30s
     - matches on game_id; the live IDs match the stats IDs
     - returns status, period, formatted clock (Q3 4:40, OT 2:31, 2OT), scores, a postponed flag, `fetched_at`, and `stale: true` with the last good data when a fetch fails
   - `GET /api/game/<game_id>`: the drawer data, including **rest days** for both teams, Elo, rolling stats per side, the odds grid, the pick, edge and bet, and the result.
   - `GET /api/days?end=&n=7`: per-date rollup for the rail (games, picks W–L, bets W–L, net P/L).
   - `GET /api/performance?season=`:
     - KPIs: bankroll, net P/L, ROI, staked, bets W–L, picks W–L and accuracy, max drawdown with peak and trough dates, longest streaks
     - the nightly series: date, bankroll, nightly P/L, bets W–L, picks W–L
     - splits by book, confidence bucket and edge bucket (bets, W, L, staked, P/L, ROI)
     - the recent bet W/L sequence
   - `GET /api/predictions?season=&team=&bets_only=&result=&book=&min_edge=&page=&page_size=`: log rows and a total.
   - `GET /api/model`: production model name, trained_at and test metrics from the metadata and leaderboard files, live season accuracy and pick count, and calibration buckets from settled predictions.
   - `GET /api/workflow-status`: latest run per kind, a state (ok / running / failed / missed), and `controls_allowed`.
   - `POST /api/run-workflow`:
     - only allowed when the request comes from 127.0.0.1/::1 **and** `ALLOW_RUN_WORKFLOW=true`
     - returns 409 if a run is already going
     - starts `run_workflow_async()`
8. **Tests.** Pytest against the seeded DB, covering:
   - each endpoint's shape
   - season filtering
   - the Kelly worked example ($1,111.67 bankroll, 61% at −105 → $55.58)
   - the void path for postponed games
   - live-score clock formatting and stale fallback
   - local-only gating of run-workflow
9. **Later / optional.**
   - An end-of-night settle job.
   - Per-prediction factor contributions for drawer option B, in a `prediction_factors` table: logistic coefficient × scaled value, converted to probability points.
   - Fix the README's accuracy claim.
