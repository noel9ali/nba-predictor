# Copilot instructions for `nba-predictor`

## Build, run, and validation commands

This is a Python project. Use the repository virtual environment on Windows:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements-pipeline.txt
```

The normal daily workflows are implemented as batch files:

```powershell
.\run_pipeline.bat   # collect games, recompute Elo/features, train, track results
.\run_predict.bat    # fetch today's games/odds and log predictions
```

For deterministic offline/local validation, use a separate worktree or a backed-up database:

```powershell
.\run_local_test.bat
```

The production pipeline now uses Supabase. The old local fixture script is only for isolated offline development and must not be pointed at the migrated Supabase data. To seed only a local SQLite fixture:

```powershell
python scripts\seed_test_games.py --reset
```

The offline test suite (fakes only, no network or database) runs with:

```powershell
python -m unittest discover -s tests -v
```

The closest targeted smoke check for NBA API connectivity is:

```powershell
python src\test.py
```

Individual pipeline stages can be run directly, for example `python src\elo.py`, `python src\features.py`, or `python src\model.py`. Scripts that call external services require the corresponding network access and credentials; copy `.env.example` to `.env` and set `ODDS_API_KEY` before using odds/prediction workflows.

## Architecture

- `src\collect.py` is the ingestion boundary. It downloads regular-season team-game rows from `nba_api` for the configured seasons and upserts them into the `games` table on `(GAME_ID, TEAM_ID)` after successful collection.
- `src\elo.py` reads chronological game rows, pairs home/away records by `GAME_ID`, records pre-game Elo values, applies updates after each game, applies 25% season-boundary mean reversion toward 1500, and writes the `elo` table.
- `src\features.py` converts the two team rows for each game into one row, computes shifted 10-game rolling team statistics and rest-day differences, joins pre-game Elo values, and writes the `features` table. The shift before rolling is required to avoid using the current game's result as an input.
- `src\model.py` is the active training/evaluation entry point. It standardizes the fixed `FEATURES` list, splits rows chronologically 80/20, trains the registered candidate models with time-series cross-validation, evaluates probability quality, writes the leaderboard/metadata, and persists the selected model and scaler under `data\`.
- `src\model_wrappers.py` adapts the PyTorch LSTM to the scikit-learn estimator interface so it can participate in the same grid-search and probability-scoring flow as XGBoost, gradient boosting, random forest, and calibrated logistic regression.
- `src\predict.py` loads the persisted model/scaler, combines today's NBA scoreboard data with the latest feature rows and Elo ratings, fetches and line-shops moneyline odds, applies edge filtering and quarter-Kelly sizing, and records predictions.
- `src\track.py` owns prediction/bankroll tables and updates completed results from the NBA scoreboard. `src\backtest_last_year.py` reuses the model registry and logged odds to evaluate a configured production model on a season and simulate bets.
- Supabase PostgreSQL is the integration contract between stages. The server-only client lives in `src\database.py`; derived tables include `elo`, `features`, `predictions`, and `bankroll`. Generated model artifacts and reports are written under `data\`.

## Repository-specific conventions

- Run the active scripts from the repository root. Model artifacts use relative paths under `data\`, and the batch files invoke modules as `python src\...`; database access is configured through Supabase environment variables.
- Treat `src\model.py` as authoritative for current training and prediction behavior. The root-level `model.py` is an older standalone logistic-regression implementation and is not used by the batch workflows.
- Keep training and feature evaluation chronological. Do not shuffle game rows or compute rolling statistics from the current game/future games; preserve the shifted rolling-window logic in `src\features.py`.
- Keep the training and inference feature schema synchronized. `src\predict.py` must assemble the same 16 columns and order listed in `src\model.py`: rolling home/away stats, `rest_diff`, `HOME_ELO`, `AWAY_ELO`, and `ELO_DIFF`.
- Model names are registry keys in `src\model.py`. `NBA_PRODUCTION_MODEL` selects the production candidate; the default is `legacy-calibrated-logistic`. If changing a candidate, update the registry/metadata behavior rather than hard-coding model-specific logic in prediction.
- Persist models with the paired scaler. `data\model.pkl` and `data\scaler.pkl` must be trained from the same feature schema; `data\model_metadata.json` and `data\model_leaderboard.csv` describe the training run.
- Production database writes go through `src\database.py`, use explicit structured payloads, bounded batches, and database-enforced upsert/unique-key behavior. Do not add table creation, truncation, migration, or reset logic to production scripts.
- `scripts\seed_test_games.py` is intentionally separate from production access and still manages an offline SQLite fixture; never use it with production data.
- API-facing code uses `nba_api` for games/results and The Odds API for moneylines. Odds are matched by full team names through `src\odds.py`'s abbreviation map, and bets are only recorded when model edge is positive.
- Keep secrets in `.env`; do not commit `.env`, generated model files, or the local SQLite database fixture. The checked-in `.env.example` is the template for `ODDS_API_KEY`, `SUPABASE_URL`, and `SUPABASE_SECRET_KEY`.
- Server-side Supabase access requires `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. Never expose the secret key to browser code, API responses, logs, or source control.
- Schema changes live in `supabase/migrations/` and are applied manually (Supabase CLI or MCP `apply_migration`); no script ever creates, alters, truncates or resets a table.
- `NBA_SCHEMA_V2` (default `false`) gates *new* columns and tables used by new code paths (new `predictions` columns, `book_odds`, `model_runs`). Check `database.schema_v2_enabled()` before writing to those. The `bankroll`/`workflow_log` tables are not gated by this flag — code accesses them unconditionally and instead catches `MissingTableError` (see `track._require_bankroll_table`, `daily_workflow.get_overall_stats`) to handle the pre-migration state.
- `requirements.txt` is the Vercel/API runtime dependency set (no ML libraries). `requirements-pipeline.txt` extends it with the training/pipeline dependencies (scikit-learn, xgboost, torch, twilio) and is what the laptop installs.
- The dashboard API (`app.py`) is frontend-owned and imports only `src\database.py`; it never imports `src\model.py`, `src\predict.py` or other pipeline modules directly.
