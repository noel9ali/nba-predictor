import pandas as pd
from database import select_rows, upsert_rows

# --- Config ---
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

# load_games() reads games from Supabase sorted chronologically
def load_games():
    return select_rows(
        "games",
        columns="GAME_ID,GAME_DATE,TEAM_ID,TEAM_ABBREVIATION,WL,MATCHUP,SEASON",
        order_by=["GAME_DATE", "GAME_ID", "TEAM_ID"],
    )

# compute_elo() loops through all games updating elo ratings
def compute_elo():
    print("Loading games...")
    df = load_games()

    # pre-build away team lookup to avoid slow per-row filtering
    away_df = df[df['MATCHUP'].str.contains('@')].drop_duplicates(subset='GAME_ID').set_index('GAME_ID')
    away_lookup = away_df[['TEAM_ID', 'TEAM_ABBREVIATION']].to_dict('index')

    # get home games only sorted by date
    home_games = df[df['MATCHUP'].str.contains('vs.')].copy()

    # initialize
    ratings = {}
    elo_records = []
    current_season = None

    print(f"Computing Elo across {len(home_games)} games...")

    for _, game in home_games.iterrows():
        season = game['SEASON']
        game_id = game['GAME_ID']
        game_date = game['GAME_DATE']
        home_team_id = game['TEAM_ID']

        # fast lookup instead of filtering entire dataframe
        if game_id not in away_lookup:
            continue

        away_team_id = away_lookup[game_id]['TEAM_ID']

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

    # Save pre-game ratings without deleting historical rows.
    elo_df = pd.DataFrame(elo_records)
    upsert_rows("elo", elo_df.to_dict("records"), conflict_columns=["GAME_ID"])

    print(f"Saved {len(elo_df)} elo records to database")
    return ratings

# get_current_ratings() returns every team's most recent elo rating
def get_current_ratings():
    # returns the most recent elo rating for every team
    elo = select_rows(
        "elo",
        columns="GAME_ID,GAME_DATE,HOME_TEAM_ID,AWAY_TEAM_ID,HOME_ELO,AWAY_ELO",
        order_by=["GAME_DATE", "GAME_ID"],
        descending=True,
    )
    if len(elo) == 0:
        return {}
    games = select_rows(
        "games",
        columns="GAME_ID,TEAM_ID,MATCHUP,WL",
        order_by=["GAME_ID", "TEAM_ID"],
    )
    home_games = games[games["MATCHUP"].str.contains("vs.", na=False)]
    outcomes = home_games.set_index("GAME_ID")["WL"].to_dict()

    ratings = {}
    for _, game in elo.iterrows():
        home_id = game["HOME_TEAM_ID"]
        away_id = game["AWAY_TEAM_ID"]
        game_id = game["GAME_ID"]
        home_elo, away_elo = update_elo(
            game["HOME_ELO"],
            game["AWAY_ELO"],
            outcomes.get(game_id) == "W",
        )
        ratings.setdefault(home_id, home_elo)
        ratings.setdefault(away_id, away_elo)
    return ratings

def get_last_elo_date():
    df = select_rows(
        "elo",
        columns="GAME_DATE",
        order_by=["GAME_DATE", "GAME_ID"],
        descending=True,
        limit=1,
    )
    return None if len(df) == 0 else df["GAME_DATE"].iloc[0]

if __name__ == '__main__':
    final_ratings = compute_elo()
    print("\nCurrent team ratings:")
    sorted_ratings = sorted(final_ratings.items(), key=lambda x: x[1], reverse=True)
    for team_id, rating in sorted_ratings:
        print(f"  {team_id}: {rating:.1f}")