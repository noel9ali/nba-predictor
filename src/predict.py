import os

import joblib
import pandas as pd
from nba_api.stats.endpoints import scoreboardv3
from datetime import date
from console import force_utf8_stdio
from track import setup_tables, save_prediction, kelly_bet, get_current_bankroll
from odds import get_tonights_odds
from elo import get_current_ratings
from database import select_rows

# --- Config ---
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

# games_from_scoreboard() builds one row per game from a ScoreboardV3 dict, taking home and away from the
#   explicit homeTeam / awayTeam objects. The LineScore frame is NOT positional-safe: it lists the HOME team
#   first, so the old groupby().first() = away / .last() = home swapped every game (wrong venue features,
#   odds and edge for the wrong matchup).
def games_from_scoreboard(scoreboard):
    rows = []
    seen = set()
    for game in (scoreboard or {}).get('scoreboard', {}).get('games', []) or []:
        game_id = game.get('gameId')
        home, away = game.get('homeTeam') or {}, game.get('awayTeam') or {}
        if not game_id or game_id in seen or not home.get('teamId') or not away.get('teamId'):
            continue
        seen.add(game_id)
        rows.append({
            'gameId': game_id,
            'HOME_TEAM_ID': home['teamId'],
            'HOME_TEAM_ABBREVIATION': home.get('teamTricode'),
            'VISITOR_TEAM_ID': away['teamId'],
            'VISITOR_TEAM_ABBREVIATION': away.get('teamTricode'),
            'GAME_STATUS': game.get('gameStatus'),
            'TIP_UTC': game.get('gameTimeUTC'),
        })
    return pd.DataFrame(rows, columns=['gameId', 'HOME_TEAM_ID', 'HOME_TEAM_ABBREVIATION',
                                       'VISITOR_TEAM_ID', 'VISITOR_TEAM_ABBREVIATION', 'GAME_STATUS', 'TIP_UTC'])


def predict_window_minutes():
    """NBA_PREDICT_WINDOW_MINUTES (set by the evening predict stage): only price games that tip within this many
    minutes, so each game is priced shortly before tip with the newest injury report. Unset = no window."""
    try:
        value = int(os.environ.get('NBA_PREDICT_WINDOW_MINUTES', '').strip())
    except ValueError:
        return None
    return value if value > 0 else None


def within_window(games, minutes, now=None):
    """Keep games that tip within `minutes` from now. A game with an unknown tip time is kept (never silently
    dropped); one whose tip has passed is left to not_started()."""
    if not minutes or 'TIP_UTC' not in games.columns:
        return games
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='UTC')
    tip = pd.to_datetime(games['TIP_UTC'], utc=True, errors='coerce')
    soon = tip.isna() | (tip <= now + pd.Timedelta(minutes=minutes))
    return games[soon].reset_index(drop=True)


def not_yet_predicted(games):
    """Drop games that already have a predictions row. A failed lookup keeps every game: the per-game
    duplicate check in save_prediction is still the safety net."""
    try:
        done = select_rows("predictions", columns="game_id", order_by="game_id",
                           filters=[("game_date", "eq", str(date.today()))])
    except Exception as exc:
        print(f"Could not check existing predictions ({type(exc).__name__}); predicting every game.")
        return games
    if done.empty:
        return games
    have = set(done["game_id"].astype(str))
    return games[~games["gameId"].astype(str).isin(have)].reset_index(drop=True)


def not_started(games):
    """Keep scheduled games only (ScoreboardV3 gameStatus 1). A late-day run must not price a game that is in
    progress or over: in-play odds and a known score would make the 'prediction' meaningless. A missing status
    is treated as scheduled."""
    if 'GAME_STATUS' not in games.columns:
        return games
    status = pd.to_numeric(games['GAME_STATUS'], errors='coerce').fillna(1)
    return games[status == 1].reset_index(drop=True)


# get_todays_games() fetches today's games from nba_api. Returns a dataframe with one
#   game per row
def get_todays_games():
    today = date.today().strftime('%Y-%m-%d')
    board = scoreboardv3.ScoreboardV3(game_date=today)
    return games_from_scoreboard(board.get_dict())

