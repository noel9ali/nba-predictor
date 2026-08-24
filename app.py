import os
import sqlite3
from datetime import date

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

DB_PATH = "data/nba.db"


def safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
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


def query_rows(sql, params=()):
    if not os.path.exists(DB_PATH):
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def available_years():
    rows = query_rows(
        """
        SELECT DISTINCT substr(game_date, 1, 4) AS year
        FROM predictions
        WHERE game_date IS NOT NULL
        ORDER BY year DESC
        """
    )
    years = [r["year"] for r in rows if r.get("year")]
    if not years:
        years = [str(date.today().year)]
    return years


def available_prediction_dates(year):
    rows = query_rows(
        """
        SELECT DISTINCT game_date
        FROM predictions
        WHERE substr(game_date, 1, 4) = ?
        ORDER BY game_date DESC
        """,
        (year,),
    )
    dates = [r["game_date"] for r in rows if r.get("game_date")]
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


def bankroll_series_for_year(year):
    rows = query_rows(
        """
        SELECT date, balance
        FROM bankroll
        WHERE substr(date, 1, 4) = ?
        ORDER BY date ASC, rowid ASC
        """,
        (year,),
    )
    points = []
    for row in rows:
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


def ytd_summary_for_year(year):
    rows = query_rows(
        """
        SELECT game_date, correct, profit_loss, bet_amount
        FROM predictions
        WHERE substr(game_date, 1, 4) = ?
          AND correct IS NOT NULL
        ORDER BY game_date ASC, game_id ASC
        """,
        (year,),
    )

    if not rows:
        return {
            "year": year,
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

    games = len(rows)
    wins = sum(1 for r in rows if r.get("correct") == 1)
    losses = games - wins
    bets_placed = sum(1 for r in rows if (safe_float(r.get("bet_amount"), 0) or 0) > 0)
    total_staked = sum(safe_float(r.get("bet_amount"), 0) or 0 for r in rows)
    total_pl = sum(safe_float(r.get("profit_loss"), 0) or 0 for r in rows)
    roi = (total_pl / total_staked) if total_staked > 0 else 0.0

    bankroll_points = bankroll_series_for_year(year)
    bankroll = bankroll_points[-1]["balance"] if bankroll_points else None
    streaks = longest_streaks(rows)

    return {
        "year": year,
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

    rows = query_rows(
        """
        SELECT elo_value
        FROM (
            SELECT HOME_ELO AS elo_value, GAME_DATE
            FROM elo
            WHERE HOME_TEAM_ID = ?
            UNION ALL
            SELECT AWAY_ELO AS elo_value, GAME_DATE
            FROM elo
            WHERE AWAY_TEAM_ID = ?
        )
        ORDER BY GAME_DATE DESC
        LIMIT 1
        """,
        (team_id, team_id),
    )
    return safe_float(rows[0]["elo_value"]) if rows else None


def latest_team_feature_by_side(team_abbr, side_prefix):
    if not team_abbr:
        return {}

    col_team = f"{side_prefix}_TEAM_ABBREVIATION"
    col_team_id = f"{side_prefix}_TEAM_ID"
    rows = query_rows(
        f"""
        SELECT
            {col_team_id} AS team_id,
            {side_prefix}_roll_PTS AS roll_pts,
            {side_prefix}_roll_FG_PCT AS roll_fg_pct,
            {side_prefix}_roll_REB AS roll_reb,
            {side_prefix}_roll_AST AS roll_ast,
            {side_prefix}_roll_TOV AS roll_tov,
            {side_prefix}_roll_STOCKS AS roll_stocks
        FROM features
        WHERE {col_team} = ?
        ORDER BY GAME_DATE DESC
        LIMIT 1
        """,
        (team_abbr,),
    )
    return rows[0] if rows else {}


def build_recommendations(game_date):
    rows = query_rows(
        """
        SELECT
            game_id,
            game_date,
            home_team,
            away_team,
            home_win_prob,
            away_win_prob,
            predicted_winner,
            bet_amount,
            odds
        FROM predictions
        WHERE game_date = ?
        ORDER BY home_team, away_team
        """,
        (game_date,),
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
        recommendations.append(
            {
                "id": game.get("game_id") or f"game-{i}",
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


def build_dashboard_state(year, game_date):
    ytd = ytd_summary_for_year(year)
    recs = build_recommendations(game_date)
    bankroll_points = bankroll_series_for_year(year)
    peaks = peak_and_trough(bankroll_points)

    return {
        "year": year,
        "game_date": game_date,
        "ytd_summary": ytd,
        "recommendations": recs,
        "confidence_distribution": confidence_distribution(recs),
        "top_edges": top_edges(recs),
        "bankroll_series": bankroll_points,
        "peak_point": peaks["peak"],
        "trough_point": peaks["trough"],
    }


@app.route("/")
def index():
    years = available_years()
    selected_year = request.args.get("year", years[0])
    if selected_year not in years:
        selected_year = years[0]

    dates = available_prediction_dates(selected_year)
    selected_date = request.args.get("game_date", dates[0])
    if selected_date not in dates:
        selected_date = dates[0]

    dashboard_state = build_dashboard_state(selected_year, selected_date)
    return render_template(
        "index.html",
        years=years,
        selected_year=selected_year,
        available_dates=dates,
        selected_date=selected_date,
        dashboard_state=dashboard_state,
    )


@app.route("/api/dashboard-state")
def api_dashboard_state():
    years = available_years()
    selected_year = request.args.get("year", years[0])
    if selected_year not in years:
        selected_year = years[0]

    dates = available_prediction_dates(selected_year)
    selected_date = request.args.get("game_date", dates[0])
    if selected_date not in dates:
        selected_date = dates[0]

    return jsonify(build_dashboard_state(selected_year, selected_date))


@app.route("/api/ytd-summary")
def api_ytd_summary():
    years = available_years()
    year = request.args.get("year", years[0])
    if year not in years:
        year = years[0]
    return jsonify(ytd_summary_for_year(year))


@app.route("/api/recommendations")
def api_recommendations():
    years = available_years()
    year = request.args.get("year", years[0])
    if year not in years:
        year = years[0]
    dates = available_prediction_dates(year)
    game_date = request.args.get("game_date", dates[0])
    if game_date not in dates:
        game_date = dates[0]
    return jsonify({"game_date": game_date, "recommendations": build_recommendations(game_date)})


@app.route("/api/bankroll-series")
def api_bankroll_series():
    years = available_years()
    year = request.args.get("year", years[0])
    if year not in years:
        year = years[0]
    return jsonify({"year": year, "points": bankroll_series_for_year(year)})


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
