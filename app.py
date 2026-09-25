import os
import re
import secrets
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, g, jsonify, make_response, render_template, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from database import (  # noqa: E402  (needs the src/ path above)
    DatabaseError,
    MissingColumnError,
    MissingTableError,
    normalize_game_id,
    schema_v2_enabled,
    select_rows,
)

load_dotenv()

# Statics live in public/ so Vercel's CDN serves them; local Flask serves the same
# files at the same /static URL.
app = Flask(__name__, static_folder="public/static", static_url_path="/static")
# SEC-F7: no hardcoded fallback. Sessions/flash are unused (confirmed: git grep -n
# "session|flash" -- app.py templates/ -> 0 hits), so a random per-process key is fine;
# it just needs to never be a known, publicly-visible default.
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_urlsafe(32)

SEASON_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")
LEGACY_CACHE_CONTROL = "public, s-maxage=300, stale-while-revalidate=3600"


def safe_float(value, default=None):
    try:
        if value is None:
            return default
        value = float(value)
        if value != value:  # NaN
            return default
        return value
    except (TypeError, ValueError):
        return default


def normalize_probability(prob):
    value = safe_float(prob)
    if value is None:
        return None
    if value > 1:
        value = value / 100.0
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def implied_probability(american_odds):
    odds = safe_float(american_odds)
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def confidence_bucket(expected_prob):
    if expected_prob is None:
        return "unknown"
    if expected_prob >= 0.65:
        return "high"
    if expected_prob >= 0.58:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Seasons: an NBA season runs Sept 1 - Aug 31 (04-API-CONTRACT sec0), so the
# Aug 2020 bubble games stay in 2019-20.
# ---------------------------------------------------------------------------

def season_for(value):
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    start = d.year if d.month >= 9 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def parse_season(value):
    """Return value if it's a season label like 2025-26, else None."""
    match = SEASON_PATTERN.match(value)
    if not match or match.group(2) != str(int(match.group(1)) + 1)[2:]:
        return None
    return value


def season_bounds(season):
    start = int(season[:4])
    return f"{start}-09-01", f"{start + 1}-08-31"


def season_end_year(season):
    """The legacy "year" of a season: the calendar year it ends in."""
    return str(int(season[:4]) + 1)


def season_filters(column, season):
    start, end = season_bounds(season)
    return [(column, "gte", start), (column, "lte", end)]


def requested_season(args):
    """The season asked for by ?season= or the legacy ?year=YYYY alias.

    Returns "" when none is given (a non-numeric year counts as none, as it
    always did) and None when ?season= is malformed.
    """
    raw = (args.get("season") or "").strip()
    if raw:
        return parse_season(raw)
    year = (args.get("year") or "").strip()
    if re.fullmatch(r"\d{4}", year):
        return f"{int(year) - 1}-{year[2:]}"
    return ""


def pick_season(requested, seasons):
    return requested if requested in seasons else seasons[0]


def pick_date(args, dates):
    selected = args.get("game_date", dates[0])
    return selected if selected in dates else dates[0]


# ---------------------------------------------------------------------------
# Data access (Supabase through src/database.py; no SQL in the app)
# ---------------------------------------------------------------------------

def read_rows(table, **kwargs):
    """select_rows, reading a table or column a pending migration adds as empty."""
    try:
        return select_rows(table, **kwargs)
    except (MissingTableError, MissingColumnError):
        g.migration_pending = True
        return pd.DataFrame()


def records(df):
    """DataFrame rows as plain dicts, with NaN turned into None."""
    if df.empty:
        return []
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _prediction_dates():
    """All predictions.game_date values, fetched once per request so available_seasons()
    and available_prediction_dates() (SEC-F4/API-F1) can share the read."""
    dates = g.get("_prediction_dates")
    if dates is None:
        df = read_rows(
            "predictions",
            columns="game_date",
            filters=[("game_date", "not_is", "null")],
            order_by="game_date",
            descending=True,
        )
        dates = [r["game_date"] for r in records(df) if r.get("game_date")]
        g._prediction_dates = dates
    return dates


def available_seasons():
    seasons = list(dict.fromkeys(season_for(d) for d in _prediction_dates()))
    if not seasons:
        seasons = [season_for(date.today())]
    return seasons


def available_prediction_dates(season):
    start, end = season_bounds(season)
    dates = list(dict.fromkeys(d for d in _prediction_dates() if start <= d <= end))
    if not dates:
        dates = [date.today().strftime("%Y-%m-%d")]
    return dates


def longest_streaks(completed_rows):
    longest_win = 0
    longest_loss = 0
    current_win = 0
    current_loss = 0

    for row in completed_rows:
        if row.get("correct") == 1:
            current_win += 1
            current_loss = 0
        elif row.get("correct") == 0:
            current_loss += 1
            current_win = 0
        else:
            current_win = 0
            current_loss = 0
        longest_win = max(longest_win, current_win)
        longest_loss = max(longest_loss, current_loss)

    return {"longest_win_streak": longest_win, "longest_loss_streak": longest_loss}


def bankroll_series_for_season(season):
    df = read_rows(
        "bankroll",
        columns="date,balance",
        filters=season_filters("date", season),
        order_by="date",
    )
    points = []
    for row in records(df):
        balance = safe_float(row.get("balance"))
        if row.get("date") and balance is not None:
            points.append({"date": row["date"], "balance": balance})

    if not points:
        return []

    start_balance = points[0]["balance"]
    for p in points:
        p["cum_pl"] = p["balance"] - start_balance
    return points


def max_drawdown(bankroll_points):
    if not bankroll_points:
        return 0.0
    peak = bankroll_points[0]["balance"]
    worst = 0.0
    for p in bankroll_points:
        bal = p["balance"]
        if bal > peak:
            peak = bal
        drawdown = peak - bal
        if drawdown > worst:
            worst = drawdown
    return worst


def empty_ytd_summary(season):
    return {
        "year": season_end_year(season),
        "season": season,
        "games": 0,
        "wins": 0,
        "losses": 0,
        "accuracy": "0.0%",
        "bets_placed": 0,
        "total_staked": 0.0,
        "total_pl": 0.0,
        "roi": "0.0%",
        "bankroll": None,
        "longest_win_streak": 0,
        "longest_loss_streak": 0,
        "max_drawdown": 0.0,
    }


