"""
daily_workflow.py — NBA Predictor daily automation orchestrator.

Runs the morning pipeline (collect → features → elo → model → track) and
evening predictions, then sends a Twilio SMS summary and logs the run.

Can be invoked directly:
    python daily_workflow.py

Or triggered via the Flask API (POST /api/run-workflow).
"""

import os
import sys
import sqlite3
import subprocess
import threading
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = 'data/nba.db'
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def ensure_workflow_log_table():
    """Create workflow_log table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date      TEXT,
            started_at    TEXT,
            finished_at   TEXT,
            status        TEXT,
            pipeline_ok   INTEGER,
            predict_ok    INTEGER,
            sms_sent      INTEGER,
            notes         TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_run(run_date, started_at, finished_at, status, pipeline_ok, predict_ok, sms_sent, notes=''):
    ensure_workflow_log_table()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO workflow_log
        (run_date, started_at, finished_at, status, pipeline_ok, predict_ok, sms_sent, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (run_date, started_at, finished_at, status, pipeline_ok, predict_ok, sms_sent, notes))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def run_bat(bat_path):
    """
    Run a .bat file via cmd.exe, streaming output.
    Returns (returncode, combined_stdout_stderr).
    """
    result = subprocess.run(
        ['cmd.exe', '/c', bat_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    return result.returncode, output


# ---------------------------------------------------------------------------
# Data queries
# ---------------------------------------------------------------------------

def get_yesterdays_results():
    """Return a list of dicts for yesterday's completed predictions."""
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql(f"""
            SELECT home_team, away_team, predicted_winner, actual_winner,
                   correct, bet_placed, bet_amount, odds, profit_loss
            FROM predictions
            WHERE game_date = '{yesterday}' AND actual_winner IS NOT NULL
        """, conn)
        conn.close()
        return df.to_dict('records')
    except Exception:
        return []


def get_todays_predictions():
    """Return a list of dicts for today's pending predictions."""
    today = date.today().strftime('%Y-%m-%d')
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql(f"""
            SELECT home_team, away_team, home_win_prob, away_win_prob,
                   predicted_winner, bet_placed, bet_amount, odds
            FROM predictions
            WHERE game_date = '{today}'
        """, conn)
        conn.close()
        return df.to_dict('records')
    except Exception:
        return []


