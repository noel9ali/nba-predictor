import json
import os

import joblib
import numpy as np
import pandas as pd
from database import select_rows
from model_wrappers import TorchLSTMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

# --- Config ---
MODEL_PATH = "data/model.pkl"
SCALER_PATH = "data/scaler.pkl"
METADATA_PATH = "data/model_metadata.json"
LEADERBOARD_PATH = "data/model_leaderboard.csv"
RANDOM_STATE = 42
DEFAULT_PRODUCTION_MODEL = "legacy-calibrated-logistic"

FEATURES = [
    "HOME_roll_PTS",
    "HOME_roll_FG_PCT",
    "HOME_roll_REB",
    "HOME_roll_AST",
    "HOME_roll_TOV",
    "HOME_roll_STOCKS",
    "AWAY_roll_PTS",
    "AWAY_roll_FG_PCT",
    "AWAY_roll_REB",
    "AWAY_roll_AST",
    "AWAY_roll_TOV",
    "AWAY_roll_STOCKS",
    "rest_diff",
    "HOME_ELO",
    "AWAY_ELO",
    "ELO_DIFF",
]
TARGET = "home_win"


def load_features():
    return select_rows("features", order_by=["GAME_DATE", "GAME_ID"])


def split_data(df):
    ordered = df.assign(_GAME_DATE=pd.to_datetime(df["GAME_DATE"])).sort_values("_GAME_DATE")
    split_index = max(1, int(len(ordered) * 0.8))
    train = ordered.iloc[:split_index].drop(columns="_GAME_DATE")
    test = ordered.iloc[split_index:].drop(columns="_GAME_DATE")
    return train, test


def split_data_by_season(df, test_season):
    if "SEASON" not in df.columns:
        season_lookup = select_rows(
            "games",
            columns="GAME_ID,SEASON",
            order_by=["GAME_ID", "TEAM_ID"],
        )
        season_lookup = season_lookup.drop_duplicates(subset=["GAME_ID"])
        season_lookup["GAME_ID"] = season_lookup["GAME_ID"].astype(str)

        df = df.copy()
        df["GAME_ID"] = df["GAME_ID"].astype(str)
        df = df.merge(season_lookup, on="GAME_ID", how="left")

    train = df[df["SEASON"] != test_season]
    test = df[df["SEASON"] == test_season]
    return train, test


def _ensure_data_dir():
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)


def _clean_frame(frame):
    clean = frame.dropna(subset=FEATURES).copy()
    clean["GAME_DATE"] = pd.to_datetime(clean["GAME_DATE"])
    clean = clean.sort_values("GAME_DATE").reset_index(drop=True)
    return clean


def _split_xy(frame):
    clean = _clean_frame(frame)
    X = clean[FEATURES]
    y = clean[TARGET].astype(int)
    return clean, X, y


def _time_series_cv(n_samples, requested_splits=3):
    if n_samples < 4:
        raise ValueError("At least four training rows are required for time-series cross-validation.")
    n_splits = min(requested_splits, n_samples - 1)
    return TimeSeriesSplit(n_splits=max(2, n_splits))


def _safe_roc_auc(y_true, probs):
    try:
        return roc_auc_score(y_true, probs)
    except ValueError:
        return float("nan")


def _expected_calibration_error(y_true, probs, n_bins=10):
    y_true = np.asarray(y_true)
    probs = np.asarray(probs)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bucket_ids = np.digitize(probs, bins[1:-1], right=True)

    error = 0.0
    for bucket in range(n_bins):
        mask = bucket_ids == bucket
        if not np.any(mask):
            continue
        confidence = probs[mask].mean()
        accuracy = y_true[mask].mean()
        error += abs(confidence - accuracy) * (mask.sum() / len(probs))
    return float(error)