def ytd_summary_for_season(season, bankroll_points=None):
    rows = records(
        read_rows(
            "predictions",
            columns="game_id,game_date,correct,profit_loss,bet_amount",
            filters=[*season_filters("game_date", season), ("correct", "not_is", "null")],
            order_by=["game_date", "game_id"],
        )
    )

    if not rows:
        return empty_ytd_summary(season)

    games = len(rows)
    wins = sum(1 for r in rows if r.get("correct") == 1)
    losses = games - wins
    bets_placed = sum(1 for r in rows if (safe_float(r.get("bet_amount"), 0) or 0) > 0)
    total_staked = sum(safe_float(r.get("bet_amount"), 0) or 0 for r in rows)
    total_pl = sum(safe_float(r.get("profit_loss"), 0) or 0 for r in rows)
    roi = (total_pl / total_staked) if total_staked > 0 else 0.0

    if bankroll_points is None:
        bankroll_points = bankroll_series_for_season(season)
    bankroll = bankroll_points[-1]["balance"] if bankroll_points else None
    streaks = longest_streaks(rows)

    return {
        "year": season_end_year(season),
        "season": season,
        "games": games,
        "wins": wins,
        "losses": losses,
        "accuracy": f"{(wins / games):.1%}" if games else "0.0%",
        "bets_placed": bets_placed,
        "total_staked": total_staked,
        "total_pl": total_pl,
        "roi": f"{roi:.1%}",
        "bankroll": bankroll,
        "longest_win_streak": streaks["longest_win_streak"],
        "longest_loss_streak": streaks["longest_loss_streak"],
        "max_drawdown": max_drawdown(bankroll_points),
    }


# Batched per-team lookups (API-F1): one query per side for the whole slate instead of one
# per team, so the call count stays constant no matter how many games are on the date. Most
# teams have played within TEAM_LOOKBACK_DAYS, so that short window keeps each query to a
# single page; whichever teams are still missing after it (e.g. a season-opening slate, where
# every team's last game was months into the offseason -- longer still across the 2020 bubble
# gap) get one extra, wider retry per query so they don't silently lose Elo/features rather
# than just being less fresh. A normal slate never triggers the retry, so its call count is
# unaffected; the worst case (nobody within the short window) adds at most one retry call per
# query below.
TEAM_LOOKBACK_DAYS = 60
TEAM_LOOKBACK_RETRY_DAYS = 400  # longer than any NBA offseason, including the 2020 bubble gap


def _latest_elo_by_team(team_ids, before_date):
    """The latest elo rating for each team_id, across both home and away appearances."""
    team_ids = sorted({int(t) for t in team_ids if t is not None})
    if not team_ids:
        return {}

    latest = {}

    def scan(ids, lookback_days):
        if not ids:
            return
        lookback = (date.fromisoformat(before_date) - timedelta(days=lookback_days)).isoformat()
        for side in ("HOME", "AWAY"):
            id_column = f"{side}_TEAM_ID"
            rows = records(
                read_rows(
                    "elo",
                    columns=f"GAME_DATE,{id_column},{side}_ELO",
                    filters=[(id_column, "in", ids), ("GAME_DATE", "gte", lookback)],
                    order_by="GAME_DATE",
                    descending=True,
                )
            )
            seen = set()
            for row in rows:
                team_id = row.get(id_column)
                if team_id is None or team_id in seen:
                    continue  # rows arrive latest-first per side; the first hit per team wins
                seen.add(team_id)
                game_date = row.get("GAME_DATE")
                current = latest.get(team_id)
                if current is None or str(game_date) > str(current["GAME_DATE"]):
                    latest[team_id] = {"GAME_DATE": game_date, "elo_value": row.get(f"{side}_ELO")}

    scan(team_ids, TEAM_LOOKBACK_DAYS)
    scan([t for t in team_ids if t not in latest], TEAM_LOOKBACK_RETRY_DAYS)
    return {team_id: safe_float(v["elo_value"]) for team_id, v in latest.items()}


def _latest_features_by_team(team_abbrs, side_prefix, before_date):
    """The latest `side_prefix` features row for each team in team_abbrs, in one query."""
    team_abbrs = sorted({t for t in team_abbrs if t})
    if not team_abbrs:
        return {}

    columns = {
        "team_id": f"{side_prefix}_TEAM_ID",
        "roll_pts": f"{side_prefix}_roll_PTS",
        "roll_fg_pct": f"{side_prefix}_roll_FG_PCT",
        "roll_reb": f"{side_prefix}_roll_REB",
        "roll_ast": f"{side_prefix}_roll_AST",
        "roll_tov": f"{side_prefix}_roll_TOV",
        "roll_stocks": f"{side_prefix}_roll_STOCKS",
        "rest_days": f"{side_prefix}_rest_days",
    }
    abbr_column = f"{side_prefix}_TEAM_ABBREVIATION"
    latest = {}

    def scan(abbrs, lookback_days):
        if not abbrs:
            return
        lookback = (date.fromisoformat(before_date) - timedelta(days=lookback_days)).isoformat()
        rows = records(
            read_rows(
                "features",
                columns=f"{abbr_column}," + ",".join(columns.values()),
                filters=[(abbr_column, "in", abbrs), ("GAME_DATE", "gte", lookback)],
                order_by="GAME_DATE",
                descending=True,
            )
        )
        for row in rows:
            abbr = row.get(abbr_column)
            if abbr and abbr not in latest:  # rows arrive latest-first; keep the first per team
                latest[abbr] = {alias: row.get(column) for alias, column in columns.items()}

    scan(team_abbrs, TEAM_LOOKBACK_DAYS)
    scan([t for t in team_abbrs if t not in latest], TEAM_LOOKBACK_RETRY_DAYS)
    return latest


def build_recommendations(game_date):
    rows = records(
        read_rows(
            "predictions",
            columns=(
                "game_id,game_date,home_team,away_team,home_win_prob,away_win_prob,"
                "predicted_winner,bet_amount,odds"
            ),
            filters=[("game_date", "eq", game_date)],
            order_by=["home_team", "away_team"],
        )
    )

    home_features = _latest_features_by_team((r.get("home_team") for r in rows), "HOME", game_date)
    away_features = _latest_features_by_team((r.get("away_team") for r in rows), "AWAY", game_date)
    team_ids = (
        ctx.get("team_id") for ctx in (*home_features.values(), *away_features.values())
    )
    elo_by_team = _latest_elo_by_team(team_ids, game_date)

    recommendations = []
    for i, game in enumerate(rows):
        home_prob = normalize_probability(game.get("home_win_prob"))
        away_prob = normalize_probability(game.get("away_win_prob"))
        predicted = game.get("predicted_winner")

        expected_win_prob = None
        if predicted == game.get("home_team"):
            expected_win_prob = home_prob
        elif predicted == game.get("away_team"):
            expected_win_prob = away_prob

        implied_prob = implied_probability(game.get("odds"))
        edge = None
        if expected_win_prob is not None and implied_prob is not None:
            edge = expected_win_prob - implied_prob

        home_ctx = home_features.get(game.get("home_team"), {})
        away_ctx = away_features.get(game.get("away_team"), {})
        home_team_id = home_ctx.get("team_id")
        away_team_id = away_ctx.get("team_id")

        bet_amount = safe_float(game.get("bet_amount"), 0) or 0
        game_id = game.get("game_id")
        recommendations.append(
            {
                "id": normalize_game_id(game_id) if game_id is not None else f"game-{i}",
                "matchup": f"{game.get('away_team')} @ {game.get('home_team')}",
                "home_team": game.get("home_team"),
                "away_team": game.get("away_team"),
                "predicted_winner": predicted,
                "expected_win_prob": expected_win_prob,
                "implied_prob": implied_prob,
                "edge": edge,
                "confidence_bucket": confidence_bucket(expected_win_prob),
                "bet_amount": bet_amount,
                "odds": safe_float(game.get("odds")),
                "recommendation_type": "bet" if bet_amount > 0 else "no_edge",
                "details": {
                    "home_elo": elo_by_team.get(int(home_team_id)) if home_team_id is not None else None,
                    "away_elo": elo_by_team.get(int(away_team_id)) if away_team_id is not None else None,
                    "home_rest_days": safe_float(home_ctx.get("rest_days")),
                    "away_rest_days": safe_float(away_ctx.get("rest_days")),
                    "home_roll_pts": safe_float(home_ctx.get("roll_pts")),
                    "home_roll_fg_pct": safe_float(home_ctx.get("roll_fg_pct")),
                    "home_roll_reb": safe_float(home_ctx.get("roll_reb")),
                    "home_roll_ast": safe_float(home_ctx.get("roll_ast")),
                    "home_roll_tov": safe_float(home_ctx.get("roll_tov")),
                    "home_roll_stocks": safe_float(home_ctx.get("roll_stocks")),
                    "away_roll_pts": safe_float(away_ctx.get("roll_pts")),
                    "away_roll_fg_pct": safe_float(away_ctx.get("roll_fg_pct")),
                    "away_roll_reb": safe_float(away_ctx.get("roll_reb")),
                    "away_roll_ast": safe_float(away_ctx.get("roll_ast")),
                    "away_roll_tov": safe_float(away_ctx.get("roll_tov")),
                    "away_roll_stocks": safe_float(away_ctx.get("roll_stocks")),
                },
            }
        )
    return recommendations


