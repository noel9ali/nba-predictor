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
import subprocess
import threading
from datetime import date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, 'src'))

from database import DatabaseError, MissingTableError, insert_rows, select_rows  # noqa: E402

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WORKFLOW_LOG_MIGRATION = 'supabase/migrations/20260923000500_workflow_log.sql'
LOG_TAIL_CHARS = 4000
SECRET_ENV_VARS = ('SUPABASE_SECRET_KEY', 'ODDS_API_KEY', 'TWILIO_AUTH_TOKEN')


# ---------------------------------------------------------------------------
# Database helpers (Supabase through src/database.py; tables come from migrations)
# ---------------------------------------------------------------------------

def redact_secrets(text):
    """Replace known secret values so they never reach workflow_log."""
    for name in SECRET_ENV_VARS:
        value = os.getenv(name, '').strip()
        if value:
            text = text.replace(value, f'<{name}>')
    return text


def log_run(run_date, started_at, finished_at, status, pipeline_ok, predict_ok, sms_sent, notes='',
            kind='manual', trigger='schedule', log_tail=''):
    """Insert one workflow_log row. A database failure is reported, never raised."""
    row = {
        'run_date': run_date,
        'kind': kind,
        'trigger': trigger,
        'started_at': started_at,
        'finished_at': finished_at,
        'status': status,
        'pipeline_ok': bool(pipeline_ok),
        'predict_ok': bool(predict_ok),
        'sms_sent': bool(sms_sent),
        'notes': notes,
        'log_tail': redact_secrets(log_tail)[-LOG_TAIL_CHARS:],
    }
    try:
        insert_rows('workflow_log', [row])
    except DatabaseError as e:
        print(f"⚠ workflow_log not written ({e}); if the table is missing, apply {WORKFLOW_LOG_MIGRATION}")


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

def _records(df, numeric_columns=()):
    """Rows as dicts; text numbers (pre-migration columns) become floats, NaN becomes None."""
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors='coerce')
    return df.astype(object).where(df.notna(), None).to_dict('records')


def get_yesterdays_results():
    """Return a list of dicts for yesterday's completed predictions."""
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    try:
        df = select_rows(
            'predictions',
            columns='home_team,away_team,predicted_winner,actual_winner,'
                    'correct,bet_placed,bet_amount,odds,profit_loss',
            filters=[('game_date', 'eq', yesterday), ('actual_winner', 'not_is', 'null')],
            order_by='game_id',
        )
        return _records(df, ('bet_amount', 'odds', 'profit_loss'))
    except Exception:
        return []


def get_todays_predictions():
    """Return a list of dicts for today's pending predictions."""
    today = date.today().strftime('%Y-%m-%d')
    try:
        df = select_rows(
            'predictions',
            columns='home_team,away_team,home_win_prob,away_win_prob,'
                    'predicted_winner,bet_placed,bet_amount,odds',
            filters=[('game_date', 'eq', today)],
            order_by='game_id',
        )
        return _records(df, ('home_win_prob', 'away_win_prob', 'bet_amount', 'odds'))
    except Exception:
        return []


def get_overall_stats():
    """Return overall prediction accuracy and bankroll info."""
    try:
        preds = select_rows(
            'predictions',
            columns='correct,profit_loss',
            filters=[('correct', 'not_is', 'null')],
            order_by='game_id',
        )
        try:
            bankroll_row = select_rows(
                'bankroll', columns='balance', order_by='date', descending=True, limit=1
            )
        except MissingTableError:
            bankroll_row = pd.DataFrame()

        if preds.empty:
            return {}

        total = len(preds)
        correct = int(pd.to_numeric(preds['correct']).sum())
        total_pl = float(pd.to_numeric(preds['profit_loss'], errors='coerce').sum())
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

def run_workflow(send_text=True, trigger='schedule'):
    """
    Full daily workflow:
      1. Run pipeline.bat
      2. Run predict.bat
      3. Build + send SMS summary
      4. Log results to workflow_log
    trigger is 'schedule' from the CLI (Task Scheduler) and 'manual' from Run now.
    Returns a dict with status info.
    """
    run_date = date.today().strftime('%Y-%m-%d')
    started_at = datetime.now().astimezone().isoformat(timespec='seconds')

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
    finished_at = datetime.now().astimezone().isoformat(timespec='seconds')
    overall_status = 'success' if (pipeline_ok and predict_ok) else 'partial' if (pipeline_ok or predict_ok) else 'failed'
    notes = []
    if not pipeline_ok:
        notes.append('pipeline failed')
    if not predict_ok:
        notes.append('predict failed')
    if send_text and not sms_sent:
        notes.append('sms not sent')

    log_run(run_date, started_at, finished_at, overall_status,
            pipeline_ok, predict_ok, sms_sent, ', '.join(notes),
            kind='manual', trigger=trigger, log_tail=pipeline_out + predict_out)

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
        _workflow_thread = threading.Thread(
            target=run_workflow, kwargs={'trigger': 'manual'}, daemon=True
        )
        _workflow_thread.start()
        return True, "Workflow started"


def workflow_is_running():
    return _workflow_thread is not None and _workflow_thread.is_alive()


if __name__ == '__main__':
    run_workflow()