def _metric_row(model_name, y_true, probs, y_train=None, train_probs=None, search=None, feature_signal=""):
    probs = np.clip(np.asarray(probs), 1e-6, 1 - 1e-6)
    preds = (probs >= 0.5).astype(int)

    row = {
        "model": model_name,
        "test_games": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, preds)),
        "log_loss": float(log_loss(y_true, probs)),
        "brier_score": float(brier_score_loss(y_true, probs)),
        "roc_auc": float(_safe_roc_auc(y_true, probs)),
        "calibration_ece": _expected_calibration_error(y_true, probs),
        "baseline_home_win_rate": float(np.mean(y_true)),
        "avg_confidence": float(np.mean(np.maximum(probs, 1 - probs))),
        "probability_std": float(np.std(probs)),
        "extreme_prediction_rate": float(np.mean((probs <= 0.1) | (probs >= 0.9))),
        "feature_signal": feature_signal,
    }

    if y_train is not None and train_probs is not None:
        train_probs = np.clip(np.asarray(train_probs), 1e-6, 1 - 1e-6)
        train_preds = (train_probs >= 0.5).astype(int)
        row["train_accuracy"] = float(accuracy_score(y_train, train_preds))
        row["train_log_loss"] = float(log_loss(y_train, train_probs))
        row["accuracy_gap"] = float(row["train_accuracy"] - row["accuracy"])
        row["log_loss_gap"] = float(row["log_loss"] - row["train_log_loss"])
    else:
        row["train_accuracy"] = float("nan")
        row["train_log_loss"] = float("nan")
        row["accuracy_gap"] = float("nan")
        row["log_loss_gap"] = float("nan")

    if search is not None:
        row["cv_best_score"] = float(search.best_score_)
        row["best_params"] = json.dumps(search.best_params_, sort_keys=True)
    else:
        row["cv_best_score"] = float("nan")
        row["best_params"] = ""

    return row


def _fit_with_grid_search(estimator, param_grid, X_train, y_train):
    search = GridSearchCV(
        estimator=estimator,
        param_grid=param_grid,
        scoring="neg_log_loss",
        cv=_time_series_cv(len(y_train)),
        refit=True,
        n_jobs=1,
        verbose=0,
    )
    search.fit(X_train, y_train)
    return search.best_estimator_, search


def _fit_calibrated_logistic(X_train, y_train):
    estimator = CalibratedClassifierCV(
        LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
        cv=3,
        method="isotonic",
    )
    return _fit_with_grid_search(estimator, [{}], X_train, y_train)


def _fit_current_xgboost(X_train, y_train):
    estimator = XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.05,
        eval_metric="logloss",
        random_state=RANDOM_STATE,
    )
    return _fit_with_grid_search(estimator, [{}], X_train, y_train)


def _fit_tuned_gradient_boosting(X_train, y_train):
    estimator = GradientBoostingClassifier(random_state=RANDOM_STATE)
    param_grid = {
        "n_estimators": [100, 200],
        "learning_rate": [0.05, 0.1],
        "max_depth": [2, 3],
    }
    return _fit_with_grid_search(estimator, param_grid, X_train, y_train)


def _fit_tuned_random_forest(X_train, y_train):
    estimator = RandomForestClassifier(random_state=RANDOM_STATE, n_jobs=1)
    param_grid = {
        "n_estimators": [200, 400],
        "max_depth": [6, None],
        "min_samples_leaf": [1, 4],
        "max_features": ["sqrt"],
    }
    return _fit_with_grid_search(estimator, param_grid, X_train, y_train)


def _fit_tuned_lstm(X_train, y_train):
    estimator = TorchLSTMClassifier(device="cpu", random_state=RANDOM_STATE)
    param_grid = {
        "hidden_size": [16, 32],
        "num_layers": [1],
        "dropout": [0.0, 0.2],
        "lr": [0.001, 0.003],
        "batch_size": [64],
        "epochs": [12],
        "weight_decay": [0.0],
    }
    return _fit_with_grid_search(estimator, param_grid, X_train, y_train)