def get_overall_stats():
    """Return overall prediction accuracy and bankroll info."""
    try:
        conn = sqlite3.connect(DB_PATH)
        preds = pd.read_sql(
            "SELECT correct, profit_loss FROM predictions WHERE correct IS NOT NULL", conn
        )
        bankroll_row = pd.read_sql(
            "SELECT balance FROM bankroll ORDER BY date DESC, rowid DESC LIMIT 1", conn
        )
        conn.close()

        if preds.empty:
            return {}

        total = len(preds)
        correct = int(preds['correct'].sum())
        total_pl = float(preds['profit_loss'].sum())
        bankroll = float(bankroll_row['balance'].iloc[0]) if not bankroll_row.empty else 1000.0

        return {
            'total': total,
            'correct': correct,
            'accuracy': correct / total if total else 0,
            'total_pl': total_pl,
            'bankroll': bankroll,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# SMS formatting & sending
# ---------------------------------------------------------------------------

def format_sms(yesterday_results, today_predictions, stats):
    """Build the daily SMS text."""
    yesterday = (date.today() - timedelta(days=1)).strftime('%b %d')
    today_str = date.today().strftime('%b %d')

    lines = [f"🏀 NBA Daily Summary — {today_str}", ""]

    # Yesterday's results
    lines.append(f"Yesterday's Results ({yesterday}):")
    if yesterday_results:
        for g in yesterday_results:
            mark = '✓' if g['correct'] else '✗'
            pl = g['profit_loss'] or 0
            pl_str = f"+${pl:.2f}" if pl >= 0 else f"-${abs(pl):.2f}"
            lines.append(
                f"  {mark} {g['away_team']} @ {g['home_team']} "
                f"— predicted {g['predicted_winner']}, actual {g['actual_winner']}, P/L: {pl_str}"
            )
    else:
        lines.append("  No completed results for yesterday.")

    if stats:
        acc_pct = f"{stats['accuracy']:.1%}"
        pl_str = f"+${stats['total_pl']:.2f}" if stats['total_pl'] >= 0 else f"-${abs(stats['total_pl']):.2f}"
        lines.append(
            f"Overall: {stats['correct']}-{stats['total'] - stats['correct']} ({acc_pct}) "
            f"| P/L: {pl_str} | Bankroll: ${stats['bankroll']:.2f}"
        )

    lines.append("")

    # Today's predictions
    lines.append(f"Today's Predictions ({today_str}):")
    if today_predictions:
        for g in today_predictions:
            win_prob = g['home_win_prob'] if g['predicted_winner'] == g['home_team'] else g['away_win_prob']
            prob_pct = f"{win_prob:.0%}" if win_prob else "?"
            bet_str = ""
            if g['bet_amount'] and float(g['bet_amount']) > 0:
                odds = int(g['odds']) if g['odds'] else '?'
                odds_str = f"+{odds}" if isinstance(odds, int) and odds > 0 else str(odds)
                bet_str = f" | Bet: ${float(g['bet_amount']):.2f} @ {odds_str}"
            lines.append(
                f"  {g['away_team']} @ {g['home_team']} "
                f"— {g['predicted_winner']} ({prob_pct}){bet_str}"
            )
    else:
        lines.append("  No predictions available for today yet.")

    return "\n".join(lines)


def send_sms(body):
    """Send SMS via Twilio. Returns True on success."""
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    from_number = os.getenv('TWILIO_FROM')
    to_number = os.getenv('TWILIO_TO')

    if not all([account_sid, auth_token, from_number, to_number]):
        print("⚠ Twilio credentials not configured — SMS skipped.")
        return False

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        message = client.messages.create(body=body, from_=from_number, to=to_number)
        print(f"✓ SMS sent — SID: {message.sid}")
        return True
    except Exception as e:
        print(f"✗ SMS failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def run_workflow(send_text=True):
    """
    Full daily workflow:
      1. Run pipeline.bat
      2. Run predict.bat
      3. Build + send SMS summary
      4. Log results to workflow_log
    Returns a dict with status info.
    """
    from datetime import datetime

    ensure_workflow_log_table()

    run_date = date.today().strftime('%Y-%m-%d')
    started_at = datetime.now().isoformat(timespec='seconds')

    print(f"\n{'='*50}")
    print(f"NBA Daily Workflow — {run_date}")
    print(f"{'='*50}\n")

    # Step 1 — pipeline
    print("▶ Running run_pipeline.bat...")
    pipeline_rc, pipeline_out = run_bat(os.path.join(REPO_ROOT, 'run_pipeline.bat'))
    pipeline_ok = pipeline_rc == 0
    print(pipeline_out)
    if pipeline_ok:
        print("✓ Pipeline complete.\n")
    else:
        print(f"✗ Pipeline exited with code {pipeline_rc}.\n")

    # Step 2 — predictions
    print("▶ Running run_predict.bat...")
    predict_rc, predict_out = run_bat(os.path.join(REPO_ROOT, 'run_predict.bat'))
    predict_ok = predict_rc == 0
    print(predict_out)
    if predict_ok:
        print("✓ Predictions complete.\n")
    else:
        print(f"✗ Predictions exited with code {predict_rc}.\n")

    # Step 3 — SMS
    sms_sent = False
    if send_text:
        yesterday_results = get_yesterdays_results()
        today_predictions = get_todays_predictions()
        stats = get_overall_stats()

        sms_body = format_sms(yesterday_results, today_predictions, stats)
        print("📱 Daily SMS:\n")
        print(sms_body)
        print()

        sms_sent = send_sms(sms_body)

    # Step 4 — log
    finished_at = datetime.now().isoformat(timespec='seconds')
    overall_status = 'success' if (pipeline_ok and predict_ok) else 'partial' if (pipeline_ok or predict_ok) else 'failed'
    notes = []
    if not pipeline_ok:
        notes.append('pipeline failed')
    if not predict_ok:
        notes.append('predict failed')
    if send_text and not sms_sent:
        notes.append('sms not sent')

    log_run(run_date, started_at, finished_at, overall_status,
            int(pipeline_ok), int(predict_ok), int(sms_sent), ', '.join(notes))

    result = {
        'run_date': run_date,
        'started_at': started_at,
        'finished_at': finished_at,
        'status': overall_status,
        'pipeline_ok': pipeline_ok,
        'predict_ok': predict_ok,
        'sms_sent': sms_sent,
    }
    print(f"\n{'='*50}")
    print(f"Workflow finished — status: {overall_status}")
    print(f"{'='*50}\n")
    return result


# Background thread reference (used by Flask)
_workflow_thread = None
_workflow_lock = threading.Lock()


def run_workflow_async():
    """Run the workflow in a background thread. Returns immediately."""
    global _workflow_thread
    with _workflow_lock:
        if _workflow_thread and _workflow_thread.is_alive():
            return False, "Workflow already running"
        _workflow_thread = threading.Thread(target=run_workflow, daemon=True)
        _workflow_thread.start()
        return True, "Workflow started"


def workflow_is_running():
    return _workflow_thread is not None and _workflow_thread.is_alive()


if __name__ == '__main__':
    run_workflow()