# get_team_rolling_stats() looks up rolling averages for a team's past 10 games
def get_team_rolling_stats(team_id, prefix):
    if prefix not in {"HOME", "AWAY"}:
        raise ValueError("prefix must be HOME or AWAY")
    columns = (
        f"{prefix}_roll_PTS,{prefix}_roll_FG_PCT,{prefix}_roll_REB,"
        f"{prefix}_roll_AST,{prefix}_roll_TOV,{prefix}_roll_STOCKS,GAME_DATE"
    )
    return select_rows(
        "features",
        columns=columns,
        filters=[(f"{prefix}_TEAM_ID", "eq", team_id)],
        order_by="GAME_DATE",
        descending=True,
        limit=1,
    )

# get_rest_days() calculates the amount of days since last game for a given team
def get_rest_days(team_id, prefix):
    if prefix not in {"HOME", "AWAY"}:
        raise ValueError("prefix must be HOME or AWAY")
    df = select_rows(
        "features",
        columns="GAME_DATE",
        filters=[(f"{prefix}_TEAM_ID", "eq", team_id)],
        order_by="GAME_DATE",
        descending=True,
        limit=1,
    )
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

# implied_prob() converts american odds to implied probability (market-agnostic, src/betting.py)
from betting import implied_prob  # noqa: E402

def _availability_setup():
    """Load the availability helpers, the saved candidate (if any) and player names. Never raises."""
    try:
        import availability_predict as ap
    except Exception as exc:
        print(f"Availability step disabled: {type(exc).__name__}: {exc}")
        return None, None, {}
    try:
        ap.flag_status_changes()
    except Exception as exc:
        print(f"Status-change check skipped: {type(exc).__name__}: {exc}")
    configured = ap.configured_candidate_name()
    try:
        candidate = ap.load_candidate(configured or ap.DEFAULT_CANDIDATE, required=bool(configured))
    except Exception as exc:
        if configured:
            raise RuntimeError(f"Configured candidate cannot be used: {exc}") from exc
        print(f"Availability candidate not loaded: {type(exc).__name__}: {exc}")
        candidate = None
    try:
        names = ap.player_names()
    except Exception:
        names = {}
    return ap, candidate, names


def run():
    # load the trained model and scaler
    print("Loading model...")
    model, scaler = load_model()
    ap, candidate, player_names = _availability_setup()

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

    # skip games already in progress or finished (a late-day run, or a manual re-run)
    scheduled = not_started(games)
    if len(scheduled) < len(games):
        print(f"Skipping {len(games) - len(scheduled)} game(s) already started or finished.")
    games = scheduled
    if len(games) == 0:
        print("No games left to predict.")
        return

    # the evening stage prices each game shortly before its tip, with the newest injury report
    window = predict_window_minutes()
    if window:
        in_window = within_window(games, window)
        if len(in_window) < len(games):
            print(f"{len(games) - len(in_window)} game(s) tip more than {window} min from now; deferred to a later run.")
        games = in_window
        if len(games) == 0:
            print("No games inside the prediction window.")
            return

    # a repeat run (a retry trigger, or a manual re-run) must not spend an odds request on games that already
    # have a prediction; save_prediction would skip them anyway
    games = not_yet_predicted(games)
    if len(games) == 0:
        print("Every game today already has a prediction.")
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

        # Availability (player-data work): projections, features and the candidate's shadow prediction.
        # Production picks only change when NBA_PRODUCTION_MODEL names the availability candidate.
        extra = {}
        if ap is not None:
            try:
                avail = ap.run_for_game(str(game['gameId']), str(date.today()), int(home_id), int(away_id), row,
                                        candidate=candidate, names=player_names)
                if avail and candidate and ap.production_uses_candidate(candidate['name']):
                    home_prob = avail['home_win_prob'] * 100
                    away_prob = 100 - home_prob
                    extra = {'prob_range_low': avail['prob_range_low'],
                             'prob_range_high': avail['prob_range_high'],
                             'model_name': candidate['name']}
            except Exception as exc:
                print(f"  availability step skipped: {type(exc).__name__}: {exc}")

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
            if extra:
                from scenarios import apply_gate
                bet_amount, skip_reason = apply_gate(bet_amount, extra['prob_range_low'], extra['prob_range_high'])
                if skip_reason:
                    extra['skip_reason'] = skip_reason
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
            odds             = bet_odds,
            extra            = extra or None
        )

if __name__ == '__main__':
    force_utf8_stdio()
    setup_tables()
    run()