def model_registry():
    return {
        "legacy-calibrated-logistic": _fit_calibrated_logistic,
        "current-xgboost": _fit_current_xgboost,
        "gradient-boosting-gridsearch": _fit_tuned_gradient_boosting,
        "random-forest-gridsearch": _fit_tuned_random_forest,
        "lstm-gridsearch": _fit_tuned_lstm,
    }


def available_models():
    return list(model_registry().keys())


def get_production_model_name():
    configured = os.getenv("NBA_PRODUCTION_MODEL", DEFAULT_PRODUCTION_MODEL).strip()
    return configured if configured else DEFAULT_PRODUCTION_MODEL


def _candidate_specs():
    registry = model_registry()
    return [(name, registry[name]) for name in available_models()]


def _extract_feature_signal(model):
    importances = getattr(model, "feature_importances_", None)
    if importances is None and hasattr(model, "calibrated_classifiers_"):
        coef_rows = []
        for calibrated in model.calibrated_classifiers_:
            estimator = getattr(calibrated, "estimator", None)
            if estimator is None:
                estimator = getattr(calibrated, "base_estimator", None)
            if estimator is not None and hasattr(estimator, "coef_"):
                coef_rows.append(np.abs(estimator.coef_[0]))
        if coef_rows:
            importances = np.mean(np.vstack(coef_rows), axis=0)

    if importances is None:
        return ""

    importances = np.asarray(importances, dtype=float)
    if importances.ndim != 1 or len(importances) != len(FEATURES):
        return ""

    order = np.argsort(importances)[::-1][:5]
    top_features = [
        {"feature": FEATURES[index], "importance": float(importances[index])}
        for index in order
    ]
    return json.dumps(top_features)


def _fit_candidates(train):
    clean_train, X_train_df, y_train = _split_xy(train)
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train_df)
    y_train_np = y_train.to_numpy()

    fitted = []
    for model_name, fit_fn in _candidate_specs():
        print(f"Training {model_name}...")
        model, search = fit_fn(X_train, y_train_np)
        fitted.append(
            {
                "model_name": model_name,
                "model": model,
                "search": search,
                "feature_signal": _extract_feature_signal(model),
            }
        )

    return fitted, scaler, X_train, y_train_np


def _score_candidates(fitted, scaler, X_train, y_train, test):
    clean_test, X_test_df, y_test = _split_xy(test)
    if len(clean_test) == 0:
        raise ValueError("No test games are available after applying the existing date-based split.")
    X_test = scaler.transform(X_test_df)
    y_test_np = y_test.to_numpy()

    rows = []
    for item in fitted:
        model = item["model"]
        test_probs = model.predict_proba(X_test)[:, 1]
        train_probs = model.predict_proba(X_train)[:, 1]
        rows.append(
            _metric_row(
                item["model_name"],
                y_test_np,
                test_probs,
                y_train=y_train,
                train_probs=train_probs,
                search=item["search"],
                feature_signal=item["feature_signal"],
            )
        )

    leaderboard = pd.DataFrame(rows)
    leaderboard = leaderboard.sort_values(
        by=["log_loss", "brier_score", "calibration_ece", "accuracy", "roc_auc"],
        ascending=[True, True, True, False, False],
    ).reset_index(drop=True)
    leaderboard.insert(0, "rank", leaderboard.index + 1)
    return leaderboard


def _select_best_by_cv(fitted):
    best_item = max(fitted, key=lambda item: item["search"].best_score_)
    return best_item["model"], best_item["model_name"]


def train_model(train):
    fitted, scaler, _, _ = _fit_candidates(train)
    best_model, _ = _select_best_by_cv(fitted)
    return best_model, scaler


def train_selected_model(train, model_name=None):
    selected_name = model_name or get_production_model_name()
    registry = model_registry()
    if selected_name not in registry:
        raise ValueError(
            f"Unknown model '{selected_name}'. Available models: {', '.join(available_models())}"
        )

    clean_train, X_train_df, y_train = _split_xy(train)
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train_df)
    model, search = registry[selected_name](X_train, y_train.to_numpy())
    return model, scaler, clean_train, selected_name, search


