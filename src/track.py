import pandas as pd
from datetime import date, timedelta
from nba_api.stats.endpoints import scoreboardv3
from console import force_utf8_stdio
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
# Bound how many stale pending predictions a single run will settle; a backlog
# larger than this is cleared over successive runs (update_results() is
# idempotent, so re-running is always safe).
MAX_PENDING_PER_RUN = 500
# ScoreboardV3's GameHeader.gameStatus: 1=scheduled, 2=live, 3=final.
FINAL_GAME_STATUS = 3


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

# update_results() fetches results for every prediction still pending from
#   before today (not just yesterday), updates the corresponding prediction
#   rows, and recomputes the bankroll for every date that got settled.
def update_results():
    today = date.today().strftime('%Y-%m-%d')

    # game_date < today (not "== yesterday"): a row missed on one run must
    # stay eligible on every later run until it's settled. actual_winner is
    # null makes this idempotent -- a settled row is never selected again.
    # Select the MOST RECENT pending rows first (descending), then process
    # them oldest-first below: a permanently-stuck old row (e.g. a cancelled
    # game that never appears in any future scoreboard) can then never
    # occupy every cap slot and starve genuinely newer, settleable rows.
    pending = select_rows(
        "predictions",
        filters=[
            ("game_date", "lt", today),
            ("actual_winner", "is", "null"),
        ],
        order_by="game_date",
        descending=True,
        limit=MAX_PENDING_PER_RUN,
    )

    if len(pending) == 0:
        print("No pending predictions to update.")
        return

    print(f"Updating {len(pending)} predictions...")

    settled_dates = set()

    # one scoreboard fetch per distinct outstanding date, oldest first
    for game_date, group in pending.groupby("game_date", sort=True):
        board = scoreboardv3.ScoreboardV3(game_date=game_date)
        frames = board.get_data_frames()
        headers = frames[1]
        teams = frames[2]
        normalized_scoreboard_ids = teams['gameId'].map(normalize_game_id)
        # LineScore lists every game scheduled for the date regardless of
        # status, so presence there alone can't tell a finished game from a
        # scheduled/live/postponed one -- only GameHeader carries gameStatus.
        final_game_ids = set(
            headers.loc[headers['gameStatus'] == FINAL_GAME_STATUS, 'gameId'].map(normalize_game_id)
        )

        for _, pred in group.iterrows():
            pred_game_id = normalize_game_id(pred['game_id'])
            if pred_game_id not in final_game_ids:
                # scheduled, live, postponed, or missing from GameHeader
                # entirely -- leave pending, retried next run
                continue

            game_teams = teams[normalized_scoreboard_ids == pred_game_id]
            if len(game_teams) == 0:
                continue

            # figure out who won
            game_teams = game_teams.copy()
            scores = pd.to_numeric(game_teams['score'], errors='coerce')
            if scores.isna().any() or scores.max() == scores.min():
                # defensive: a "final" game with equal or missing scores
                # would fabricate a winner via idxmax's arbitrary tie-break
                # -- leave pending and retry rather than guess.
                print(f"  Warning: game {pred_game_id} is final but its scores are equal or missing; leaving pending.")
                continue
            winner = game_teams.loc[scores.idxmax(), 'teamTricode']
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
            settled_dates.add(game_date)

            result = "✓" if correct else "✗"
            print(f"  {result} {pred['away_team']} @ {pred['home_team']} — predicted {pred['predicted_winner']}, actual {winner}, P/L: ${profit_loss:.2f}")

    if not settled_dates:
        print("No predictions were settled (all pending games are postponed or not yet final).")
        return

    _recompute_bankroll(settled_dates)


# _recompute_bankroll() rewrites the bankroll row for every date from the
#   earliest affected date onward, in chronological order, matching the
#   cumulative-sum formula in migration 20260923001100_backfill.sql (starting
#   bankroll + running total of settled profit_loss, ordered by game_date).
#   Settling an EARLIER date shifts the cumulative balance of every LATER
#   date too, so rewriting only the dates settled in this run would leave
#   every later bankroll row (including the latest one the dashboard/SMS
#   read) stale.
def _recompute_bankroll(affected_dates):
    completed = select_rows(
        "predictions",
        columns="game_date,profit_loss",
        filters=[("profit_loss", "not_is", "null")],
        order_by="game_date",
    )
    completed = completed.copy()
    completed["profit_loss"] = pd.to_numeric(completed["profit_loss"], errors="coerce").fillna(0)
    daily_totals = completed.groupby("game_date")["profit_loss"].sum()
    running_balance = STARTING_BANKROLL + daily_totals.cumsum()

    earliest_affected = min(affected_dates)
    stale_dates = sorted(d for d in running_balance.index if d >= earliest_affected)
    if not stale_dates:
        return

    rows = [{"date": d, "balance": float(running_balance.loc[d])} for d in stale_dates]
    upsert_rows("bankroll", rows, conflict_columns=["date"])
    print(f"Bankroll updated for {len(rows)} date(s) from {stale_dates[0]}: ${rows[-1]['balance']:.2f}")

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
    force_utf8_stdio()
    setup_tables()
    update_results()
    print("Tracking tables ready.")
    print_summary()