def confidence_distribution(recommendations):
    counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for rec in recommendations:
        bucket = rec.get("confidence_bucket", "unknown")
        if bucket not in counts:
            bucket = "unknown"
        counts[bucket] += 1
    return counts


def top_edges(recommendations, limit=5):
    rows = [r for r in recommendations if r.get("edge") is not None]
    rows.sort(key=lambda x: x["edge"], reverse=True)
    return rows[:limit]


def peak_and_trough(bankroll_points):
    if not bankroll_points:
        return {"peak": None, "trough": None}

    peak = max(bankroll_points, key=lambda x: x["balance"])
    trough = min(bankroll_points, key=lambda x: x["balance"])
    return {"peak": peak, "trough": trough}


def build_dashboard_state(season, game_date):
    bankroll_points = bankroll_series_for_season(season)
    ytd = ytd_summary_for_season(season, bankroll_points)
    recs = build_recommendations(game_date)
    peaks = peak_and_trough(bankroll_points)

    return {
        "year": season_end_year(season),
        "season": season,
        "game_date": game_date,
        "ytd_summary": ytd,
        "recommendations": recs,
        "confidence_distribution": confidence_distribution(recs),
        "top_edges": top_edges(recs),
        "bankroll_series": bankroll_points,
        "peak_point": peaks["peak"],
        "trough_point": peaks["trough"],
    }


def empty_dashboard_state(season, game_date):
    return {
        "year": season_end_year(season),
        "season": season,
        "game_date": game_date,
        "ytd_summary": empty_ytd_summary(season),
        "recommendations": [],
        "confidence_distribution": confidence_distribution([]),
        "top_edges": [],
        "bankroll_series": [],
        "peak_point": None,
        "trough_point": None,
    }


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

# SEC-F2: locked-down response headers for every route (pages, API JSON, and errors).
# HSTS is deliberately not set here: Vercel adds Strict-Transport-Security on its own
# domains, and this app also runs locally over plain HTTP, where HSTS would be wrong.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


@app.after_request
def set_security_headers(response):
    # setdefault: never overwrite a header a route already set deliberately.
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


def api_response(payload, cache_control=LEGACY_CACHE_CONTROL):
    body = dict(payload)
    body["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body["migration_pending"] = bool(g.get("migration_pending", False))
    response = jsonify(body)
    response.headers["Cache-Control"] = cache_control
    return response


def error_response(status, error, **extra):
    response = jsonify({"error": error, **extra})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def season_from_request():
    """The selected season, or None when ?season= is malformed."""
    requested = requested_season(request.args)
    if requested is None:
        return None
    return pick_season(requested, available_seasons())


def bad_season_response():
    return error_response(400, "bad_request", detail="season must look like 2025-26")


@app.errorhandler(DatabaseError)
def database_unavailable(exc):
    # The exception text stays out of the response; only its type is logged.
    app.logger.warning("Database unavailable: %s", type(exc).__name__)
    return error_response(503, "database_unavailable")


@app.errorhandler(404)
def not_found(exc):
    return error_response(404, "not_found")


@app.errorhandler(405)
def method_not_allowed(exc):
    return error_response(405, "method_not_allowed")


@app.route("/")
def index():
    notice = None
    try:
        seasons = available_seasons()
        selected_season = pick_season(requested_season(request.args) or "", seasons)
        dates = available_prediction_dates(selected_season)
        selected_date = pick_date(request.args, dates)
        dashboard_state = build_dashboard_state(selected_season, selected_date)
    except DatabaseError as exc:
        app.logger.warning("Database unavailable: %s", type(exc).__name__)
        selected_season = season_for(date.today())
        seasons = [selected_season]
        selected_date = date.today().strftime("%Y-%m-%d")
        dates = [selected_date]
        dashboard_state = empty_dashboard_state(selected_season, selected_date)
        notice = "Game data is unavailable right now. Try again in a few minutes."

    response = make_response(
        render_template(
            "index.html",
            seasons=seasons,
            selected_season=selected_season,
            available_dates=dates,
            selected_date=selected_date,
            dashboard_state=dashboard_state,
            notice=notice,
            migration_pending=bool(g.get("migration_pending", False)),
        )
    )
    response.headers["Cache-Control"] = LEGACY_CACHE_CONTROL if notice is None else "no-store"
    return response


@app.route("/api/dashboard-state")
def api_dashboard_state():
    season = season_from_request()
    if season is None:
        return bad_season_response()
    dates = available_prediction_dates(season)
    return api_response(build_dashboard_state(season, pick_date(request.args, dates)))


@app.route("/api/ytd-summary")
def api_ytd_summary():
    season = season_from_request()
    if season is None:
        return bad_season_response()
    return api_response(ytd_summary_for_season(season))


@app.route("/api/recommendations")
def api_recommendations():
    season = season_from_request()
    if season is None:
        return bad_season_response()
    game_date = pick_date(request.args, available_prediction_dates(season))
    return api_response(
        {"season": season, "game_date": game_date, "recommendations": build_recommendations(game_date)}
    )


@app.route("/api/bankroll-series")
def api_bankroll_series():
    season = season_from_request()
    if season is None:
        return bad_season_response()
    return api_response(
        {"year": season_end_year(season), "season": season, "points": bankroll_series_for_season(season)}
    )


# ---------------------------------------------------------------------------
# Dashboard read API (04-API-CONTRACT sec2, sec4-9; build tasks B5/B6).
#
# [M] data (tables and columns a pending migration adds) is only read when
# NBA_SCHEMA_V2 is on; otherwise it comes back null/empty with
# migration_pending: true. Every route keeps a constant, bounded number of
# Supabase calls no matter how many games or rows are involved (API-F1).
# ---------------------------------------------------------------------------

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GAME_ID_PATTERN = re.compile(r"^\d{10}$")
TEAM_QUERY_PATTERN = re.compile(r"^[A-Za-z0-9 .'-]{1,40}$")
EASTERN = "America/New_York"
START_BANKROLL = 1000.0
RECENT_BETS = 33
# The sportsbooks odds.py keeps (src/odds.py PREFERRED_BOOKS), in grid order.
PREFERRED_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "BetRivers", "BetUS"]

