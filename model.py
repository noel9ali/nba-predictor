import sqlite3
import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, log_loss
from sklearn.calibration import CalibratedClassifierCV

# --- Config ---
DB_PATH = 'data/nba.db'

FEATURES = [
    'HOME_roll_PTS', 'HOME_roll_FG_PCT', 'HOME_roll_REB', 'HOME_roll_AST', 'HOME_roll_TOV', 'HOME_roll_STOCKS',
    'AWAY_roll_PTS', 'AWAY_roll_FG_PCT', 'AWAY_roll_REB', 'AWAY_roll_AST', 'AWAY_roll_TOV', 'AWAY_roll_STOCKS',
    'rest_diff',
    'HOME_ELO', 'AWAY_ELO', 'ELO_DIFF'
]
TARGET = 'home_win'

# load_features() loads the cleaned feature table from the database into pandas
def load_features():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('SELECT * FROM features', conn)
    conn.close()
    return df

# split_data() divides the data into training and test sets by date
def split_data(df):
    # use everything except the last 30 days as training
    cutoff = cutoff = (pd.Timestamp.today() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    train = df[df['GAME_DATE'] < cutoff]
    test  = df[df['GAME_DATE'] >= cutoff]
    return train, test

# train_model() rescales features to a unified scale and trains a logistic
#   regression model on the data
def train_model(train):
    train = train.dropna(subset=FEATURES)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(train[FEATURES])
    y_train = train[TARGET]

    # train base logistic regression
    base_model = LogisticRegression()
    
    # wrap with calibration to improve probability estimates
    model = CalibratedClassifierCV(base_model, cv=5, method='isotonic')
    model.fit(X_train, y_train)
    
    return model, scaler

# evaluate_model() measures the model's accuracy and log loss on test games
def evaluate_model(model, scaler, test):
    X_test = scaler.transform(test[FEATURES])
    y_test = test[TARGET]

    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)[:, 1]

    print(f"Test games:  {len(test)}")
    print(f"Accuracy:    {accuracy_score(y_test, preds):.1%}")
    print(f"Log Loss:    {log_loss(y_test, probs):.4f}")
    print(f"Baseline (always pick home): {test[TARGET].mean():.1%}")

# save_model() writes the trained model and scaler to disk for future loading
def save_model(model, scaler):
    joblib.dump(model, 'data/model.pkl')
    joblib.dump(scaler, 'data/scaler.pkl')
    print("Model saved!")

def run():
    print("Loading features...")
    df = load_features()

    print("Splitting data...")
    train, test = split_data(df)
    print(f"  Train: {len(train)} games")
    print(f"  Test:  {len(test)} games")

    print("Training model...")
    model, scaler = train_model(train)

    print("Evaluating...")
    evaluate_model(model, scaler, test)

    print("Saving model...")
    save_model(model, scaler)

if __name__ == '__main__':
    run()