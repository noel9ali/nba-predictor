# Design ideation session: NBA Predictor web dashboard

Paste everything below into a new session, with the `nba-predictor.worktrees` folder connected.

---

You are running a full design ideation session with me (Noel) for the web dashboard of my NBA game prediction and paper-trading system. A first design session already locked the visual direction and a draft of the main Games page. Your job in this session is to settle **every page the site will have, how people interact with it, and what gets built next**. Work iteratively: ask me focused questions, show options visually, take my feedback, refine, and repeat until I approve.

## How to work

1. **Get oriented before asking anything.**
   - Read the Design canvas where the drafts live: https://claude.ai/code/artifact/a702b1d5-c99f-4bf4-b134-aa7cb93049c2. The current Games draft is the artboard `Games.dc.html` ("Round 2 · Games page (C)"). The three Round 1 concepts are still on the canvas for reference, and the chosen one is `Broadcast.dc.html`.
   - Copies of the drafts are also saved in `daily-workflow-integration-frontend/design/drafts/`.
   - Skim the codebase in `daily-workflow-integration-frontend/`: `app.py` (Flask + JSON API), `src/track.py` (DB schema, Kelly), `src/predict.py`, `src/odds.py`, `daily_workflow.py`, `templates/index.html`. The model comparison work is in the other worktree, `nba-model-integration-lstm-gb-rf/data/` (`model_leaderboard.csv`, `model_metadata.json`).
2. **Keep working on the same canvas.** Add each round as a new labeled row (a title note like "Round 3: …") under the earlier ones. Never delete earlier rounds. Artboards are desktop 1440 wide; phone artboards are 390 wide.
3. **Ask questions with the multiple-choice question tool**, at most 4 at a time, and only when the answer changes what you build. If something has a sensible default, pick it and tell me.
4. **Show options, don't just describe them.** When a choice is visual, like a layout, a page structure or a component variant, draw 2–3 options side by side and let me pick.
5. **One topic per round.** After each round, summarize what's decided in a sentence or two and what's next.
6. Don't build the final HTML in this session unless I ask. This session ends with approved designs, a written spec and a build plan (see Deliverables).

## Constraints

- **Team logos are required** on every matchup. You can't draw or recreate NBA logos, so use labeled logo placeholders in team colors, sized and placed exactly where the real logos go. The final build will load the real logo images from a source I choose (a folder of logo files in the project, or an image link pattern). One open question for this session is which source to use.
- **Use sample data only, labeled "Sample data" in the design.** Make it realistic but never present it as real results. Sample slate date: Tue, Nov 17. Today is late September, which is the offseason, so there are no live games to pull from right now.
- Don't use the word "genuinely" in anything you write to me.

## The system (context)

- **Data.** 7 seasons (2019-20 through 2025-26, 14,000+ regular-season games) pulled with `nba_api` (`leaguegamefinder`) into SQLite at `data/nba.db`.
- **Features.** Rolling averages (points, FG%, rebounds, assists, turnovers, stocks = blocks + steals), rest-day difference, and Elo ratings with mean reversion between seasons. Strict temporal validation to prevent leakage.
- **Model.** 71.1% accuracy on held-out games is the headline number. I've described the model as XGBoost, but the README says logistic regression, and `model_metadata.json` lists `legacy-calibrated-logistic` as the production model. A second worktree compares XGBoost, gradient boosting, random forest and an LSTM (accuracy 67–68%, plus log loss, Brier score, ROC AUC and calibration). **Ask me which model the site should present and whether a model comparison page belongs on the site.**
- **Odds.** The Odds API, moneyline (`h2h`), US region. Line shop across DraftKings, FanDuel, BetMGM, BetRivers and BetUS, taking the best price.
- **Betting.** Edge = model win probability − implied probability. A paper bet is placed only with positive edge, sized with Kelly Criterion from a $1,000 starting bankroll.
- **Logging.** SQLite tables:
  - `predictions`: game_id, game_date, home_team, away_team, home_win_prob, away_win_prob, predicted_winner, actual_winner, correct, bet_placed, bet_amount, odds, profit_loss
  - `bankroll`: date, balance
  - also `games`, `features` and `elo`
- **Automation.**
  - Morning: `run_pipeline.bat` (Windows Task Scheduler, 6:00 AM) pulls new games, rebuilds features and Elo, retrains, and settles yesterday's results and bankroll.
  - Evening: `run_predict.bat` pulls tonight's games and odds, predicts and logs bets.
  - `daily_workflow.py` wraps this, logs runs to a workflow log table, and sends an SMS summary through Twilio.
- **Flask API** (`app.py`):
  - `/`
  - `/api/dashboard-state`
  - `/api/ytd-summary`: accuracy, bets, staked, P/L, ROI, streaks, max drawdown
  - `/api/recommendations`: per game, the pick, win prob, implied prob, edge, confidence bucket, bet amount, odds, and details with Elo and rolling stats for both teams
  - `/api/bankroll-series`
  - The API takes `year` and `game_date` query params.

**Known data gaps**, which belong in the build plan:

- Only the single best price is stored. Showing every book's odds needs a new table for per-book odds.
- The bookmaker name and the edge aren't stored in the `predictions` table.
- There's no live score feed yet.
- Team records and last-10 form aren't stored, but can be derived from `games`.

## Decisions already locked

**Visual direction: "Sports broadcast" (concept C)**

- Deep navy background `#0a1630`, panels `#102244`, dividers `#1d3461`.
- Colors: yellow accent `#ffc72c`, muted text `#b7c4dd`, win/hit green `#3ee08f`, loss/miss red `#ff8a95`, live red `#d62839`.
- Type: Barlow Condensed (uppercase, 600–800) for display and numbers, Barlow for body text.
- Team colors for logo placeholders and probability bars. Square edges and bold score-bug styling.
- Comfortable density. Desktop first.