CACHE_SLATE_TODAY = "public, s-maxage=60, stale-while-revalidate=300"
CACHE_PAST = "public, s-maxage=3600, stale-while-revalidate=86400"
CACHE_GAME = "public, s-maxage=60, stale-while-revalidate=600"
CACHE_MODEL = "public, s-maxage=600, stale-while-revalidate=86400"
CACHE_WORKFLOW = "public, s-maxage=30, stale-while-revalidate=60"

TEAMS = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}

PREDICTION_COLUMNS = (
    "game_id,game_date,home_team,away_team,home_win_prob,away_win_prob,predicted_winner,"
    "actual_winner,correct,bet_placed,bet_amount,odds,profit_loss"
)
PREDICTION_V2_COLUMNS = (
    PREDICTION_COLUMNS + ",season,tip_time_utc,bookmaker,implied_prob,edge,bankroll_at_bet,"
    "kelly_full,kelly_fraction,model_name,predicted_at,status,home_score,away_score,skip_reason"
)


def bad_request(detail):
    return error_response(400, "bad_request", detail=detail)


def today_et():
    """Today's date on the US East Coast, where the NBA schedules its nights."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(EASTERN)).date()
    except Exception:  # no tz database: fall back to a fixed UTC-5 offset
        return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def parse_iso_date(value):
    """A YYYY-MM-DD string as a date, or None when it isn't one."""
    if not value or not DATE_PATTERN.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def pending_migration():
    g.migration_pending = True


def read_v2_rows(table, **kwargs):
    """Read an [M] table only when the v2 schema is on; otherwise flag the payload."""
    if not schema_v2_enabled():
        pending_migration()
        return pd.DataFrame()
    return read_rows(table, **kwargs)


def read_predictions(**kwargs):
    """predictions rows, with the [M] columns when the v2 schema has them."""
    if schema_v2_enabled():
        try:
            return select_rows("predictions", columns=PREDICTION_V2_COLUMNS, **kwargs)
        except MissingColumnError:
            pass
    pending_migration()
    return read_rows("predictions", columns=PREDICTION_COLUMNS, **kwargs)


def game_id_filter_value(game_id):
    # predictions.game_id is bigint until migration 0001 turns it into 10-char text.
    return game_id if schema_v2_enabled() else int(game_id)


def season_or_all_from_request():
    """"all", a known season, the latest season, or None when ?season= is malformed."""
    if (request.args.get("season") or "").strip().lower() == "all":
        return "all"
    return season_from_request()


def season_or_all_filters(column, season):
    return [] if season == "all" else season_filters(column, season)


def money(value):
    return round(float(value), 2)


def record_text(wins, losses):
    return f"{wins}-{losses}"


def as_int(value):
    number = safe_float(value)
    return int(number) if number is not None else None


def pick_probability(row):
    """The model's probability for its own pick (None when the pick is unknown)."""
    predicted = row.get("predicted_winner")
    if predicted and predicted == row.get("home_team"):
        return normalize_probability(row.get("home_win_prob"))
    if predicted and predicted == row.get("away_team"):
        return normalize_probability(row.get("away_win_prob"))
    return None


def prediction_edge(row):
    stored = safe_float(row.get("edge"))
    if stored is not None:
        return stored
    prob = pick_probability(row)
    implied = implied_probability(row.get("odds"))
    if prob is None or implied is None:
        return None
    return prob - implied


def bet_amount(row):
    return safe_float(row.get("bet_amount"), 0.0) or 0.0


def is_settled(row):
    return row.get("correct") in (0, 1)


def prediction_status(row):
    status = row.get("status")
    if status in ("scheduled", "final", "postponed", "void"):
        # 0011 backfills 'final' only where actual_winner is set; trust a settled result.
        return "final" if status == "scheduled" and is_settled(row) else status
    return "final" if is_settled(row) else "scheduled"


def bet_result(row):
    if prediction_status(row) in ("void", "postponed"):
        return "void" if bet_amount(row) > 0 else None
    if row.get("correct") == 1:
        return "hit"
    if row.get("correct") == 0:
        return "miss"
    return None


def team_block(tricode, prob, form, score):
    form = form or {}
    return {
        "tricode": tricode,
        "name": TEAMS.get(tricode),
        "record": form.get("record"),
        "l10": form.get("l10"),
        "win_prob": prob,
        "score": score,
    }


def build_book_grid(rows):
    """The 5-book "odds at time of bet" grid from book_odds rows for one game."""
    if not rows:
        return None
    books = list(PREFERRED_BOOKS)
    for row in rows:
        if row.get("bookmaker") and row["bookmaker"] not in books:
            books.append(row["bookmaker"])
    by_book = {row.get("bookmaker"): row for row in rows}
    home = [as_int(by_book.get(b, {}).get("home_price")) for b in books]
    away = [as_int(by_book.get(b, {}).get("away_price")) for b in books]

    def best(prices):
        # A higher American price always pays more, for favourites and underdogs alike.
        priced = [(p, i) for i, p in enumerate(prices) if p is not None]
        return max(priced)[1] if priced else None

    return {
        "books": books, "home": home, "away": away,
        "best_home_idx": best(home), "best_away_idx": best(away),
    }


