import joblib
import pandas as pd
from src.database import select_rows
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, log_loss
from sklearn.calibration import CalibratedClassifierCV

# --- Config ---
FEATURES = [
    'HOME_roll_PTS', 'HOME_roll_FG_PCT', 'HOME_roll_REB', 'HOME_roll_AST', 'HOME_roll_TOV', 'HOME_roll_STOCKS',
    'AWAY_roll_PTS', 'AWAY_roll_FG_PCT', 'AWAY_roll_REB', 'AWAY_roll_AST', 'AWAY_roll_TOV', 'AWAY_roll_STOCKS',
    'rest_diff',
    'HOME_ELO', 'AWAY_ELO', 'ELO_DIFF'
]
TARGET = 'home_win'

# load_features() loads the cleaned feature table from the database into pandas
def load_features():
    return select_rows("features")

# split_data() divides the data into chronological 80/20 training and test sets
def split_data(df):
    ordered = df.assign(_GAME_DATE=pd.to_datetime(df['GAME_DATE'])).sort_values('_GAME_DATE')
    split_index = max(1, int(len(ordered) * 0.8))
    train = ordered.iloc[:split_index].drop(columns='_GAME_DATE')
    test = ordered.iloc[split_index:].drop(columns='_GAME_DATE')
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