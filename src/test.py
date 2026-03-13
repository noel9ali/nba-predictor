from nba_api.stats.endpoints import leaguegamefinder
import pandas as pd

print("Libraries imported successfully...")

gamefinder = leaguegamefinder.LeagueGameFinder(season_nullable='2023-24')
games = gamefinder.get_data_frames()[0]

print(f"Total rows: {len(games)}")
print(games.head())
