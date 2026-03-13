import sqlite3
import pandas as pd

# --- Config ---
DB_PATH = 'data/nba.db'
ROLLING_WINDOW = 10

def load_games():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('SELECT * FROM games', conn)
    conn.close()
    return df

def label_home_away(df):
    df['HOME'] = df['MATCHUP'].apply(lambda x: 1 if 'vs.' in x else 0)
    return df

def make_game_rows(df):
    home = df[df['HOME'] == 1].copy()
    away = df[df['HOME'] == 0].copy()

    home = home.add_prefix('HOME_')
    away = away.add_prefix('AWAY_')

    home = home.rename(columns={'HOME_GAME_ID': 'GAME_ID', 'HOME_GAME_DATE': 'GAME_DATE'})
    away = away.rename(columns={'AWAY_GAME_ID': 'GAME_ID'})

    merged = pd.merge(home, away, on='GAME_ID')
    merged['HOME_STOCKS'] = merged['HOME_STL'] + merged['HOME_BLK']
    merged['AWAY_STOCKS'] = merged['AWAY_STL'] + merged['AWAY_BLK']
    merged['home_win'] = (merged['HOME_WL'] == 'W').astype(int)
    return merged

# TODO
# merge_stocks() merges steals and blocks into a singular category titled stocks
# def make_stocks():

def add_rolling_stats(df):
    df = df.sort_values('GAME_DATE').copy()
    
    cols_to_roll = ['PTS', 'FG_PCT', 'REB', 'AST', 'TOV', 'STOCKS']
    
    for col in cols_to_roll:
        for prefix in ['HOME', 'AWAY']:
            team_col = f'{prefix}_{col}'
            roll_col = f'{prefix}_roll_{col}'
            df[roll_col] = (
                df.groupby(f'{prefix}_TEAM_ID')[team_col]
                .transform(lambda x: x.shift(1).rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).mean())
            )
    
    # drop rows where rolling window isn't full yet
    df = df.dropna(subset=[f'HOME_roll_{c}' for c in cols_to_roll])
    return df

def add_rest_days(df):
    df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
    
    for prefix in ['HOME', 'AWAY']:
        df[f'{prefix}_rest_days'] = (
            df.groupby(f'{prefix}_TEAM_ID')['GAME_DATE']
            .transform(lambda x: x.diff().dt.days)
        )
    
    df['rest_diff'] = df['HOME_rest_days'] - df['AWAY_rest_days']
    return df

def add_elo(df):
    conn = sqlite3.connect(DB_PATH)
    elo = pd.read_sql("SELECT * FROM elo", conn)
    conn.close()

    # merge elo to features table
    df = df.merge(
        elo[['GAME_ID', 'HOME_ELO', 'AWAY_ELO', 'ELO_DIFF']],
        on='GAME_ID',
        how='left'
    )

    return df

def run():
    print("Loading games...")
    df = load_games()

    print("Labelling home and away...")
    df = label_home_away(df)

    print("Merging into one row per game...")
    games = make_game_rows(df)

    print("Adding rolling stats...")
    games = add_rolling_stats(games)

    print("Adding rest days...")
    games = add_rest_days(games)

    print("Adding Elo ratings...")
    games = add_elo(games)

    print(f"\nTotal games after rolling window: {len(games)}")
    print(f"Home win rate: {games['home_win'].mean():.1%}")
    print(games[['GAME_DATE', 'HOME_TEAM_ABBREVIATION', 'AWAY_TEAM_ABBREVIATION',
                  'HOME_roll_PTS', 'AWAY_roll_PTS', 'HOME_ELO', 'AWAY_ELO', 'ELO_DIFF', 'home_win']].head(10))

    print("Saving features to database...")
    conn = sqlite3.connect(DB_PATH)
    games.to_sql('features', conn, if_exists='replace', index=False)
    conn.close()
    print("Saved!")

if __name__ == '__main__':
    run()