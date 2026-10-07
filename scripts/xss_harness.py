"""Serve the real dashboard with hostile strings in every text field the UI renders.

Usage (from the repo root):  venv\\Scripts\\python scripts\\xss_harness.py [port]

The app runs with NBA_SCHEMA_V2=true over the sample season's fake tables (no network, no
Supabase), with script-breaking payloads injected into team codes, picks, sportsbook names,
model names and pipeline notes. Each payload only calls console.log('XSS-FIRED-<n>'), so a
browser check can count them without a dialog blocking automation. Open / (no ?sample=1):
Games, a past night, a drawer and Performance all render API data.
"""
import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ["SUPABASE_URL"] = "http://127.0.0.1:9"
os.environ["SUPABASE_SECRET_KEY"] = "xss-harness-dummy"
os.environ["NBA_SCHEMA_V2"] = "true"
os.environ.pop("ALLOW_RUN_WORKFLOW", None)

import build_sample_data as sample  # noqa: E402

P = {
    1: "<img src=x onerror=\"console.log('XSS-FIRED-1')\">",
    2: "\"><svg onload=\"console.log('XSS-FIRED-2')\">",
    3: "</script><script>console.log('XSS-FIRED-3')</script>",
    4: "'><img src=x onerror=console.log('XSS-FIRED-4')>",
    5: "<iframe srcdoc=\"<script>parent.console.log('XSS-FIRED-5')</script>\">",
    6: "javascript:console.log('XSS-FIRED-6')",
}


def hostile_tables():
    history, targets = sample.build_history()
    tables, tonight = sample.build_tables(history, targets)
    preds = tables.predictions
    by_id = {r["game_id"]: r for r in preds}
    t0, t1 = tonight[0].game_id, tonight[1].game_id
    # Tonight: hostile team codes, pick and book on two games.
    by_id[t0].update(home_team=P[1], predicted_winner=P[1], bet_placed=P[1], bookmaker=P[2])
    by_id[t1].update(away_team=P[3], bookmaker=P[4])
    for row in tables.book_odds:
        if row["game_id"] == t0 and row["bookmaker"] == "FanDuel":
            row["bookmaker"] = P[2]
    # Last night and the log: hostile codes on a settled game.
    nov16 = [r for r in preds if r["game_date"] == "2026-11-16"]
    nov16[0].update(away_team=P[5], bookmaker=P[6])
    nov16[1].update(home_team=P[4], predicted_winner=P[4])
    tables.model_runs[0]["production_model"] = P[1]
    tables.model_runs[0]["leaderboard"][1]["model"] = P[1]
    tables.workflow_log[0]["notes"] = P[3]
    tables.workflow_log[1]["notes"] = P[5]
    return tables, t0, [g.game_id for g in tonight]


def hostile_live_board(game_ids):
    """/api/live-scores without the network: a fake upstream whose status and clock text is
    hostile. The proxy builds every clock itself, so none of it may reach the page."""
    raw = []
    for i, game_id in enumerate(game_ids):
        status = 2 if i == 0 else 3 if i == 1 else 1
        raw.append({"gameId": game_id, "gameStatus": status, "gameStatusText": P[i % 6 + 1],
                    "period": 3 if status == 2 else 4 if status == 3 else 0,
                    "gameClock": P[2] if status == 2 else "",
                    "homeTeam": {"teamTricode": P[1], "score": 88 if status > 1 else 0},
                    "awayTeam": {"teamTricode": P[3], "score": 80 if status > 1 else 0}})
    body = {"scoreboard": {"gameDate": "2026-11-17", "games": raw}}

    class Response:
        status_code = 200

        def json(self):
            return body

    return sample.dashboard.live_scores.LiveScoreboard(http_get=lambda *a, **k: Response())


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5058
    tables, first_game, tonight_ids = hostile_tables()
    print(f"hostile game id: {first_game}")
    fake = sample.FakeSelect(tables.as_dict())
    now = datetime(2026, 11, 18, 2, 5, tzinfo=timezone.utc)
    with patch.object(sample.dashboard, "select_rows", fake), \
            patch.object(sample.dashboard, "today_et", lambda: date(2026, 11, 17)), \
            patch.object(sample.dashboard, "now_utc", lambda: now),             patch.object(sample.dashboard, "LIVE_SCOREBOARD", hostile_live_board(tonight_ids)):
        sample.dashboard.app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
