import sqlite3
import joblib
import pandas as pd
from nba_api.stats.endpoints import scoreboardv3
from datetime import date
from track import setup_tables, save_prediction, kelly_bet, get_current_bankroll
from odds import get_tonights_odds
from elo import get_current_ratings

# --- Config ---
DB_PATH = 'data/nba.db'
FEATURES = [
    'HOME_roll_PTS', 'HOME_roll_FG_PCT', 'HOME_roll_REB', 'HOME_roll_AST', 'HOME_roll_TOV', 'HOME_roll_STOCKS',
    'AWAY_roll_PTS', 'AWAY_roll_FG_PCT', 'AWAY_roll_REB', 'AWAY_roll_AST', 'AWAY_roll_TOV', 'AWAY_roll_STOCKS',
    'rest_diff',
    'HOME_ELO', 'AWAY_ELO', 'ELO_DIFF'
]

# load_model() loads a trained model and scaler
def load_model():
    model  = joblib.load('data/model.pkl')
    scaler = joblib.load('data/scaler.pkl')
    return model, scaler

# get_todays_games() fetches today's games from nba_api. Returns a dataframe with one
#   game per row
def get_todays_games():
    today = date.today().strftime('%Y-%m-%d')
    board = scoreboardv3.ScoreboardV3(game_date=today)
    
    games = board.get_data_frames()[1]  # game header
    teams = board.get_data_frames()[2]  # team info

    # split into separate rows for home and away to be merged
    away_teams = teams.groupby('gameId').first().reset_index()
    home_teams = teams.groupby('gameId').last().reset_index()

    # merge into one row per game
    merged = games[['gameId']].drop_duplicates()
    merged = merged.merge(home_teams[['gameId', 'teamId', 'teamTricode']], on='gameId')
    merged = merged.rename(columns={'teamId': 'HOME_TEAM_ID', 'teamTricode': 'HOME_TEAM_ABBREVIATION'})
    merged = merged.merge(away_teams[['gameId', 'teamId', 'teamTricode']], on='gameId')
    merged = merged.rename(columns={'teamId': 'VISITOR_TEAM_ID', 'teamTricode': 'VISITOR_TEAM_ABBREVIATION'})

    return merged

