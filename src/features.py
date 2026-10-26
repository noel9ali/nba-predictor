import pandas as pd
from console import force_utf8_stdio
from database import select_rows, upsert_rows

# --- Config ---
ROLLING_WINDOW = 10

def load_games():
    return select_rows("games", order_by=["GAME_DATE", "GAME_ID", "TEAM_ID"])

REST_CAP = 7  # days; a longer gap (season opener, All-Star break) is the same "fully rested" to the model

def completed_games(df):
    """Rows of finished games only. An in-progress game has WL null and a partial score; treating it as a
    finished home loss would corrupt Elo, rolling stats and labels."""
    return df[df['WL'].isin(['W', 'L'])].copy()

def home_flags(df):
    """1 for each game's home-team row, 0 for the away row. Neutral-site games (international / Cup games)
    have '@' in both rows and no 'vs.' row; the matchup text doesn't say who is designated home, so the
    lower TEAM_ID is made home, deterministically, rather than dropping the game."""
    has_vs = df['MATCHUP'].str.contains('vs.', regex=False)
    game_has_vs = has_vs.groupby(df['GAME_ID']).transform('any')
    lowest = df['TEAM_ID'] == df.groupby('GAME_ID')['TEAM_ID'].transform('min')
    return (has_vs | (~game_has_vs & lowest)).astype(int)

def label_home_away(df):
    df['HOME'] = home_flags(df)
    return df

def role_form(team_rows, prefix, window=ROLLING_WINDOW):
    """A team's current rolling form: the mean over its last `window` completed games in the given role
    (HOME or AWAY), newest included. Same definition as add_rolling_stats, which shifts by one game so
    each training row only sees games before it; serving a future game sees every game so far.
    `team_rows` is one team's rows from `games`. Returns None until the window is full."""
    rows = completed_games(team_rows)
    wanted = 'vs.' if prefix == 'HOME' else '@'
    rows = rows[rows['MATCHUP'].str.contains(wanted, regex=False)].sort_values('GAME_DATE').tail(window)
    if len(rows) < window:
        return None
    return {
        f'{prefix}_roll_PTS': rows['PTS'].mean(),
        f'{prefix}_roll_FG_PCT': rows['FG_PCT'].mean(),
        f'{prefix}_roll_REB': rows['REB'].mean(),
        f'{prefix}_roll_AST': rows['AST'].mean(),
        f'{prefix}_roll_TOV': rows['TOV'].mean(),
        f'{prefix}_roll_STOCKS': (rows['STL'] + rows['BLK']).mean(),
    }

def rest_days_before(team_rows, game_date):
    """Days since the team's previous completed game (either role) before `game_date`, capped at REST_CAP.
    Mirrors add_rest_days. None when the team has no earlier game."""
    rows = completed_games(team_rows)
    prior = pd.to_datetime(rows['GAME_DATE'])
    prior = prior[prior < pd.Timestamp(game_date)]
    if prior.empty:
        return None
    return min((pd.Timestamp(game_date) - prior.max()).days, REST_CAP)

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
    original_len = len(df)
    df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])

    # A team's rest depends on its true immediately-preceding game, regardless
    # of whether that game (or this one) was played at home or away. Build one
    # row per team per game (long format), diff within each team across BOTH
    # roles, then map the per-team rest value back onto the wide HOME/AWAY
    # columns via a merge on (GAME_ID, TEAM_ID).
    team_games = pd.concat(
        [
            df[['GAME_ID', 'GAME_DATE', 'HOME_TEAM_ID']].rename(columns={'HOME_TEAM_ID': 'TEAM_ID'}),
            df[['GAME_ID', 'GAME_DATE', 'AWAY_TEAM_ID']].rename(columns={'AWAY_TEAM_ID': 'TEAM_ID'}),
        ],
        ignore_index=True,
    )
    # A duplicated game row (e.g. an upstream dedup bug) must never multiply
    # rows through the merge below -- collapse to one entry per (game, team)
    # before diffing/merging.
    team_games = team_games.drop_duplicates(subset=['GAME_ID', 'TEAM_ID']).sort_values(['TEAM_ID', 'GAME_DATE'])
    team_games['rest_days'] = (
        team_games.groupby('TEAM_ID')['GAME_DATE'].transform(lambda x: x.diff().dt.days).clip(upper=REST_CAP)
    )

    for prefix in ['HOME', 'AWAY']:
        df = df.merge(
            team_games[['GAME_ID', 'TEAM_ID', 'rest_days']].rename(
                columns={'TEAM_ID': f'{prefix}_TEAM_ID', 'rest_days': f'{prefix}_rest_days'}
            ),
            on=['GAME_ID', f'{prefix}_TEAM_ID'],
            how='left',
        )

    if len(df) != original_len:
        raise RuntimeError(
            "add_rest_days must not change the number of game rows "
            f"(started with {original_len}, ended with {len(df)}) -- "
            "check for duplicate (GAME_ID, TEAM_ID) rows upstream"
        )

    df['rest_diff'] = df['HOME_rest_days'] - df['AWAY_rest_days']
    return df

def add_elo(df):
    elo = select_rows("elo", order_by=["GAME_DATE", "GAME_ID"])

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

    df = completed_games(df)

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
    upsert_rows("features", games.to_dict("records"), conflict_columns=["GAME_ID"])
    print("Saved!")

if __name__ == '__main__':
    force_utf8_stdio()
    run()