import json
import sqlite3

import numpy as np
import pandas as pd
from model import (
    DB_PATH,
    FEATURES,
    TARGET,
    compute_classification_metrics,
    get_production_model_name,
    load_features,
    split_data_by_season,
    train_selected_model,
)
from track import STARTING_BANKROLL, kelly_bet

TEST_SEASON = "2025-26"
RESULTS_PATH = "data/backtest_2025_26_bets.csv"
SUMMARY_PATH = "data/backtest_2025_26_summary.json"


def implied_prob(american_odds):
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return abs(american_odds) / (abs(american_odds) + 100)


def load_logged_odds():
    conn = sqlite3.connect(DB_PATH)
    table_exists = pd.read_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'", conn
    )
    if len(table_exists) == 0:
        conn.close()
        return pd.DataFrame(columns=["game_id", "bet_placed", "odds"])

    odds_logs = pd.read_sql(
        """
        SELECT game_id, bet_placed, odds
        FROM predictions
        WHERE odds IS NOT NULL AND bet_placed IS NOT NULL
        """,
        conn,
    )
    conn.close()
    odds_logs["game_id"] = odds_logs["game_id"].astype(str)
    return odds_logs.drop_duplicates(subset=["game_id"], keep="last")


def prepare_test_predictions(model, scaler, test):
    clean_test = test.dropna(subset=FEATURES).copy()
    X_test = scaler.transform(clean_test[FEATURES])
    home_probs = model.predict_proba(X_test)[:, 1]

    clean_test["home_prob"] = home_probs
    clean_test["away_prob"] = 1.0 - home_probs
    clean_test["model_pick"] = np.where(
        clean_test["home_prob"] >= clean_test["away_prob"],
        clean_test["HOME_TEAM_ABBREVIATION"],
        clean_test["AWAY_TEAM_ABBREVIATION"],
    )
    clean_test["GAME_ID"] = clean_test["GAME_ID"].astype(str)
    return clean_test


def run_betting_simulation(scored_test, odds_logs):
    merged = scored_test.merge(odds_logs, left_on="GAME_ID", right_on="game_id", how="inner")
    merged = merged.sort_values("GAME_DATE").reset_index(drop=True)

    summary = {
        "odds_logged_games": int(len(merged)),
        "side_compatible_games": 0,
        "bets_placed": 0,
        "wins": 0,
        "losses": 0,
        "total_wagered": 0.0,
        "total_profit_loss": 0.0,
        "final_bankroll": float(STARTING_BANKROLL),
        "roi": 0.0,
    }

    if len(merged) == 0:
        merged["bet_amount"] = []
        merged["profit_loss"] = []
        return merged, summary

    bankroll = float(STARTING_BANKROLL)
    bet_amounts = []
    profit_losses = []

    for _, row in merged.iterrows():
        if row["model_pick"] != row["bet_placed"]:
            bet_amounts.append(0.0)
            profit_losses.append(0.0)
            continue

        summary["side_compatible_games"] += 1

        best_prob = row["home_prob"] if row["model_pick"] == row["HOME_TEAM_ABBREVIATION"] else row["away_prob"]
        edge = best_prob - implied_prob(row["odds"])
        bet_amount = kelly_bet(best_prob, row["odds"], bankroll) if edge > 0 else 0.0

        if bet_amount <= 0:
            bet_amounts.append(0.0)
            profit_losses.append(0.0)
            continue

        summary["bets_placed"] += 1
        summary["total_wagered"] += float(bet_amount)

        actual_winner = row["HOME_TEAM_ABBREVIATION"] if int(row[TARGET]) == 1 else row["AWAY_TEAM_ABBREVIATION"]
        if actual_winner == row["model_pick"]:
            if row["odds"] > 0:
                profit_loss = bet_amount * (row["odds"] / 100)
            else:
                profit_loss = bet_amount * (100 / abs(row["odds"]))
            summary["wins"] += 1
        else:
            profit_loss = -bet_amount
            summary["losses"] += 1

        bankroll += float(profit_loss)
        bet_amounts.append(float(bet_amount))
        profit_losses.append(float(profit_loss))

    merged["bet_amount"] = bet_amounts
    merged["profit_loss"] = profit_losses

    summary["total_profit_loss"] = float(np.sum(profit_losses))
    summary["final_bankroll"] = float(bankroll)
    summary["roi"] = float((bankroll - STARTING_BANKROLL) / STARTING_BANKROLL)
    return merged, summary


def run():
    print(f"Loading features and splitting with test season={TEST_SEASON}...")
    df = load_features()
    train, test = split_data_by_season(df, TEST_SEASON)
    print(f"  Train games: {len(train)}")
    print(f"  Test games:  {len(test)}")

    if len(test) == 0:
        raise ValueError(f"No test rows found for season {TEST_SEASON}.")

    production_model_name = get_production_model_name()
    print(f"Training configured production model ({production_model_name})...")
    model, scaler, _, _, _ = train_selected_model(train, production_model_name)

    print("Scoring test season...")
    scored_test = prepare_test_predictions(model, scaler, test)
    metrics = compute_classification_metrics(scored_test[TARGET].to_numpy(), scored_test["home_prob"].to_numpy())

    print(f"Season metrics on {TEST_SEASON}:")
    print(f"  Accuracy:    {metrics['accuracy']:.1%}")
    print(f"  Log Loss:    {metrics['log_loss']:.4f}")
    print(f"  Brier Score: {metrics['brier_score']:.4f}")
    print(f"  ROC-AUC:     {metrics['roc_auc']:.4f}")
    print(f"  Calibration: {metrics['calibration_ece']:.4f}")

    print("Loading locally logged odds and running simulation...")
    odds_logs = load_logged_odds()
    sim_df, sim_summary = run_betting_simulation(scored_test, odds_logs)

    print("Simulation summary:")
    print(f"  Odds-logged games in season: {sim_summary['odds_logged_games']}")
    print(f"  Side-compatible games:       {sim_summary['side_compatible_games']}")
    print(f"  Bets placed:                 {sim_summary['bets_placed']}")
    print(f"  Wins / Losses:               {sim_summary['wins']} / {sim_summary['losses']}")
    print(f"  Total wagered:               ${sim_summary['total_wagered']:.2f}")
    print(f"  Total P/L:                   ${sim_summary['total_profit_loss']:.2f}")
    print(f"  Final bankroll:              ${sim_summary['final_bankroll']:.2f}")
    print(f"  ROI:                         {sim_summary['roi']:.2%}")

    sim_df.to_csv(RESULTS_PATH, index=False)
    summary = {
        "test_season": TEST_SEASON,
        "model": production_model_name,
        "metrics": metrics,
        "simulation": sim_summary,
        "results_path": RESULTS_PATH,
    }
    with open(SUMMARY_PATH, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print(f"Saved detailed simulation rows to {RESULTS_PATH}")
    print(f"Saved summary to {SUMMARY_PATH}")


if __name__ == "__main__":
    run()