def build_game(row, grids=None, forms=None):
    """One /api/slate games[] item (04 sec2) from a predictions row."""
    grids = grids or {}
    forms = forms or {}
    game_id = normalize_game_id(row["game_id"])
    home, away = row.get("home_team"), row.get("away_team")
    odds = as_int(row.get("odds"))
    implied = safe_float(row.get("implied_prob"))
    if implied is None:
        implied = implied_probability(odds)
    amount = bet_amount(row)
    bet = None
    if amount > 0:
        bet = {
            "side": row.get("bet_placed") or row.get("predicted_winner"),
            "amount": money(amount),
            "bankroll_at_bet": safe_float(row.get("bankroll_at_bet")),
            "kelly_full": safe_float(row.get("kelly_full")),
            "kelly_fraction": safe_float(row.get("kelly_fraction")),
            "result": bet_result(row),
            "profit_loss": safe_float(row.get("profit_loss")),
        }
    return {
        "game_id": game_id,
        "date": row.get("game_date"),
        "tip_time_utc": row.get("tip_time_utc"),
        "status": prediction_status(row),
        "home": team_block(home, normalize_probability(row.get("home_win_prob")),
                           forms.get(home), as_int(row.get("home_score"))),
        "away": team_block(away, normalize_probability(row.get("away_win_prob")),
                           forms.get(away), as_int(row.get("away_score"))),
        "pick": row.get("predicted_winner"),
        "pick_prob": pick_probability(row),
        "odds": odds,
        "bookmaker": row.get("bookmaker"),
        "implied_prob": implied,
        "edge": prediction_edge(row),
        "bet": bet,
        "result": bet_result(row) if amount > 0 else (
            {1: "hit", 0: "miss"}.get(row.get("correct"))
        ),
        "skip_reason": row.get("skip_reason"),
        "book_grid": build_book_grid(grids.get(game_id)),
    }


def book_grids_for(game_ids):
    """book_odds rows grouped by game_id, one query for the whole slate ([M])."""
    ids = sorted({normalize_game_id(i) for i in game_ids})
    if not ids:
        return {}
    grouped = {}
    for row in records(read_v2_rows(
        "book_odds",
        columns="game_id,bookmaker,home_price,away_price",
        filters=[("game_id", "in", ids)],
        order_by=["game_id", "bookmaker"],
    )):
        grouped.setdefault(normalize_game_id(row["game_id"]), []).append(row)
    return grouped


def team_forms_for(teams, season, before_date):
    """Season record and last-10 string per team as of before_date ([M]: games is only
    complete after the Gate M re-collect, so pre-migration records would be wrong)."""
    teams = sorted({t for t in teams if t})
    if not teams:
        return {}
    rows = records(read_v2_rows(
        "games",
        columns="GAME_DATE,TEAM_ABBREVIATION,WL",
        filters=[("SEASON", "eq", season), ("GAME_DATE", "lt", before_date),
                 ("TEAM_ABBREVIATION", "in", teams)],
        order_by="GAME_DATE",
    ))
    results = {}
    for row in rows:
        if row.get("WL") in ("W", "L"):
            results.setdefault(row.get("TEAM_ABBREVIATION"), []).append(row["WL"])
    return {
        team: {"record": record_text(wl.count("W"), wl.count("L")), "l10": "".join(wl[-10:])}
        for team, wl in results.items()
    }


def bankroll_around(game_date):
    """(balance before the night, balance after it) from bankroll ([M])."""
    rows = records(read_v2_rows(
        "bankroll", columns="date,balance",
        filters=[("date", "lte", game_date)], order_by="date", descending=True, limit=2,
    ))
    if not rows:
        return None, None
    if str(rows[0].get("date"))[:10] == game_date:
        before = safe_float(rows[1].get("balance")) if len(rows) > 1 else None
        return before, safe_float(rows[0].get("balance"))
    return safe_float(rows[0].get("balance")), None


def win_loss(rows):
    wins = sum(1 for r in rows if r.get("correct") == 1)
    losses = sum(1 for r in rows if r.get("correct") == 0)
    return wins, losses


def night_recap(rows, game_date):
    settled = [r for r in rows if is_settled(r)]
    bets = [r for r in settled if bet_amount(r) > 0]
    staked = sum(bet_amount(r) for r in bets)
    net = sum(safe_float(r.get("profit_loss"), 0.0) or 0.0 for r in bets)
    before, after = bankroll_around(game_date)

    def bet_ref(row):
        return {"game_id": normalize_game_id(row["game_id"]),
                "profit_loss": money(safe_float(row.get("profit_loss"), 0.0) or 0.0)}

    ranked = sorted(bets, key=lambda r: safe_float(r.get("profit_loss"), 0.0) or 0.0)
    return {
        "net_pl": money(net),
        "bankroll_before": before,
        "bankroll_after": after,
        "picks": record_text(*win_loss(settled)),
        "bets": record_text(*win_loss(bets)),
        "staked": money(staked),
        "roi": (net / staked) if staked > 0 else None,
        "best_bet": bet_ref(ranked[-1]) if ranked else None,
        "worst_bet": bet_ref(ranked[0]) if ranked else None,
    }


def tip_order_key(game):
    return (game.get("tip_time_utc") or "", game["game_id"])


def latest_prediction_date_before(day):
    earlier = [d for d in _prediction_dates() if d < day]
    return max(earlier) if earlier else None


def slate_phase(games, day, today, latest_date):
    if games:
        if all(game["status"] in ("final", "void", "postponed") for game in games):
            return "all_final"
        return "picks_posted"
    if day < today.isoformat():
        return "no_games"
    # No schedule source until B2/B7: a date within a week of the last slate is taken to
    # be a game night whose picks haven't posted yet; anything later is a break.
    if latest_date and (date.fromisoformat(day) - date.fromisoformat(latest_date)).days <= 7:
        return "before_predictions"
    return "no_games"


@app.route("/api/slate")
def api_slate():
    today = today_et()
    raw = (request.args.get("date") or "").strip()
    day = parse_iso_date(raw) if raw else today
    if day is None:
        return bad_request("date must look like 2026-04-12")
    day = day.isoformat()

    rows = records(read_predictions(filters=[("game_date", "eq", day)], order_by="game_id"))
    latest_date = latest_prediction_date_before(day)
    season = season_for(day)
    grids = book_grids_for(r["game_id"] for r in rows) if rows else {}
    forms = team_forms_for(
        [t for r in rows for t in (r.get("home_team"), r.get("away_team"))], season, day
    ) if rows else {}
    games = sorted((build_game(r, grids, forms) for r in rows), key=tip_order_key)

    phase = slate_phase(games, day, today, latest_date)
    is_past = day < today.isoformat()
    settled_bets = [r for r in rows if is_settled(r) and bet_amount(r) > 0]
    days_since_last = (
        (date.fromisoformat(day) - date.fromisoformat(latest_date)).days if latest_date else None
    )
    payload = {
        "date": day,
        "season": season,
        "is_past": is_past,
        "phase": phase,
        "offseason": phase == "no_games" and (
            days_since_last > 30 if days_since_last is not None
            else not any(d > day for d in _prediction_dates())
        ),
        "last_slate_date": latest_date,
        "summary": {
            "games": len(games),
            "final": sum(1 for x in games if x["status"] == "final"),
            "live": 0,  # live state comes from /api/live-scores
            "upcoming": sum(1 for x in games if x["status"] == "scheduled"),
            "bets_placed": sum(1 for r in rows if bet_amount(r) > 0),
            "staked": money(sum(bet_amount(r) for r in rows)),
            "settled_pl": money(sum(safe_float(r.get("profit_loss"), 0.0) or 0.0
                                    for r in settled_bets)),
        },
        "games": games,
        "recap": night_recap(rows, day) if rows and (is_past or phase == "all_final") else None,
    }
    return api_response(payload, CACHE_PAST if is_past else CACHE_SLATE_TODAY)


