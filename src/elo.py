import sqlite3
import pandas as pd

# --- Config ---
DB_PATH = 'data/nba.db'
STARTING_ELO = 1500
K = 20
HOME_ADVANTAGE = 100  # home team gets a 100 point elo boost
MEAN_REVERSION = 0.25  # 25% regression to mean between seasonsS
SCALING_FACTOR=400

# expected_win_prob(home_elo, away_elo) calculates win probability for the home team based on elo ratings
def expected_win_prob(home_elo, away_elo):
    return 1 / (1 + 10 ** ((away_elo - home_elo) / SCALING_FACTOR))

# update_elo(home_elo, away_elo, home_win) updates elo for both teams after a game
def update_elo(home_elo, away_elo, home_win):
    # calculate expected outcome
    expected = expected_win_prob(home_elo + HOME_ADVANTAGE, away_elo)
    actual = 1 if home_win else 0

    # update ratings
    new_home_elo = home_elo + K * (actual - expected)
    new_away_elo = away_elo + K * ((1 - actual) - (1 - expected))

    return new_home_elo, new_away_elo

# apply_mean_reversion(ratings) applies a 'reset' to the elo rating for each team
def apply_mean_reversion(ratings):
    # regress all ratings 25% toward 1500 at start of new season
    return {
        team: rating * (1 - MEAN_REVERSION) + STARTING_ELO * MEAN_REVERSION
        for team, rating in ratings.items()
    }

# load_games() reads games from nba.db sorted chronologically
def load_games():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT GAME_ID, GAME_DATE, TEAM_ID, TEAM_ABBREVIATION, WL, MATCHUP, SEASON
        FROM games
        ORDER BY GAME_DATE ASC
    """, conn)
    conn.close()
    return df

# compute_elo() loops through all games updating elo ratings
def compute_elo():
    print("Loading games...")
    df = load_games()

    # initialize all teams at 1500
    ratings = {}
    elo_records = []
    current_season = None

    # get one row per game (home team only)
    home_games = df[df['MATCHUP'].str.contains('vs.')].copy()

    print(f"Computing Elo across {len(home_games)} games...")

    for _, game in home_games.iterrows():
        season = game['SEASON']
        game_id = game['GAME_ID']
        game_date = game['GAME_DATE']
        home_team_id = game['TEAM_ID']
        home_abbr = game['TEAM_ABBREVIATION']

        # get away team for this game
        away_row = df[(df['GAME_ID'] == game_id) & (df['MATCHUP'].str.contains('@'))]
        if len(away_row) == 0:
            continue

        away_team_id = away_row.iloc[0]['TEAM_ID']
        away_abbr = away_row.iloc[0]['TEAM_ABBREVIATION']

        # apply mean reversion at start of each new season
        if season != current_season:
            if current_season is not None:
                print(f"  New season {season} — applying mean reversion")
                ratings = apply_mean_reversion(ratings)
            current_season = season

        # initialize teams if first time seen
        if home_team_id not in ratings:
            ratings[home_team_id] = STARTING_ELO
        if away_team_id not in ratings:
            ratings[away_team_id] = STARTING_ELO

        # record elo BEFORE the game
        home_elo_before = ratings[home_team_id]
        away_elo_before = ratings[away_team_id]

        elo_records.append({
            'GAME_ID': game_id,
            'GAME_DATE': game_date,
            'HOME_TEAM_ID': home_team_id,
            'AWAY_TEAM_ID': away_team_id,
            'HOME_ELO': home_elo_before,
            'AWAY_ELO': away_elo_before,
            'ELO_DIFF': home_elo_before - away_elo_before
        })

        # update ratings after the game
        home_win = 1 if game['WL'] == 'W' else 0
        new_home_elo, new_away_elo = update_elo(home_elo_before, away_elo_before, home_win)
        ratings[home_team_id] = new_home_elo
        ratings[away_team_id] = new_away_elo

    # save to database
    elo_df = pd.DataFrame(elo_records)
    conn = sqlite3.connect(DB_PATH)
    elo_df.to_sql('elo', conn, if_exists='replace', index=False)
    conn.close()

    print(f"Saved {len(elo_df)} elo records to database")
    return ratings

# get_current_ratings() returns every team's most recent elo rating
def get_current_ratings():
    # returns the most recent elo rating for every team
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT HOME_TEAM_ID as TEAM_ID, HOME_ELO as ELO
        FROM elo
        WHERE GAME_DATE = (SELECT MAX(GAME_DATE) FROM elo)
    """, conn)
    conn.close()
    return dict(zip(df['TEAM_ID'], df['ELO']))

if __name__ == '__main__':
    final_ratings = compute_elo()
    print("\nCurrent team ratings:")
    sorted_ratings = sorted(final_ratings.items(), key=lambda x: x[1], reverse=True)
    for team_id, rating in sorted_ratings:
        print(f"  {team_id}: {rating:.1f}")