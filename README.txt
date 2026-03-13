# NBA Game Prediction & Paper Trading System

An end-to-end machine learning pipeline that predicts NBA game outcomes and simulates paper betting against real sportsbook lines.

## How It Works

1. Historical game data is pulled from the NBA API across 7 seasons (14,000+ games)
2. Rolling average features are engineered with strict temporal validation to prevent data leakage
3. A logistic regression classifier is trained on the data, achieving 61.4% accuracy on held-out test data
4. Real-time odds are fetched from The Odds API to calculate model edge per game
5. Kelly Criterion bet sizing is used to simulate paper bets against real sportsbook lines
6. All predictions and results are logged to a local SQLite database

## Project Structure

    nba-predictor/
    ├── data/
    │   └── nba.db          ← SQLite database (games, features, predictions, bankroll)
    ├── src/
    │   ├── collect.py      ← fetch game data from NBA API
    │   ├── features.py     ← feature engineering and rolling averages
    │   ├── model.py        ← train and evaluate logistic regression model
    │   ├── predict.py      ← generate predictions for tonight's games
    │   ├── odds.py         ← fetch real-time odds from The Odds API
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
5. Run initial data collection: `python src/collect.py` → `python src/features.py` → `python src/model.py`

## Daily Usage

### Morning — `run_pipeline.bat`
Fetches new games, recomputes features, retrains model, updates yesterday's results and bankroll

### Evening — `run_predict.bat`
Fetches tonight's games and odds, generates win probabilities, sizes paper bets using Kelly Criterion, logs predictions to database

## Results

| Metric | Value |
|--------|-------|
| Test accuracy | 61.4% |
| Naive baseline | 53.6% |
| Edge over baseline | +7.8% |
| Training seasons | 2019-20 through 2025-26 |
| Total games | 14,000+ |

## Tech Stack

| Component | Tool |
|-----------|------|
| Data collection | nba_api |
| Data storage | SQLite + sqlalchemy |
| Feature engineering | pandas |
| Machine learning | scikit-learn |
| Odds fetching | The Odds API + requests |
| Model persistence | joblib |

## Notes

- Model retrains daily on a rolling window using the most recent 30 days as the test set
- Paper trading uses quarter-Kelly sizing with a 5% bankroll cap per game
- Bets are only placed when the model edge exceeds the implied odds from the sportsbook line
- 500 free API requests per month from The Odds API is sufficient for daily use