def tape_block(ctx, elo):
    ctx = ctx or {}
    return {
        "elo": elo,
        "rest_days": safe_float(ctx.get("rest_days")),
        "roll_pts": safe_float(ctx.get("roll_pts")),
        "roll_fg_pct": safe_float(ctx.get("roll_fg_pct")),
        "roll_reb": safe_float(ctx.get("roll_reb")),
        "roll_ast": safe_float(ctx.get("roll_ast")),
        "roll_tov": safe_float(ctx.get("roll_tov")),
        "roll_stocks": safe_float(ctx.get("roll_stocks")),
    }


def tape_better(home, away):
    better = {}
    for key in home:
        h, a = home[key], away[key]
        if h is None or a is None or h == a:
            continue
        lower_wins = key == "roll_tov"  # turnovers: fewer is better
        better[key] = "home" if (h < a) == lower_wins else "away"
    return better


@app.route("/api/game/<game_id>")
def api_game(game_id):
    if not GAME_ID_PATTERN.match(game_id):
        return bad_request("game_id must be 10 digits")
    rows = records(read_predictions(
        filters=[("game_id", "eq", game_id_filter_value(game_id))], order_by="game_id", limit=1,
    ))
    if not rows:
        return error_response(404, "not_found")
    row = rows[0]
    day = str(row.get("game_date"))[:10]
    home_team, away_team = row.get("home_team"), row.get("away_team")

    grids = book_grids_for([row["game_id"]])
    forms = team_forms_for([home_team, away_team], season_for(day), day)
    game = build_game(row, grids, forms)

    home_ctx = _latest_features_by_team([home_team], "HOME", day).get(home_team, {})
    away_ctx = _latest_features_by_team([away_team], "AWAY", day).get(away_team, {})
    ids = [c.get("team_id") for c in (home_ctx, away_ctx) if c.get("team_id") is not None]
    elo = _latest_elo_by_team(ids, day)

    def team_elo(ctx):
        return elo.get(int(ctx["team_id"])) if ctx.get("team_id") is not None else None

    home_tape = tape_block(home_ctx, team_elo(home_ctx))
    away_tape = tape_block(away_ctx, team_elo(away_ctx))
    result = None
    if is_settled(row) or prediction_status(row) in ("void", "postponed"):
        result = {
            "winner": row.get("actual_winner"),
            "home_score": as_int(row.get("home_score")),
            "away_score": as_int(row.get("away_score")),
            "correct": row.get("correct"),
        }
    payload = {
        "game": game,
        "tape": {"home": home_tape, "away": away_tape, "better": tape_better(home_tape, away_tape)},
        "predicted_at": row.get("predicted_at"),
        "model_name": row.get("model_name"),
        "result": result,
    }
    return api_response(payload, CACHE_PAST if day < today_et().isoformat() else CACHE_GAME)


@app.route("/api/days")
def api_days():
    raw_end = (request.args.get("end") or "").strip()
    end = parse_iso_date(raw_end) if raw_end else today_et()
    if end is None:
        return bad_request("end must look like 2026-04-12")
    raw_n = (request.args.get("n") or "7").strip()
    if not raw_n.isdigit() or not 1 <= int(raw_n) <= 31:
        return bad_request("n must be a whole number from 1 to 31")
    n = int(raw_n)

    all_dates = sorted(set(d for d in _prediction_dates() if d <= end.isoformat()), reverse=True)
    dates = all_dates[:n]
    days = []
    if dates:
        rows = records(read_rows(
            "predictions",
            columns="game_date,correct,bet_amount,profit_loss",
            filters=[("game_date", "in", dates)],
            order_by="game_date",
        ))
        by_date = {}
        for row in rows:
            by_date.setdefault(str(row.get("game_date"))[:10], []).append(row)
        for day in dates:
            night = by_date.get(day, [])
            bets = [r for r in night if bet_amount(r) > 0]
            days.append({
                "date": day,
                "games": len(night),
                "picks": record_text(*win_loss(night)),
                "bets": record_text(*win_loss(bets)),
                "net_pl": money(sum(safe_float(r.get("profit_loss"), 0.0) or 0.0
                                    for r in bets if is_settled(r))),
                "pending": sum(1 for r in night if not is_settled(r)),
            })
    return api_response({"days": days, "has_earlier": len(all_dates) > n})


def edge_bucket(edge):
    if edge is None:
        return None
    pct = edge * 100
    if pct < 0:
        return "<0"
    if pct < 3:
        return "0-3"
    if pct < 6:
        return "3-6"
    if pct < 10:
        return "6-10"
    return "10+"


def split_rows(bets, key_fn, order):
    groups = {}
    for row in bets:
        key = key_fn(row)
        if key is not None:
            groups.setdefault(key, []).append(row)
    keys = [k for k in order if k in groups] + sorted(k for k in groups if k not in order)
    out = []
    for key in keys:
        rows = groups[key]
        staked = sum(bet_amount(r) for r in rows)
        pl = sum(safe_float(r.get("profit_loss"), 0.0) or 0.0 for r in rows)
        wins, losses = win_loss(rows)
        out.append({"key": key, "bets": len(rows), "w": wins, "l": losses,
                    "staked": money(staked), "pl": money(pl),
                    "roi": (pl / staked) if staked > 0 else None})
    return out


def drawdown(series):
    worst = {"amount": 0.0, "peak_date": None, "trough_date": None}
    if not series:
        return worst
    peak, worst_amount = series[0], 0.0
    for point in series:
        if point["bankroll"] > peak["bankroll"]:
            peak = point
        amount = peak["bankroll"] - point["bankroll"]
        if amount > worst_amount + 0.005:  # the first night of the deepest trough wins
            worst_amount = amount
            worst = {"amount": money(amount), "peak_date": peak["date"],
                     "trough_date": point["date"]}
    return worst


def bankroll_by_date(season):
    """{date: balance} from bankroll ([M]); empty before the migration."""
    rows = records(read_v2_rows(
        "bankroll", columns="date,balance",
        filters=season_or_all_filters("date", season), order_by="date",
    ))
    return {str(r["date"])[:10]: safe_float(r.get("balance"))
            for r in rows if r.get("date") and safe_float(r.get("balance")) is not None}


