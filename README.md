# NBA Game Prediction & Paper Trading

An end-to-end pipeline that predicts NBA game outcomes, paper-bets against real sportsbook lines, and publishes the results to a public dashboard.

## How it works

1. `nba_api` supplies regular-season team-game rows for 2019-20 through 2025-26.
2. Shifted 10-game rolling averages (points, FG%, rebounds, assists, turnovers, stocks) and rest days are built with strict temporal ordering, so no future data leaks in.
3. Elo ratings run across all seasons, with 25% mean reversion between seasons.
4. Candidate models (calibrated logistic regression, XGBoost, calibrated XGBoost, gradient boosting, random forest and a PyTorch LSTM) are trained chronologically (the first 80% of games train, the last 20% test) and ranked by log-loss, Brier score and calibration. `NBA_PRODUCTION_MODEL` picks the live model.
5. The Odds API supplies moneylines, shopped across the preferred books for the best price.
6. Paper bets use quarter-Kelly sizing, capped at 5% of bankroll, and are placed only when the model's edge over the implied probability is positive.
7. Everything is stored in Supabase Postgres, which is the only contract between the laptop pipeline and the hosted dashboard.

## Architecture

| Part | Runs on | Entry point |
|---|---|---|
| Pipeline (collect, Elo, features, train, settle, predict, SMS) | Windows laptop, Task Scheduler | `daily_workflow.py`, `run_pipeline.bat`, `run_predict.bat` |
| Database | Supabase Postgres (RLS on, server key only) | `src/database.py`, `supabase/migrations/` |
| Dashboard API and page | Vercel (Flask) or `python app.py` locally | `app.py`, `public/` |

## Setup (laptop)

1. Get a free API key at [the-odds-api.com](https://the-odds-api.com).
2. Copy `.env.example` to `.env` and fill it in. `SUPABASE_SECRET_KEY` is server-only.
3. `python -m venv venv` then `venv\Scripts\activate`
4. `pip install -r requirements-pipeline.txt`
5. Schema changes live in `supabase/migrations/` and are applied manually. Scripts never create or alter tables.

## Daily usage

- **Morning:** `run_pipeline.bat` runs collect → Elo → features → train → settle.
- **Predictions:** `run_predict.bat` fetches tonight's games and odds, predicts, sizes bets and logs them.
- **Scheduled:** `scheduler\task_scheduler_setup.ps1` registers the Task Scheduler jobs that run `daily_workflow.py` and send the SMS summary.
- **Local dashboard:** `python app.py`, then open http://127.0.0.1:5000

## Hosting (Vercel)

Vercel runs `app.py` as a single Python function and installs only `requirements.txt` (no ML libraries). Set `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (Sensitive), `FLASK_SECRET_KEY` and `NBA_SCHEMA_V2` in the Vercel project. Never set `ALLOW_RUN_WORKFLOW` there.

## Testing

`run_local_test.bat` (or `python -m unittest discover -s tests -v`) runs the offline test suite. It uses fakes and never touches the network or the database.

`scripts\seed_test_games.py --reset` builds a deterministic **local SQLite** fixture for offline experiments only. It is not used by the pipeline and must never point at production.

## Results

From `data/model_leaderboard.csv` (trained 2026-09-18, 1,596 held-out test games):

| Metric | Production model (`legacy-calibrated-logistic`) |
|---|---|
| Test accuracy | 68.2% |
| Brier score | 0.209 |
| ROC AUC | 0.729 |
| Home-win base rate | 55.0% |

## Tech stack

nba_api · pandas · scikit-learn · XGBoost · PyTorch · The Odds API · Supabase Postgres · Flask · Vercel · Twilio