def train_best_model(train):
    model, scaler, clean_train, selected_name, search = train_selected_model(
        train,
        DEFAULT_PRODUCTION_MODEL,
    )
    return model, scaler, clean_train


def compute_classification_metrics(y_true, probs):
    probs = np.clip(np.asarray(probs), 1e-6, 1 - 1e-6)
    preds = (probs >= 0.5).astype(int)
    return {
        "test_games": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, preds)),
        "log_loss": float(log_loss(y_true, probs)),
        "brier_score": float(brier_score_loss(y_true, probs)),
        "roc_auc": float(_safe_roc_auc(y_true, probs)),
        "calibration_ece": _expected_calibration_error(y_true, probs),
        "baseline_home_win_rate": float(np.mean(y_true)),
    }


def evaluate_model(model, scaler, test):
    metadata = None
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)

    clean_test, X_test_df, y_test = _split_xy(test)
    X_test = scaler.transform(X_test_df)
    probs = model.predict_proba(X_test)[:, 1]
    preds = model.predict(X_test)
    metrics = compute_classification_metrics(y_test.to_numpy(), probs)

    print(f"Test games:  {metrics['test_games']}")
    print(f"Accuracy:    {metrics['accuracy']:.1%}")
    print(f"Log Loss:    {metrics['log_loss']:.4f}")
    print(f"Brier Score: {metrics['brier_score']:.4f}")
    print(f"ROC-AUC:     {metrics['roc_auc']:.4f}")
    print(f"Calibration: {metrics['calibration_ece']:.4f}")
    print(f"Baseline (always pick home): {metrics['baseline_home_win_rate']:.1%}")

    if metadata:
        print(f"Selected model: {metadata['best_model']}")


def save_model(model, scaler):
    _ensure_data_dir()
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    print("Model saved!")


def _save_leaderboard(leaderboard, best_model_name, cutoff):
    _ensure_data_dir()
    leaderboard.to_csv(LEADERBOARD_PATH, index=False)
    metadata = {
        "best_model": best_model_name,
        "production_model": best_model_name,
        "available_models": available_models(),
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "cutoff_date": cutoff,
        "features": FEATURES,
        "leaderboard_path": LEADERBOARD_PATH,
    }
    with open(METADATA_PATH, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)


def run():
    print("Loading features...")
    df = load_features()

    print("Splitting data...")
    train, test = split_data(df)
    print(f"  Train: {len(train)} games")
    print(f"  Test:  {len(test)} games")

    print("Training candidate models...")
    fitted, scaler, X_train, y_train = _fit_candidates(train)

    print("Evaluating candidate models...")
    leaderboard = _score_candidates(fitted, scaler, X_train, y_train, test)
    print(
        leaderboard[
            [
                "rank",
                "model",
                "accuracy",
                "log_loss",
                "brier_score",
                "roc_auc",
                "calibration_ece",
                "avg_confidence",
                "probability_std",
                "extreme_prediction_rate",
            ]
        ].to_string(index=False)
    )

    leaderboard_best = leaderboard.iloc[0]["model"]
    production_model_name = get_production_model_name()
    fitted_lookup = {item["model_name"]: item["model"] for item in fitted}
    if production_model_name in fitted_lookup:
        best_model_name = production_model_name
    else:
        print(
            f"Configured production model '{production_model_name}' is unavailable. "
            f"Falling back to leaderboard best '{leaderboard_best}'."
        )
        best_model_name = leaderboard_best

    best_model = fitted_lookup[best_model_name]
    cutoff = pd.to_datetime(test["GAME_DATE"]).min().strftime("%Y-%m-%d")
    _save_leaderboard(leaderboard, best_model_name, cutoff)

    print("\nEvaluating selected production model...")
    evaluate_model(best_model, scaler, test)

    print("Saving selected production model...")
    save_model(best_model, scaler)


if __name__ == "__main__":
    run()
