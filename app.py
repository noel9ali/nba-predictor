"""
app.py — Flask web dashboard for the NBA Predictor daily workflow.

Run:
    python app.py

Then open http://localhost:5000
"""

import os
import sqlite3
from datetime import date, timedelta

import pandas as pd
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-me')

DB_PATH = 'data/nba.db'


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def query_db(sql, params=()):
    """Run a SELECT and return list of dicts."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return []


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    today = date.today().strftime('%Y-%m-%d')
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    # today's predictions
    predictions = query_db(
        "SELECT * FROM predictions WHERE game_date = ? ORDER BY home_team",
        (today,)
    )

    # yesterday's results
    results = query_db(
        "SELECT * FROM predictions WHERE game_date = ? AND actual_winner IS NOT NULL ORDER BY home_team",
        (yesterday,)
    )

    # overall stats
    all_completed = query_db(
        "SELECT correct, profit_loss FROM predictions WHERE correct IS NOT NULL"
    )
    stats = {}
    if all_completed:
        total = len(all_completed)
        correct = sum(r['correct'] for r in all_completed)
        total_pl = sum(r['profit_loss'] or 0 for r in all_completed)
        stats = {
            'total': total,
            'correct': correct,
            'wrong': total - correct,
            'accuracy': f"{correct/total:.1%}" if total else '0.0%',
            'total_pl': f"{total_pl:+.2f}",
        }

    # bankroll
    bankroll_rows = query_db(
        "SELECT balance FROM bankroll ORDER BY date DESC, rowid DESC LIMIT 1"
    )
    bankroll = f"${bankroll_rows[0]['balance']:.2f}" if bankroll_rows else '$1,000.00'

    # latest workflow runs
    workflow_log = query_db(
        "SELECT * FROM workflow_log ORDER BY id DESC LIMIT 10"
    )

    return render_template(
        'index.html',
        today=today,
        yesterday=yesterday,
        predictions=predictions,
        results=results,
        stats=stats,
        bankroll=bankroll,
        workflow_log=workflow_log,
    )


# ---------------------------------------------------------------------------
# JSON API routes
# ---------------------------------------------------------------------------

@app.route('/api/predictions')
def api_predictions():
    today = date.today().strftime('%Y-%m-%d')
    rows = query_db(
        "SELECT * FROM predictions WHERE game_date = ? ORDER BY home_team",
        (today,)
    )
    return jsonify({'date': today, 'predictions': rows})


@app.route('/api/results')
def api_results():
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    rows = query_db(
        "SELECT * FROM predictions WHERE game_date = ? AND actual_winner IS NOT NULL ORDER BY home_team",
        (yesterday,)
    )
    return jsonify({'date': yesterday, 'results': rows})


@app.route('/api/workflow-log')
def api_workflow_log():
    rows = query_db("SELECT * FROM workflow_log ORDER BY id DESC LIMIT 20")
    return jsonify({'log': rows})


@app.route('/api/run-workflow', methods=['POST'])
def api_run_workflow():
    """Trigger the daily workflow in a background thread."""
    from daily_workflow import run_workflow_async, workflow_is_running

    if workflow_is_running():
        return jsonify({'ok': False, 'message': 'Workflow is already running'}), 409

    started, message = run_workflow_async()
    status = 200 if started else 409
    return jsonify({'ok': started, 'message': message}), status


@app.route('/api/workflow-status')
def api_workflow_status():
    """Check whether the workflow is currently running."""
    from daily_workflow import workflow_is_running
    return jsonify({'running': workflow_is_running()})


if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