# get_team_rolling_stats() looks up rolling averages for a team's past 10 games
def get_team_rolling_stats(team_id, prefix):
    conn = sqlite3.connect(DB_PATH)
    query = f"""
        SELECT {prefix}_roll_PTS, {prefix}_roll_FG_PCT, 
               {prefix}_roll_REB, {prefix}_roll_AST, {prefix}_roll_TOV,
               {prefix}_roll_STOCKS, GAME_DATE
        FROM features
        WHERE {prefix}_TEAM_ID = {team_id}
        ORDER BY GAME_DATE DESC
        LIMIT 1
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df

# get_rest_days() calculates the amount of days since last game for a given team
def get_rest_days(team_id, prefix):
    conn = sqlite3.connect(DB_PATH)
    query = f"""
        SELECT GAME_DATE
        FROM features
        WHERE {prefix}_TEAM_ID = {team_id}
        ORDER BY GAME_DATE DESC
        LIMIT 1
    """
    df = pd.read_sql(query, conn)
    conn.close()
    if len(df) == 0:
        return 2  # default if no data
    last_game = pd.to_datetime(df['GAME_DATE'].iloc[0])
    today = pd.Timestamp(date.today())
    return (today - last_game).days

# match_odds() finds the odds for a given game from the odds dictionary
#   using team abbreviations to match against full team names
def match_odds(home_abbr, away_abbr, odds_dict):
    from odds import ABBR_MAP
    
    home_full = ABBR_MAP.get(home_abbr)
    away_full = ABBR_MAP.get(away_abbr)

    if not home_full or not away_full:
        return None

    # try normal order first
    result = odds_dict.get((home_full, away_full))
    if result:
        return result

    # try reversed order — if found, swap home and away odds
    result = odds_dict.get((away_full, home_full))
    if result:
        return {
            'home_odds': result['away_odds'],
            'away_odds': result['home_odds'],
            'home_book': result['away_book'],
            'away_book': result['home_book']
        }

    return None

# implied_prob() converts american odds to implied probability
def implied_prob(american_odds):
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)

def run():
    # load the trained model and scaler
    print("Loading model...")
    model, scaler = load_model()

    # load current elo ratings for all teams
    print("Loading Elo ratings...")
    elo_ratings = get_current_ratings()

    # fetch tonight's games
    print("Fetching today's games...")
    games = get_todays_games()

    # end early if no games today
    if len(games) == 0:
        print("No games today.")
        return

    # fetch real-time odds from The Odds API
    print("Fetching odds...")
    odds_dict = get_tonights_odds()

    # ADD THIS HERE
    print("Odds dictionary keys:")
    for key in odds_dict.keys():
        print(f"  {key}")

    print(f"Found {len(games)} games\n")
    print("=" * 45)

    # loop through each game tonight
    for _, game in games.iterrows():

        # get team IDs and abbreviations
        home_id = game['HOME_TEAM_ID']
        away_id = game['VISITOR_TEAM_ID']
        home_abbr = game['HOME_TEAM_ABBREVIATION'] if 'HOME_TEAM_ABBREVIATION' in game else home_id
        away_abbr = game['VISITOR_TEAM_ABBREVIATION'] if 'VISITOR_TEAM_ABBREVIATION' in game else away_id

        # get most recent rolling stats from the database
        home_stats = get_team_rolling_stats(home_id, 'HOME')
        away_stats = get_team_rolling_stats(away_id, 'AWAY')

        # skip game if missing data for either team
        if len(home_stats) == 0 or len(away_stats) == 0:
            print(f"{away_abbr} @ {home_abbr} — not enough data")
            continue

        # get rest days
        home_rest = get_rest_days(home_id, 'HOME')
        away_rest = get_rest_days(away_id, 'AWAY')
        rest_diff = home_rest - away_rest

        # get elo ratings for both teams
        home_elo = elo_ratings.get(home_id, 1500)
        away_elo = elo_ratings.get(away_id, 1500)
        elo_diff = home_elo - away_elo

        # assemble feature row to match format of training
        row = {
            'HOME_roll_PTS':    home_stats['HOME_roll_PTS'].iloc[0],
            'HOME_roll_FG_PCT': home_stats['HOME_roll_FG_PCT'].iloc[0],
            'HOME_roll_REB':    home_stats['HOME_roll_REB'].iloc[0],
            'HOME_roll_AST':    home_stats['HOME_roll_AST'].iloc[0],
            'HOME_roll_TOV':    home_stats['HOME_roll_TOV'].iloc[0],
            'HOME_roll_STOCKS': home_stats['HOME_roll_STOCKS'].iloc[0],
            'AWAY_roll_PTS':    away_stats['AWAY_roll_PTS'].iloc[0],
            'AWAY_roll_FG_PCT': away_stats['AWAY_roll_FG_PCT'].iloc[0],
            'AWAY_roll_REB':    away_stats['AWAY_roll_REB'].iloc[0],
            'AWAY_roll_AST':    away_stats['AWAY_roll_AST'].iloc[0],
            'AWAY_roll_TOV':    away_stats['AWAY_roll_TOV'].iloc[0],
            'AWAY_roll_STOCKS': away_stats['AWAY_roll_STOCKS'].iloc[0],
            'rest_diff':        rest_diff,
            'HOME_ELO':         home_elo,
            'AWAY_ELO':         away_elo,
            'ELO_DIFF':         elo_diff
        }

        # scale features and run through the model
        X = pd.DataFrame([row])[FEATURES]
        X_scaled = scaler.transform(X)
        prob = model.predict_proba(X_scaled)[0]

        # convert calculated probabilities to percentages
        home_prob = prob[1] * 100
        away_prob = prob[0] * 100

        # determine predicted winner
        predicted_winner = home_abbr if home_prob > away_prob else away_abbr

        # look up real odds for this game
        game_odds = match_odds(home_abbr, away_abbr, odds_dict)

        if game_odds:
            # use real odds and calculate edge
            bet_odds = game_odds['home_odds'] if predicted_winner == home_abbr else game_odds['away_odds']
            bet_book = game_odds['home_book'] if predicted_winner == home_abbr else game_odds['away_book']
            best_prob = (home_prob if predicted_winner == home_abbr else away_prob) / 100
            implied = implied_prob(bet_odds)
            edge = best_prob - implied

            # only bet if model has a real edge over the market
            bankroll = get_current_bankroll()
            bet_amount = kelly_bet(best_prob, bet_odds, bankroll) if edge > 0 else 0
            bet_team = predicted_winner if bet_amount > 0 else None
        else:
            # no odds available, skip the game
            print(f"{away_abbr} @ {home_abbr} - no odds available :(, skipping")
            continue

        # print prediction
        print(f"{away_abbr} @ {home_abbr}")
        print(f"  {home_abbr} win prob: {home_prob:.1f}%")
        print(f"  {away_abbr} win prob: {away_prob:.1f}%")
        print(f"  Predicted winner: {predicted_winner}")
        if game_odds:
            print(f"  Line: {bet_odds} ({bet_book})")
            print(f"  Edge: {edge * 100:.1f}%" if edge is not None else "  Edge: N/A")
        if bet_amount > 0:
            print(f"  Simulated bet: ${bet_amount:.2f} on {bet_team}")
        else:
            print(f"  No bet — insufficient edge")
        print()

        # log to database
        save_prediction(
            game_id          = game['gameId'],
            game_date        = str(date.today()),
            home_team        = home_abbr,
            away_team        = away_abbr,
            home_prob        = home_prob / 100,
            away_prob        = away_prob / 100,
            predicted_winner = predicted_winner,
            bet_placed       = bet_team,
            bet_amount       = bet_amount,
            odds             = bet_odds
        )

if __name__ == '__main__':
    setup_tables()
    run()