**Site scope**

- The main page is about **games: predictions and outcomes**.
- Bankroll, ROI, model accuracy and the full paper-trading history move to a **second page** (working name "Performance"). The nav already shows "Games" and "Performance" tabs.

**Games page (current draft)**

- **Header:**
  - brand, nav, "scores refresh every 30s · updated [time]", Sample data tag
  - "Tonight's slate" title with the date and counts (final / live / upcoming)
  - summary stats: Bets placed, Total staked, Settled P/L, Live picks ahead
- **Hero, "Next up · biggest edge":** the game that hasn't started yet and has a placed bet with the biggest edge. It **hands off to the next one at each tip-off**. The hero includes:
  - large logo placeholders, record, last-10 strip, pregame win probability and a probability bar
  - Pick, Odds taken, Edge, Bet placed
  - a per-book odds table
- **All games:** **two cards per row**, in **tip-off order**. **Finished games stay where they are.** Each card shows:
  - status chip (Tip-off time / LIVE with quarter and clock / Final) and pregame edge
  - both teams, each with a logo, abbreviation and name, record, last-10 strip, **pregame** win %, and the score once the game starts
  - an "Odds at time of bet" table across all five books. The price actually taken is filled yellow, and the other team's best price has yellow text.
  - a footer with the pick, odds and book, the live margin ("up 5" / "down 4") or the final result ("won by 8"), and a bet tag: "Placed $X" with a lock icon while open, "Hit +$X" / "Miss −$X" once settled, or "No bet placed"
- **Bets are already placed.** There is **no live betting integration**. Everything must read as locked pregame decisions: pregame probabilities, odds at the time of the bet, bets placed. Live data only updates scores and the pick's status.
- **Last night:** rows with logos, final score, pick and pregame win %, odds and book, a Hit/Miss chip, bet and P/L, and a summary line (picks record, bets record, net P/L).

**Live scores plan**

- **Source:** `nba_api.live.nba.endpoints.scoreboard`, already installed in the venv. It's free with no key, and gives status, quarter, clock, scores, tricodes and game IDs. It's unofficial, so it may change or get throttled.
- **Server:** a new Flask route `/api/live-scores` that caches for 20–30s and matches games to predictions by date plus home/away team. The browser can't call NBA.com directly because of CORS.
- **Page:** polls every 30s while any game is live, and stops when all games are final.
- **Fallback:** The Odds API `/scores`. It has no clock and costs quota.
- **Optional:** an end-of-night job that settles results right away instead of waiting for the 6 AM run.

**Final build target**

- One self-contained HTML file in `daily-workflow-integration-frontend/`, starting from embedded sample data and wired to the Flask API later.

## Agenda for this session

Work through these in order, one round each. Merge or split rounds as needed.

1. **Site map: which pages exist.** Propose a page list and let me choose what's in, what's merged and what's deferred. Candidates:
   - **Games:** tonight plus last night; draft done.
   - **Performance:** bankroll over time, ROI, bet win rate, model accuracy, streaks, max drawdown, P/L by bookmaker / confidence bucket / edge size, and the full prediction log with filters.
   - **Game detail:** opened from a card. Why the model picked it (Elo, rolling stats, stocks, rest days, Elo diff), the odds across books, and the result.
   - **Model:** the model comparison leaderboard, calibration, feature importance, and which model is live.
   - **History / calendar:** browse any past day's slate with its outcomes.
   - **System / settings:** pipeline and workflow run status, the last run log, trigger a run, SMS on/off, Kelly fraction, minimum edge, which books to include.
2. **Navigation and global layout:** nav structure, date navigation (previous/next day, date picker, jump to tonight), and what persists across pages.
3. **Interactions on the Games page:**
   - clicking or expanding a card
   - hover or tap explanations for edge, implied probability and Kelly
   - filters: bets only, live only, hide no-bet games
   - sorting
   - manual refresh and a "stale data" state
   - what happens visually at tip-off and at the final buzzer, including the hero hand-off
4. **Edge cases and empty states:**
   - no unstarted bets left, so the hero needs a fallback (for example a night recap)
   - zero bets on the slate, or no games (offseason, All-Star break)
   - postponed games, overtime clocks, missing odds for a game
   - live feed errors or delays, and pipeline failures
5. **Performance page:** 2–3 layout options, then refine the chosen one. It has to read in the same broadcast style.
6. **Any other pages chosen in step 1**, one round each.
7. **Mobile:** a phone version of the Games page, and of Performance if it's in scope.
8. **Logo source decision:** local folder vs. image link pattern, file naming by tricode, and a fallback when a logo fails to load.
9. **What comes next:** agree on the build plan.

## Deliverables by the end of the session

1. **Approved artboards on the canvas** for every in-scope page and its key states (pregame / live / final / empty / error), plus phone versions of the main pages.
2. **`daily-workflow-integration-frontend/design/DESIGN_SPEC.md`** covering:
   - the site map
   - each page's sections and components
   - every state and interaction
   - the data each component needs, mapped to existing DB columns and API fields or marked as a new requirement
   - the visual tokens (colors, type, spacing)
   - open questions
3. **A build plan** (in the spec or as a separate `design/BUILD_PLAN.md`). It's an ordered task list covering:
   - backend changes: the per-book odds table, storing bookmaker and edge, `/api/live-scores`, any new endpoints
   - logo assets
   - the single-file HTML build with sample data
   - wiring it to the API
   - testing
   - which parts can run in parallel

Start by reading the canvas and the codebase, then give me a short summary of where things stand and open Round 3 (site map).
