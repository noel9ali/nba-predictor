import time
import sqlite3
import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder

# Config
DB_PATH = 'data/nba.db'
SEASONS = [
    '2019-20',
    '2020-21',
    '2021-22',
    '2022-23',
    '2023-24',
    '2024-25',
    '2025-26'
]

# fetch_season()
def fetch_season(season, retries=3):
    for attempt in range(retries):
        try:
            print(f"Fetching {season}... (attempt {attempt + 1})")
            gamefinder = leaguegamefinder.LeagueGameFinder(
                season_nullable=season,
                season_type_nullable='Regular Season'
            )
            df = gamefinder.get_data_frames()[0]
            df['SEASON'] = season
            time.sleep(0.6)
            return df
        # if connection to NBA.com fails, retry after 5 seconds
        except Exception as e:
            print(f"  Failed: {e}")
            if attempt < retries - 1:
                print(f"  Retrying in 5 seconds...")
                time.sleep(5)
            # give up after 3 retries
            else:
                print(f"  Giving up on {season} after {retries} attempts")
                return pd.DataFrame()

def save_to_db(df, db_path):
    conn = sqlite3.connect(db_path)
    df.to_sql('games', conn, if_exists='append', index=False)
    conn.close()

def run():
    all_data = []
    for season in SEASONS:
        df = fetch_season(season)
        if len(df) > 0:
            all_data.append(df)
            print(f"  Got {len(df)} rows")
        else:
            print(f"  Skipping {season} — no data returned")

    if len(all_data) == 0:
        print("No data fetched — database unchanged.")
        return

    # only wipe and replace if data was fetched
    combined = pd.concat(all_data, ignore_index=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS games")
    conn.commit()
    conn.close()

    save_to_db(combined, DB_PATH)
    print(f"\nDone! Total rows saved: {len(combined)}")

if __name__ == '__main__':
    run()