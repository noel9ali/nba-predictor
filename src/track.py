import sqlite3
import joblib
import pandas as pd
from datetime import date, timedelta
from nba_api.stats.endpoints import scoreboardv3

# --- Config ---
DB_PATH = 'data/nba.db'
STARTING_BANKROLL = 1000.00

# setup_tables() creates two tables in the database for predictions and bankroll
def setup_tables():
    conn = sqlite3.connect(DB_PATH)
    
    # table to store predictions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            game_id         TEXT,
            game_date       TEXT,
            home_team       TEXT,
            away_team       TEXT,
            home_win_prob   REAL,
            away_win_prob   REAL,
            predicted_winner TEXT,
            actual_winner   TEXT,
            correct         INTEGER,
            bet_placed      TEXT,
            bet_amount      REAL,
            odds            REAL,
            profit_loss     REAL
        )
    """)

    # table to track bankroll over time
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bankroll (
            date            TEXT,
            balance         REAL
        )
    """)

    # insert starting bankroll if empty
    existing = pd.read_sql("SELECT * FROM bankroll", conn)
    if len(existing) == 0:
        conn.execute(f"INSERT INTO bankroll VALUES ('{date.today()}', {STARTING_BANKROLL})")

    conn.commit()
    conn.close()

# get_current_bankroll() looks up most recent balance from bankroll table
def get_current_bankroll():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT balance FROM bankroll ORDER BY date DESC LIMIT 1", conn)
    conn.close()
    return df['balance'].iloc[0]

# save_prediction() stores relevant information for each game in prediction table
def save_prediction(game_id, game_date, home_team, away_team, 
                    home_prob, away_prob, predicted_winner,
                    bet_placed, bet_amount, odds):
    conn = sqlite3.connect(DB_PATH)

    # check if prediction already exists for this game
    existing = pd.read_sql(f"SELECT * FROM predictions WHERE game_id = '{game_id}'", conn)
    if len(existing) > 0:
        print(f"  Prediction already logged for {game_id}, skipping.")
        conn.close()
        return

    conn.execute("""
        INSERT INTO predictions 
        (game_id, game_date, home_team, away_team, home_win_prob, away_win_prob,
         predicted_winner, actual_winner, correct, bet_placed, bet_amount, odds, profit_loss)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, NULL)
    """, (game_id, game_date, home_team, away_team, home_prob, away_prob,
          predicted_winner, bet_placed, bet_amount, odds))

    conn.commit()
    conn.close()

# kelly_bet() calculates bet size using the Kelly formula. 
#   Uses fraction paramater to scale aggresion.
def kelly_bet(prob, odds, bankroll, fraction=0.25):
    # convert american odds to decimal
    if odds > 0:
        decimal_odds = (odds / 100) + 1
    else:
        decimal_odds = (100 / abs(odds)) + 1

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
    
    conn = sqlite3.connect(DB_PATH)
    pending = pd.read_sql(f"""
        SELECT * FROM predictions 
        WHERE game_date = '{yesterday}' 
        AND actual_winner IS NULL
    """, conn)
    conn.close()

    if len(pending) == 0:
        print("No pending predictions to update.")
        return

    # fetch yesterday's results
    board = scoreboardv3.ScoreboardV3(game_date=yesterday)
    teams = board.get_data_frames()[2]

    print(f"Updating {len(pending)} predictions...")

    # process all games first, update predictions table only
    for _, pred in pending.iterrows():
        game_teams = teams[teams['gameId'] == pred['game_id']]
        if len(game_teams) == 0:
            continue

        # figure out who won
        game_teams = game_teams.copy()
        winner = game_teams.loc[game_teams['score'].astype(float).idxmax(), 'teamTricode']
        correct = 1 if winner == pred['predicted_winner'] else 0

        # calculate profit/loss
        if pred['bet_placed'] is None or pred['bet_amount'] == 0:
            profit_loss = 0
        elif winner == pred['bet_placed']:
            odds = pred['odds']
            if odds > 0:
                profit_loss = pred['bet_amount'] * (odds / 100)
            else:
                profit_loss = pred['bet_amount'] * (100 / abs(odds))
        else:
            profit_loss = -pred['bet_amount']

        # update prediction row
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            UPDATE predictions 
            SET actual_winner = ?, correct = ?, profit_loss = ?
            WHERE game_id = ?
        """, (winner, correct, profit_loss, pred['game_id']))
        conn.commit()
        conn.close()

        result = "✓" if correct else "✗"
        print(f"  {result} {pred['away_team']} @ {pred['home_team']} — predicted {pred['predicted_winner']}, actual {winner}, P/L: ${profit_loss:.2f}")

    # recalculate bankroll from scratch based on all completed predictions
    conn = sqlite3.connect(DB_PATH)
    result = pd.read_sql("""
        SELECT SUM(profit_loss) as total 
        FROM predictions 
        WHERE profit_loss IS NOT NULL
    """, conn).iloc[0, 0]
    conn.close()

    total_pl = result if result is not None else 0
    new_balance = STARTING_BANKROLL + total_pl

    # insert new bankroll entry for yesterday
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"INSERT INTO bankroll VALUES ('{yesterday}', {new_balance})")
    conn.commit()
    conn.close()

    print(f"\nBankroll updated: ${new_balance:.2f}")

# print_summary() reads all completed predictions from the database and prints a summary 
def print_summary():
    conn = sqlite3.connect(DB_PATH)
    preds = pd.read_sql("SELECT * FROM predictions WHERE correct IS NOT NULL", conn)
    bankroll = pd.read_sql("SELECT * FROM bankroll ORDER BY date DESC, rowid DESC LIMIT 1", conn)
    conn.close()

    if len(preds) == 0:
        print("No completed predictions yet.")
        return

    total = len(preds)
    correct = preds['correct'].sum()
    accuracy = correct / total
    total_pl = preds['profit_loss'].sum()
    current_bankroll = bankroll['balance'].iloc[0]

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