def nightly_series(rows, balances):
    """One point per prediction date, plus a start point the day before the first."""
    by_date = {}
    for row in rows:
        by_date.setdefault(str(row.get("game_date"))[:10], []).append(row)
    dates = sorted(by_date)
    if not dates:
        return [], START_BANKROLL
    first = date.fromisoformat(dates[0])
    start_balance = START_BANKROLL
    if balances:
        before = [d for d in balances if d < dates[0]]
        start_balance = balances[max(before)] if before else balances[min(balances)]
    series = [{"date": (first - timedelta(days=1)).isoformat(), "bankroll": money(start_balance),
               "nightly_pl": 0.0, "bets": "0-0", "picks": "0-0", "pending": 0}]
    running = start_balance
    for day in dates:
        night = by_date[day]
        bets = [r for r in night if bet_amount(r) > 0 and is_settled(r)]
        nightly = sum(safe_float(r.get("profit_loss"), 0.0) or 0.0 for r in bets)
        running += nightly
        # With a bankroll table, its balance wins; otherwise 1000 + cumulative P/L (04 sec6).
        balance = balances.get(day, running) if balances else running
        if balances:
            running = balance
        series.append({
            "date": day, "bankroll": money(balance), "nightly_pl": money(nightly),
            "bets": record_text(*win_loss(bets)),
            "picks": record_text(*win_loss(night)),
            "pending": sum(1 for r in night if not is_settled(r)),
        })
    return series, start_balance


@app.route("/api/performance")
def api_performance():
    season = season_or_all_from_request()
    if season is None:
        return bad_season_response()
    seasons = available_seasons()
    rows = records(read_predictions(
        filters=season_or_all_filters("game_date", season), order_by=["game_date", "game_id"],
    ))
    balances = bankroll_by_date(season)
    series, start_balance = nightly_series(rows, balances)
    settled = [r for r in rows if is_settled(r)]
    bets = [r for r in settled if bet_amount(r) > 0]
    staked = sum(bet_amount(r) for r in bets)
    net = sum(safe_float(r.get("profit_loss"), 0.0) or 0.0 for r in bets)
    picks_w, picks_l = win_loss(settled)
    bankroll = series[-1]["bankroll"] if series else None
    streaks = longest_streaks(settled)

    kpis = {
        "bankroll": bankroll,
        "start_bankroll": money(start_balance),
        "net_pl": money(net),
        "roi": (net / staked) if staked > 0 else None,
        "staked": money(staked),
        "bets": record_text(*win_loss(bets)),
        "picks": record_text(picks_w, picks_l),
        "accuracy": (picks_w / len(settled)) if settled else None,
        "max_drawdown": drawdown(series),
        "longest_win_streak": streaks["longest_win_streak"],
        "longest_loss_streak": streaks["longest_loss_streak"],
        "pending": len(rows) - len(settled),
    }
    splits = {
        "book": split_rows(bets, lambda r: r.get("bookmaker"), PREFERRED_BOOKS),
        "confidence": split_rows(bets, lambda r: confidence_bucket(pick_probability(r)),
                                 ["high", "medium", "low"]),
        "edge": split_rows(bets, lambda r: edge_bucket(prediction_edge(r)),
                           ["<0", "0-3", "3-6", "6-10", "10+"]),
    }
    recent = ["W" if r.get("correct") == 1 else "L" for r in bets][-RECENT_BETS:]
    payload = {
        "season": season,
        "seasons": seasons,
        "kpis": kpis,
        "series": series,
        "splits": splits,
        "recent_bets": recent,
    }
    return api_response(payload)


def prediction_log_row(row):
    game = build_game(row)
    return {
        "game_id": game["game_id"],
        "date": str(row.get("game_date"))[:10],
        "matchup": f"{row.get('away_team')} @ {row.get('home_team')}",
        "home": row.get("home_team"),
        "away": row.get("away_team"),
        "pick": game["pick"],
        "pick_prob": game["pick_prob"],
        "odds": game["odds"],
        "bookmaker": game["bookmaker"],
        "edge": game["edge"],
        "bet_amount": money(bet_amount(row)),
        "result": game["result"] or ("void" if game["status"] == "void" else "pending"),
        "profit_loss": safe_float(row.get("profit_loss")),
    }


def team_matches(row, query):
    q = query.strip().lower()
    for side in ("home_team", "away_team"):
        tricode = row.get(side) or ""
        if tricode.lower() == q or q in (TEAMS.get(tricode) or "").lower():
            return True
    return False


@app.route("/api/predictions")
def api_predictions():
    season = season_or_all_from_request()
    if season is None:
        return bad_season_response()
    args = request.args
    team = (args.get("team") or "").strip()
    if team and not TEAM_QUERY_PATTERN.match(team):
        return bad_request("team must be a team code or name")
    bets_only = (args.get("bets_only") or "false").strip().lower()
    if bets_only not in ("true", "false", "1", "0"):
        return bad_request("bets_only must be true or false")
    result = (args.get("result") or "any").strip().lower()
    if result not in ("any", "hit", "miss", "pending"):
        return bad_request("result must be any, hit, miss or pending")
    book = (args.get("book") or "").strip()
    min_edge = None
    if (args.get("min_edge") or "").strip():
        min_edge = safe_float(args.get("min_edge"))
        if min_edge is None or not -1 <= min_edge <= 1:
            return bad_request("min_edge must be a fraction from -1 to 1")
    try:
        page = int(args.get("page", 1))
        page_size = int(args.get("page_size", 25))
    except ValueError:
        return bad_request("page and page_size must be whole numbers")
    if page < 1 or not 1 <= page_size <= 100:
        return bad_request("page must be at least 1 and page_size from 1 to 100")

    rows = records(read_predictions(
        filters=season_or_all_filters("game_date", season),
        order_by=["game_date", "game_id"], descending=True,
    ))
    # Newest first, whatever order the store returned (04 sec7).
    rows.sort(key=lambda r: (str(r.get("game_date")), normalize_game_id(r["game_id"])),
              reverse=True)
    books = sorted({r.get("bookmaker") for r in rows if r.get("bookmaker")})
    if team:
        rows = [r for r in rows if team_matches(r, team)]
    if bets_only in ("true", "1"):
        rows = [r for r in rows if bet_amount(r) > 0]
    if result == "hit":
        rows = [r for r in rows if r.get("correct") == 1]
    elif result == "miss":
        rows = [r for r in rows if r.get("correct") == 0]
    elif result == "pending":
        rows = [r for r in rows if not is_settled(r)]
    if book:
        rows = [r for r in rows if r.get("bookmaker") == book]
    if min_edge is not None:
        rows = [r for r in rows if (prediction_edge(r) is not None
                                    and prediction_edge(r) >= min_edge)]
    total = len(rows)
    start = (page - 1) * page_size
    payload = {
        "season": season,
        "total": total,
        "page": page,
        "page_size": page_size,
        "books": books,
        "rows": [prediction_log_row(r) for r in rows[start:start + page_size]],
    }
    return api_response(payload)


CALIBRATION_EDGES = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 1.0001]


def calibration_buckets(settled):
    buckets = []
    for low, high in zip(CALIBRATION_EDGES, CALIBRATION_EDGES[1:]):
        rows = [(p, r) for r in settled
                if (p := pick_probability(r)) is not None and low <= p < high]
        if not rows:
            continue
        label = f"{low:.2f}-{min(high, 1.0):.2f}"
        buckets.append({
            "bucket": label,
            "n": len(rows),
            "predicted": sum(p for p, _ in rows) / len(rows),
            "actual": sum(1 for _, r in rows if r.get("correct") == 1) / len(rows),
        })
    return buckets


