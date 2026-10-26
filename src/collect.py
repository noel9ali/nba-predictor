import sys
import time
from datetime import date

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder
from console import force_utf8_stdio
from database import DatabaseError, normalize_game_id, upsert_rows
from nba_client import season_for_date

# Config: historical seasons are fixed; the current season is added automatically.
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


def seasons_to_collect(today=None):
    """Fixed historical seasons plus the current one (no yearly edit needed)."""
    current = season_for_date(today or date.today())
    return SEASONS if current in SEASONS else SEASONS + [current]


# fetch_season(): returns a DataFrame (empty = NBA has no games yet), or None
# when every attempt raised, so callers can tell "no data" from "failed".
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
            print(f"  ERROR fetching {season}: {type(e).__name__}: {e}")
            if attempt < retries - 1:
                print(f"  Retrying in 5 seconds...")
                time.sleep(5)
            # give up after 3 retries
            else:
                print(f"  ERROR: giving up on {season} after {retries} attempts")
                return None

def save_to_db(df, db_path=None):
    del db_path
    # A game still in progress comes back with WL null and a partial score. Saving it would feed a fake
    # home loss to Elo and training; the row is upserted by (GAME_ID, TEAM_ID) once the game is final.
    df = df[df["WL"].isin(["W", "L"])].copy()
    df["GAME_ID"] = df["GAME_ID"].map(normalize_game_id)
    upsert_rows(
        "games",
        df.to_dict("records"),
        conflict_columns=GAMES_CONFLICT_COLUMNS,
    )

def _raise_if_failed(failed):
    # Seasons that did fetch are already saved; a failed season must still fail the step.
    if failed:
        msg = f"ERROR: collect failed for season(s): {', '.join(failed)}"
        print(msg)
        raise RuntimeError(msg)

def run(today=None):
    all_data = []
    failed = []
    current = season_for_date(today or date.today())
    for season in seasons_to_collect(today):
        df = fetch_season(season)
        if df is None:
            failed.append(season)
        elif len(df) > 0:
            all_data.append(df)
            print(f"  Got {len(df)} rows")
        elif season == current:
            print(f"  no games yet for {season}")
        else:
            print(f"  Skipping {season} - no data returned")

    if len(all_data) == 0:
        print("No data fetched — database unchanged.")
        _raise_if_failed(failed)
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
    _raise_if_failed(failed)

if __name__ == '__main__':
    force_utf8_stdio()
    try:
        run()
    except Exception as exc:
        print(f"ERROR: collect failed: {type(exc).__name__}: {exc}")
        sys.exit(1)
