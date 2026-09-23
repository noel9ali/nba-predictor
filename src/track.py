import pandas as pd
from datetime import date, timedelta
from nba_api.stats.endpoints import scoreboardv3
from database import (
    DatabaseError,
    DuplicateRecordError,
    MissingTableError,
    insert_rows,
    normalize_game_id,
    select_rows,
    upsert_rows,
    update_rows,
)

# --- Config ---
STARTING_BANKROLL = 1000.00
MAX_DECIMAL_ODDS = 5.0
BANKROLL_MIGRATION_HINT = "supabase/migrations/20260923000400_bankroll.sql"


def _require_bankroll_table(callback):
    try:
        return callback()
    except MissingTableError:
        raise DatabaseError(
            f"bankroll table is missing: apply {BANKROLL_MIGRATION_HINT}"
        ) from None


# setup_tables() verifies the migrated tables and seeds the initial bankroll row.
def setup_tables():
    existing = _require_bankroll_table(
        lambda: select_rows("bankroll", columns="date,balance", limit=1)
    )
    if len(existing) == 0:
        _require_bankroll_table(
            lambda: upsert_rows(
                "bankroll",
                [{"date": date.today().isoformat(), "balance": STARTING_BANKROLL}],
                conflict_columns=["date"],
            )
        )

# get_current_bankroll() looks up most recent balance from bankroll table
def get_current_bankroll():
    df = _require_bankroll_table(
        lambda: select_rows(
            "bankroll",
            columns="balance",
            order_by="date",
            descending=True,
            limit=1,
        )
    )
    if len(df) == 0:
        raise DatabaseError("Reading bankroll failed: no bankroll record exists")
    return df['balance'].iloc[0]

# save_prediction() stores relevant information for each game in prediction table
def save_prediction(game_id, game_date, home_team, away_team,
                    home_prob, away_prob, predicted_winner,
                    bet_placed, bet_amount, odds):
    game_id = normalize_game_id(game_id)
    existing = select_rows(
        "predictions",
        columns="game_id",
        filters=[("game_id", "eq", game_id)],
        limit=1,
    )
    if len(existing) > 0:
        print(f"  Prediction already logged for {game_id}, skipping.")
        return
    row = {
        "game_id": game_id,
        "game_date": game_date,
        "home_team": home_team,
        "away_team": away_team,
        "home_win_prob": float(home_prob),
        "away_win_prob": float(away_prob),
        "predicted_winner": predicted_winner,
        "actual_winner": None,
        "correct": None,
        "bet_placed": bet_placed,
        "bet_amount": float(bet_amount),
        "odds": int(odds) if odds is not None else None,
        "profit_loss": None,
    }
    try:
        insert_rows("predictions", [row])
    except DuplicateRecordError:
        print(f"  Prediction already logged for {game_id}, skipping.")

# kelly_bet() calculates bet size using the Kelly formula. 
#   Uses fraction paramater to scale aggresion.
def kelly_bet(prob, odds, bankroll, fraction=0.25):
    # convert american odds to decimal
    if odds > 0:
        decimal_odds = (odds / 100) + 1
    else:
        decimal_odds = (100 / abs(odds)) + 1

    if decimal_odds > MAX_DECIMAL_ODDS:
        return 0

    edge = (prob * decimal_odds) - 1
    kelly = edge / (decimal_odds - 1)

    # only bet if there is a positive edge
    if kelly <= 0:
        return 0

    # fractional kelly to scale aggression
    bet = kelly * fraction * bankroll

    # cap bet at 5% of bankroll
    return min(bet, bankroll * 0.05)

# update_results() fetches yesterday's game results, updates the 
#   corresponding prediction rows, and updates bankroll table.
def update_results():
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    pending = select_rows(
        "predictions",
        filters=[
            ("game_date", "eq", yesterday),
            ("actual_winner", "is", "null"),
        ],
        order_by="game_id",
    )

    if len(pending) == 0:
        print("No pending predictions to update.")
        return

    # fetch yesterday's results
    board = scoreboardv3.ScoreboardV3(game_date=yesterday)
    teams = board.get_data_frames()[2]

    print(f"Updating {len(pending)} predictions...")

    normalized_scoreboard_ids = teams['gameId'].map(normalize_game_id)

    # process all games first, update predictions table only
    for _, pred in pending.iterrows():
        pred_game_id = normalize_game_id(pred['game_id'])
        game_teams = teams[normalized_scoreboard_ids == pred_game_id]
        if len(game_teams) == 0:
            continue

        # figure out who won
        game_teams = game_teams.copy()
        winner = game_teams.loc[game_teams['score'].astype(float).idxmax(), 'teamTricode']
        correct = 1 if winner == pred['predicted_winner'] else 0

        # calculate profit/loss
        bet_amount = float(pred['bet_amount'])
        if pred['bet_placed'] is None or bet_amount == 0:
            profit_loss = 0
        elif winner == pred['bet_placed']:
            odds = int(float(pred['odds']))
            if odds > 0:
                profit_loss = bet_amount * (odds / 100)
            else:
                profit_loss = bet_amount * (100 / abs(odds))
        else:
            profit_loss = -bet_amount

        # update prediction row
        update_rows(
            "predictions",
            {
                "actual_winner": winner,
                "correct": correct,
                "profit_loss": profit_loss,
            },
            filters=[("game_id", "eq", pred_game_id)],
        )

        result = "✓" if correct else "✗"
        print(f"  {result} {pred['away_team']} @ {pred['home_team']} — predicted {pred['predicted_winner']}, actual {winner}, P/L: ${profit_loss:.2f}")

    # recalculate bankroll from scratch based on all completed predictions
    completed = select_rows(
        "predictions",
        columns="profit_loss",
        filters=[("profit_loss", "not_is", "null")],
        order_by="game_id",
    )
    total_pl = completed["profit_loss"].sum() if len(completed) else 0
    new_balance = STARTING_BANKROLL + total_pl

    # insert new bankroll entry for yesterday
    upsert_rows(
        "bankroll",
        [{"date": yesterday, "balance": float(new_balance)}],
        conflict_columns=["date"],
    )

    print(f"\nBankroll updated: ${new_balance:.2f}")

# print_summary() reads all completed predictions from the database and prints a summary
def print_summary():
    preds = select_rows(
        "predictions",
        filters=[("correct", "not_is", "null")],
        order_by="game_id",
    )
    bankroll = _require_bankroll_table(
        lambda: select_rows(
            "bankroll",
            order_by="date",
            descending=True,
            limit=1,
        )
    )

    if len(preds) == 0:
        print("No completed predictions yet.")
        return

    total = len(preds)
    correct = preds['correct'].sum()
    accuracy = correct / total
    total_pl = preds['profit_loss'].sum()
    current_bankroll = bankroll['balance'].iloc[0] if len(bankroll) else STARTING_BANKROLL

    print("\n=== Paper Trading Summary ===")
    print(f"Games predicted:    {total}")
    print(f"Correct:            {correct}")
    print(f"Accuracy:           {accuracy:.1%}")
    print(f"Total P/L:          ${total_pl:.2f}")
    print(f"Starting bankroll:  ${STARTING_BANKROLL:.2f}")
    print(f"Current bankroll:   ${current_bankroll:.2f}")
    print(f"ROI:                {((current_bankroll - STARTING_BANKROLL) / STARTING_BANKROLL):.1%}")

if __name__ == '__main__':
    setup_tables()
    update_results()
    print("Tracking tables ready.")
    print_summary()