# NBA Game Prediction & Paper Trading System

An end-to-end machine learning pipeline that predicts NBA game outcomes and simulates paper betting against real sportsbook lines.

## How It Works

1. Historical game data is pulled from the NBA API across 7 seasons (14,000+ games)
2. Rolling average features (points, FG%, rebounds, assists, turnovers, stocks) are engineered with strict temporal validation to prevent data leakage
3. Elo ratings are computed across all 7 seasons with mean reversion between seasons and merged with rolling features
4. A logistic regression classifier is trained on the combined features, achieving 71.1% accuracy on held-out test data
5. Real-time odds are fetched from The Odds API and line shopped across multiple bookmakers to find the best price
6. Kelly Criterion bet sizing is used to simulate paper bets — only placed when model edge exceeds implied odds
7. All predictions and results are logged to a local SQLite database with daily bankroll tracking

## Project Structure

    nba-predictor/
    ├── data/
    │   └── nba.db          ← SQLite database (games, features, elo, predictions, bankroll)
    ├── src/
    │   ├── collect.py      ← fetch game data from NBA API
    │   ├── features.py     ← feature engineering and rolling averages
    │   ├── elo.py          ← compute and store Elo ratings across all seasons
    │   ├── model.py        ← train and evaluate logistic regression model
    │   ├── predict.py      ← generate predictions for tonight's games
    │   ├── odds.py         ← fetch and line shop real-time odds from The Odds API
    │   └── track.py        ← log results and track paper trading bankroll
    ├── run_pipeline.bat    ← morning automation script
    ├── run_predict.bat     ← evening automation script
    ├── .env.example        ← API key template
    └── requirements.txt    ← Python dependencies

## Setup

1. Sign up for a free API key at [the-odds-api.com](https://the-odds-api.com)
2. Copy `.env.example` to `.env` and fill in your key
3. Create and activate a virtual environment: `python -m venv venv` then `venv\Scripts\activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Run initial data collection: `python src/collect.py` → `python src/features.py` → `python src/elo.py` → `python src/model.py`

## Daily Usage

### Morning — `run_pipeline.bat`
Fetches new games, recomputes features, updates Elo ratings, retrains model, updates yesterday's results and bankroll

### Evening — `run_predict.bat`
Fetches tonight's games and line shops odds across multiple bookmakers, generates win probabilities, sizes paper bets using Kelly Criterion, logs predictions to database

## Results

| Metric | Value |
|--------|-------|
| Test accuracy | 71.1% |
| Naive baseline | 53.6% |
| Edge over baseline | +17.5% |
| Training seasons | 2019-20 through 2025-26 |
| Total games | 14,000+ |

## Tech Stack

| Component | Tool |
|-----------|------|
| Data collection | nba_api |
| Data storage | SQLite + sqlalchemy |
| Feature engineering | pandas |
| Elo ratings | Custom implementation |
| Machine learning | scikit-learn |
| Odds fetching | The Odds API + requests |
| Model persistence | joblib |

## Notes

- Model retrains daily on a rolling window using the most recent 30 days as the test set
- Elo ratings apply 25% mean reversion between seasons to account for roster changes
- Paper trading uses quarter-Kelly sizing with a 5% bankroll cap per game
- Bets are only placed when the model edge exceeds the implied odds from the sportsbook line
- Line shopping across multiple bookmakers ensures the best available price on every bet
- 500 free API requests per month from The Odds API is sufficient for daily use