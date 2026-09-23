import os
import re
import sys
from datetime import date, datetime, timezone

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from database import (  # noqa: E402  (needs the src/ path above)
    DatabaseError,
    MissingColumnError,
    MissingTableError,
    normalize_game_id,
    select_rows,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

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


def available_seasons():
    df = read_rows(
        "predictions",
        columns="game_date",
        filters=[("game_date", "not_is", "null")],
        order_by="game_date",
        descending=True,
    )
    seasons = list(dict.fromkeys(season_for(r["game_date"]) for r in records(df) if r.get("game_date")))
    if not seasons:
        seasons = [season_for(date.today())]
    return seasons


def available_prediction_dates(season):
    df = read_rows(
        "predictions",
        columns="game_date",
        filters=season_filters("game_date", season),
        order_by="game_date",
        descending=True,
    )
    dates = list(dict.fromkeys(r["game_date"] for r in records(df) if r.get("game_date")))
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


def latest_team_elo(team_id):
    if team_id is None:
        return None

    team_id = int(team_id)
    latest = None
    for side in ("HOME", "AWAY"):
        rows = records(
            read_rows(
                "elo",
                columns=f"GAME_DATE,{side}_ELO",
                filters=[(f"{side}_TEAM_ID", "eq", team_id)],
                order_by="GAME_DATE",
                descending=True,
                limit=1,
            )
        )
        if rows and (latest is None or str(rows[0]["GAME_DATE"]) > str(latest["GAME_DATE"])):
            latest = {"GAME_DATE": rows[0]["GAME_DATE"], "elo_value": rows[0][f"{side}_ELO"]}
    return safe_float(latest["elo_value"]) if latest else None


def latest_team_feature_by_side(team_abbr, side_prefix):
    if not team_abbr:
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
    rows = records(
        read_rows(
            "features",
            columns=",".join(columns.values()),
            filters=[(f"{side_prefix}_TEAM_ABBREVIATION", "eq", team_abbr)],
            order_by="GAME_DATE",
            descending=True,
            limit=1,
        )
    )
    if not rows:
        return {}
    return {alias: rows[0].get(column) for alias, column in columns.items()}


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

        home_ctx = latest_team_feature_by_side(game.get("home_team"), "HOME")
        away_ctx = latest_team_feature_by_side(game.get("away_team"), "AWAY")

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
                    "home_elo": latest_team_elo(home_ctx.get("team_id")),
                    "away_elo": latest_team_elo(away_ctx.get("team_id")),
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

def api_response(payload):
    body = dict(payload)
    body["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body["migration_pending"] = bool(g.get("migration_pending", False))
    response = jsonify(body)
    response.headers["Cache-Control"] = LEGACY_CACHE_CONTROL
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

    return render_template(
        "index.html",
        seasons=seasons,
        selected_season=selected_season,
        available_dates=dates,
        selected_date=selected_date,
        dashboard_state=dashboard_state,
        notice=notice,
    )


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


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
