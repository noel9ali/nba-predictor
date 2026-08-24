import os
import sqlite3
from datetime import date

from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-me')

DB_PATH = 'data/nba.db'


def get_conn():
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table_name):
    if conn is None:
        return False
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def query_rows(sql, params=()):
    conn = get_conn()
    if conn is None:
        return []
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
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


def ytd_summary_for_year(year):
    rows = query_rows(
        """
        SELECT correct, profit_loss, bet_amount
        FROM predictions
        WHERE substr(game_date, 1, 4) = ?
          AND correct IS NOT NULL
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
        }

    games = len(rows)
    wins = sum(int(r["correct"]) for r in rows if r.get("correct") is not None)
    losses = games - wins
    bets_placed = sum(1 for r in rows if (r.get("bet_amount") or 0) > 0)
    total_staked = sum(float(r.get("bet_amount") or 0) for r in rows)
    total_pl = sum(float(r.get("profit_loss") or 0) for r in rows)
    roi = (total_pl / total_staked) if total_staked > 0 else 0

    bankroll_rows = query_rows(
        """
        SELECT balance
        FROM bankroll
        WHERE substr(date, 1, 4) = ?
        ORDER BY date DESC, rowid DESC
        LIMIT 1
        """,
        (year,),
    )

    bankroll = bankroll_rows[0]["balance"] if bankroll_rows else None

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
    return rows[0]["elo_value"] if rows else None


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
            {side_prefix}_roll_STOCKS AS roll_stocks,
            GAME_DATE
        FROM features
        WHERE {col_team} = ?
        ORDER BY GAME_DATE DESC
        LIMIT 1
        """,
        (team_abbr,),
    )
    return rows[0] if rows else {}


def build_recommendations():
    today = date.today().strftime("%Y-%m-%d")
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
            bet_placed,
            bet_amount,
            odds
        FROM predictions
        WHERE game_date = ?
        ORDER BY home_team, away_team
        """,
        (today,),
    )

    recommendations = []
    for i, game in enumerate(rows):
        home_ctx = latest_team_feature_by_side(game.get("home_team"), "HOME")
        away_ctx = latest_team_feature_by_side(game.get("away_team"), "AWAY")

        home_elo = latest_team_elo(home_ctx.get("team_id"))
        away_elo = latest_team_elo(away_ctx.get("team_id"))

        expected_win_prob = None
        if game.get("predicted_winner") == game.get("home_team"):
            expected_win_prob = game.get("home_win_prob")
        elif game.get("predicted_winner") == game.get("away_team"):
            expected_win_prob = game.get("away_win_prob")

        recommendations.append(
            {
                "id": game.get("game_id") or f"game-{i}",
                "matchup": f"{game.get('away_team')} @ {game.get('home_team')}",
                "home_team": game.get("home_team"),
                "away_team": game.get("away_team"),
                "predicted_winner": game.get("predicted_winner"),
                "expected_win_prob": expected_win_prob,
                "home_win_prob": game.get("home_win_prob"),
                "away_win_prob": game.get("away_win_prob"),
                "bet_amount": game.get("bet_amount"),
                "odds": game.get("odds"),
                "details": {
                    "home_elo": home_elo,
                    "away_elo": away_elo,
                    "home_roll_pts": home_ctx.get("roll_pts"),
                    "home_roll_fg_pct": home_ctx.get("roll_fg_pct"),
                    "home_roll_reb": home_ctx.get("roll_reb"),
                    "home_roll_ast": home_ctx.get("roll_ast"),
                    "home_roll_tov": home_ctx.get("roll_tov"),
                    "home_roll_stocks": home_ctx.get("roll_stocks"),
                    "away_roll_pts": away_ctx.get("roll_pts"),
                    "away_roll_fg_pct": away_ctx.get("roll_fg_pct"),
                    "away_roll_reb": away_ctx.get("roll_reb"),
                    "away_roll_ast": away_ctx.get("roll_ast"),
                    "away_roll_tov": away_ctx.get("roll_tov"),
                    "away_roll_stocks": away_ctx.get("roll_stocks"),
                },
            }
        )
    return recommendations


@app.route("/")
def index():
    years = available_years()
    selected_year = request.args.get("year", years[0])
    if selected_year not in years:
        selected_year = years[0]

    ytd_summary = ytd_summary_for_year(selected_year)
    recommendations = build_recommendations()

    return render_template(
        "index.html",
        today=date.today().strftime("%Y-%m-%d"),
        years=years,
        selected_year=selected_year,
        ytd_summary=ytd_summary,
        recommendations=recommendations,
    )


@app.route("/api/available-years")
def api_available_years():
    return jsonify({"years": available_years()})


@app.route("/api/ytd-summary")
def api_ytd_summary():
    year = request.args.get("year")
    years = available_years()
    if not year or year not in years:
        year = years[0]
    return jsonify(ytd_summary_for_year(year))


@app.route("/api/recommendations")
def api_recommendations():
    return jsonify(
        {
            "date": date.today().strftime("%Y-%m-%d"),
            "recommendations": build_recommendations(),
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
