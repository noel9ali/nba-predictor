import requests
from dotenv import load_dotenv
import os

# Config
load_dotenv()
API_KEY = os.getenv('ODDS_API_KEY')
BASE_URL = 'https://api.the-odds-api.com/v4'
SPORT = 'basketball_nba'
REGIONS = 'us'
MARKETS = 'h2h'  # head to head = moneyline
ODDS_FORMAT = 'american'
PREFERRED_BOOKS = ['DraftKings', 'FanDuel', 'BetMGM', "BetRivers", "BetUS"]
REQUEST_SUCCESS=200
ABBR_MAP = {
    'ATL': 'Atlanta Hawks',
    'BOS': 'Boston Celtics',
    'BKN': 'Brooklyn Nets',
    'CHA': 'Charlotte Hornets',
    'CHI': 'Chicago Bulls',
    'CLE': 'Cleveland Cavaliers',
    'DAL': 'Dallas Mavericks',
    'DEN': 'Denver Nuggets',
    'DET': 'Detroit Pistons',
    'GSW': 'Golden State Warriors',
    'HOU': 'Houston Rockets',
    'IND': 'Indiana Pacers',
    'LAC': 'Los Angeles Clippers',
    'LAL': 'Los Angeles Lakers',
    'MEM': 'Memphis Grizzlies',
    'MIA': 'Miami Heat',
    'MIL': 'Milwaukee Bucks',
    'MIN': 'Minnesota Timberwolves',
    'NOP': 'New Orleans Pelicans',
    'NYK': 'New York Knicks',
    'OKC': 'Oklahoma City Thunder',
    'ORL': 'Orlando Magic',
    'PHI': 'Philadelphia 76ers',
    'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers',
    'SAC': 'Sacramento Kings',
    'SAS': 'San Antonio Spurs',
    'TOR': 'Toronto Raptors',
    'UTA': 'Utah Jazz',
    'WAS': 'Washington Wizards'
}

def get_tonights_odds():
    url = f"{BASE_URL}/sports/{SPORT}/odds"
    params = {
        'apiKey': API_KEY,
        'regions': REGIONS,
        'markets': MARKETS,
        'oddsFormat': ODDS_FORMAT
    }

    response = requests.get(url, params=params)

    if response.status_code != REQUEST_SUCCESS:
        print(f"Error fetching odds: {response.status_code} - {response.text}")
        return {}

    games = response.json()
    odds_by_teams = {}

    for game in games:
        home_team = game['home_team']
        away_team = game['away_team']

        # grab the first bookmaker available
        if not game['bookmakers']:
            continue

        bookmaker = game['bookmakers'][0]
        markets = bookmaker['markets'][0]

        best_home_odds = None
        best_away_odds = None
        best_home_book = None
        best_away_book = None

        for bookmaker in game['bookmakers']:
            if bookmaker['title'] not in PREFERRED_BOOKS:
                continue
            for market in bookmaker['markets']:
                if market['key'] != 'h2h':
                    continue
                for outcome in market['outcomes']:
                    price = outcome['price']
                    if outcome['name'] == home_team:
                        if best_home_odds is None or price > best_home_odds:
                            best_home_odds = price
                            best_home_book = bookmaker['title']
                    elif outcome['name'] == away_team:
                        if best_away_odds is None or price > best_away_odds:
                            best_away_odds = price
                            best_away_book = bookmaker['title']

        if best_home_odds and best_away_odds:
            odds_by_teams[(home_team, away_team)] = {
                'home_odds': best_home_odds,
                'away_odds': best_away_odds,
                'home_book': best_home_book,
                'away_book': best_away_book
            }

    print(f"Found odds for {len(odds_by_teams)} games")
    print(f"Requests used: {response.headers.get('x-requests-used')}")
    print(f"Requests remaining: {response.headers.get('x-requests-remaining')}")
    return odds_by_teams

def get_bookmakers():
    url = f"{BASE_URL}/sports/{SPORT}/odds"
    params = {
        'apiKey': API_KEY,
        'regions': REGIONS,
        'markets': MARKETS,
        'oddsFormat': ODDS_FORMAT
    }
    response = requests.get(url, params=params)
    games = response.json()

    bookmakers = set()
    for game in games:
        for bookmaker in game['bookmakers']:
            bookmakers.add(bookmaker['title'])

    print("Available bookmakers:")
    for b in sorted(bookmakers):
        print(f"  {b}")

if __name__ == '__main__':
    odds = get_tonights_odds()
    for teams, data in odds.items():
        print(f"{teams[1]} @ {teams[0]}")
        print(f"  Home {data['home_odds']} ({data['home_book']})")
        print(f"  Away {data['away_odds']} ({data['away_book']})")

if __name__ == '__main__':
    get_bookmakers()