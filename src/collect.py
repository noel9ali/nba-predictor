import time
import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder
from console import force_utf8_stdio
from database import DatabaseError, normalize_game_id, upsert_rows

# Config
SEASONS = [
    '2019-20',
    '2020-21',
    '2021-22',
    '2022-23',
    '2023-24',
    '2024-25',
    '2025-26'
]
GAMES_CONFLICT_COLUMNS = ["GAME_ID", "TEAM_ID"]
GAMES_COMPOSITE_PK_MIGRATION_HINT = "supabase/migrations/20260923000200_games_composite_pk.sql"

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

def save_to_db(df, db_path=None):
    del db_path
    df = df.copy()
    df["GAME_ID"] = df["GAME_ID"].map(normalize_game_id)
    upsert_rows(
        "games",
        df.to_dict("records"),
        conflict_columns=GAMES_CONFLICT_COLUMNS,
    )

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

    # Upsert fetched rows so scheduled runs are idempotent and preserve history.
    combined = pd.concat(all_data, ignore_index=True)
    try:
        save_to_db(combined)
    except DatabaseError as exc:
        if "conflict target" in str(exc):
            raise DatabaseError(
                f"{exc}: apply {GAMES_COMPOSITE_PK_MIGRATION_HINT}"
            ) from exc
        raise
    print(f"\nDone! Total rows saved: {len(combined)}")

if __name__ == '__main__':
    force_utf8_stdio()
    run()