def latest_model_run():
    rows = records(read_v2_rows(
        "model_runs",
        columns="trained_at,production_model,cutoff_date,test_games,leaderboard",
        order_by="trained_at", descending=True, limit=1,
    ))
    return rows[0] if rows else None


@app.route("/api/model")
def api_model():
    season = season_from_request()
    if season is None:
        return bad_season_response()
    settled = [r for r in records(read_predictions(
        filters=[*season_filters("game_date", season), ("correct", "not_is", "null")],
        order_by=["game_date", "game_id"],
    )) if is_settled(r)]
    wins, _ = win_loss(settled)

    run = latest_model_run()
    production, trained_at, cutoff, test, leaderboard = None, None, None, None, []
    if run:
        production = run.get("production_model")
        trained_at = run.get("trained_at")
        cutoff = run.get("cutoff_date")
        board = run.get("leaderboard") if isinstance(run.get("leaderboard"), list) else []
        leaderboard = [{
            "rank": as_int(item.get("rank")),
            "model": item.get("model"),
            "accuracy": safe_float(item.get("accuracy")),
            "log_loss": safe_float(item.get("log_loss")),
            "brier_score": safe_float(item.get("brier_score")),
        } for item in board if isinstance(item, dict)]
        mine = next((i for i in board if isinstance(i, dict) and i.get("model") == production), None)
        if mine:
            test = {
                "games": as_int(mine.get("test_games")) or as_int(run.get("test_games")),
                "accuracy": safe_float(mine.get("accuracy")),
                "brier": safe_float(mine.get("brier_score")),
                "log_loss": safe_float(mine.get("log_loss")),
                "roc_auc": safe_float(mine.get("roc_auc")),
                "baseline_home_win_rate": safe_float(mine.get("baseline_home_win_rate")),
            }
    payload = {
        "production_model": production,
        "trained_at": trained_at,
        "cutoff_date": cutoff,
        "test": test,
        "season_live": {
            "season": season,
            "picks": len(settled),
            "accuracy": (wins / len(settled)) if settled else None,
        },
        "calibration": calibration_buckets(settled),
        "leaderboard": leaderboard,
    }
    return api_response(payload, CACHE_MODEL)


WORKFLOW_KINDS = ("morning", "predict", "manual")
MORNING_RUN_HOUR_ET = 6
RUNNING_STALE_AFTER = timedelta(hours=2)
MISSED_GRACE = timedelta(minutes=30)


def parse_timestamp(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def now_utc():
    return datetime.now(timezone.utc)


def eastern_time(day, hour):
    """day at hour:00 US Eastern, as an aware datetime."""
    try:
        from zoneinfo import ZoneInfo

        return datetime(day.year, day.month, day.day, hour, tzinfo=ZoneInfo(EASTERN))
    except Exception:
        return datetime(day.year, day.month, day.day, hour, tzinfo=timezone(timedelta(hours=-5)))


def workflow_state(kind, row, now, today):
    status = row.get("status")
    started = parse_timestamp(row.get("started_at"))
    if status == "running" and started and now - started < RUNNING_STALE_AFTER:
        return "running"
    if status in ("failed", "partial"):
        return "failed"
    if status == "running":
        return "failed"  # a run still "running" after 2h died without finishing
    if kind == "morning" and str(row.get("run_date"))[:10] < today.isoformat():
        # The morning job is due at 06:00 ET; after a 30 min grace it counts as missed.
        if now > eastern_time(today, MORNING_RUN_HOUR_ET) + MISSED_GRACE:
            return "missed"
    return "ok"


@app.route("/api/workflow-status")
def api_workflow_status():
    controls = run_controls_allowed(request)
    running = False
    if controls:
        import daily_workflow  # lazy: local laptop only, never on Vercel

        running = bool(daily_workflow.workflow_is_running())

    rows = records(read_v2_rows(
        "workflow_log",
        columns="run_date,kind,trigger,started_at,finished_at,status,pipeline_ok,"
                "predict_ok,sms_sent,notes",
        order_by="started_at", descending=True, limit=30,
    ))
    now, today = now_utc(), today_et()
    latest = {kind: None for kind in WORKFLOW_KINDS}
    for row in rows:
        kind = row.get("kind") if row.get("kind") in WORKFLOW_KINDS else "manual"
        if latest[kind] is not None:
            continue
        latest[kind] = {
            "run_date": str(row.get("run_date"))[:10] if row.get("run_date") else None,
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "status": row.get("status"),
            "state": workflow_state(kind, row, now, today),
            "trigger": row.get("trigger"),
            "pipeline_ok": row.get("pipeline_ok"),
            "predict_ok": row.get("predict_ok"),
            "sms_sent": row.get("sms_sent"),
            "notes": (row.get("notes") or "")[:200],
        }
    payload = {"controls_allowed": bool(controls), "running": running, "latest": latest}
    # The local view (controls allowed) is per-machine: never let anything cache it.
    return api_response(payload, "private, no-store" if controls else CACHE_WORKFLOW)


# ---------------------------------------------------------------------------
# Run now (02-TARGET-ARCHITECTURE sec5): only on the laptop that runs Flask.
# ---------------------------------------------------------------------------

LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}
LOOPBACK_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}  # urlsplit(...).hostname strips [] from IPv6
RUN_WORKFLOW_HEADER = "X-Requested-With"
RUN_WORKFLOW_HEADER_VALUE = "run-now"


def _same_origin_loopback_request(req):
    """SEC-F1: reject cross-site/DNS-rebound calls. The Host header's hostname must be a
    loopback name; a present Origin must match that Host exactly (same-origin, loopback);
    and a non-simple header must be present so a cross-site browser request needs a CORS
    preflight (which the app never allows, since it sends no CORS headers at all)."""
    hostname = urlsplit(f"//{req.host}").hostname
    if hostname not in LOOPBACK_HOSTNAMES:
        return False

    origin = req.headers.get("Origin")
    if origin is not None and origin != f"http://{req.host}":
        return False  # covers a hostile Origin and the CORS-special "Origin: null"

    return req.headers.get(RUN_WORKFLOW_HEADER) == RUN_WORKFLOW_HEADER_VALUE


def run_controls_allowed(req):
    return (
        not os.getenv("VERCEL")
        and os.getenv("ALLOW_RUN_WORKFLOW", "false").strip().lower() == "true"
        and req.remote_addr in LOOPBACK_ADDRESSES  # never a forwarded/proxy header; no ProxyFix
        and _same_origin_loopback_request(req)
    )


@app.route("/api/run-workflow", methods=["POST"])
def api_run_workflow():
    if not run_controls_allowed(request):
        return error_response(403, "forbidden")

    import daily_workflow  # lazy: the pipeline runner is never loaded on Vercel

    if daily_workflow.workflow_is_running():
        return error_response(409, "already_running")
    started, _ = daily_workflow.run_workflow_async()
    if not started:
        return error_response(409, "already_running")
    response = jsonify({"started": True, "kind": "manual"})
    response.status_code = 202
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
