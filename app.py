import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, g, jsonify, make_response, render_template, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from database import (  # noqa: E402  (needs the src/ path above)
    DatabaseError,
    MissingColumnError,
    MissingTableError,
    normalize_game_id,
    select_rows,
)

load_dotenv()

# Statics live in public/ so Vercel's CDN serves them; local Flask serves the same
# files at the same /static URL.
app = Flask(__name__, static_folder="public/static", static_url_path="/static")
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
# Run now (02-TARGET-ARCHITECTURE sec5): only on the laptop that runs Flask.
# ---------------------------------------------------------------------------

LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}


def run_controls_allowed(req):
    return (
        not os.getenv("VERCEL")
        and os.getenv("ALLOW_RUN_WORKFLOW", "false").strip().lower() == "true"
        and req.remote_addr in LOOPBACK_ADDRESSES
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
