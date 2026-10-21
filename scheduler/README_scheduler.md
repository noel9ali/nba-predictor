# Scheduler Migration Guide

The daily workflow currently runs via **Windows Task Scheduler**. This guide shows how to swap it out for any other scheduler without changing the core logic.

The scheduler only calls one command:

```
python daily_workflow.py
```

All business logic lives in `daily_workflow.py` and `app.py` — the scheduler is just the trigger.

---

## Current: Windows Task Scheduler

**Setup:** Run once as Administrator:
```powershell
powershell -ExecutionPolicy Bypass -File scheduler\task_scheduler_setup.ps1
```

This registers a job named `NBA-Predictor-Daily` that fires at **6:00 AM** daily.

**Manual test run:**
```powershell
Start-ScheduledTask -TaskName "NBA-Predictor-Daily"
```

**Remove:**
```powershell
Unregister-ScheduledTask -TaskName "NBA-Predictor-Daily" -Confirm:$false
```

### Injury report snapshots (player-data work)

A second, independent job, `NBA-Predictor-Injury-Snapshot`, archives the official NBA injury report. It runs
`scheduler\run_injury_snapshot.bat` (that is, `python -m src.injuries --snapshot`) every 30 minutes from 11:00
to 23:00. The morning pipeline (`run_pipeline.bat`) and `run_predict.bat` also take one snapshot each.
A failed snapshot is logged and never fails the pipeline.

**Setup** (registers the job for the checkout the script lives in):
```powershell
powershell -ExecutionPolicy Bypass -File scheduler\register_injury_snapshot_task.ps1
```

Equivalent `schtasks` command (replace the path with your checkout):
```
schtasks /Create /TN "NBA-Predictor-Injury-Snapshot" /SC DAILY /ST 11:00 /RI 30 /DU 12:00 /TR "cmd.exe /c C:\path\to\checkout\scheduler\run_injury_snapshot.bat" /F
```

Outputs: raw PDFs in `data\raw\injury_reports\` (the archive), parsed rows in
`data\injuries\injury_snapshots.sqlite`, unmatched names in `data\injuries\injury_unmatched.csv`,
log in `logs\injury_snapshot.log`.

**Remove:** `Unregister-ScheduledTask -TaskName "NBA-Predictor-Injury-Snapshot" -Confirm:$false`

### Morning stage and evening predict stage

The workflow runs in two stages so the availability (injury-aware) model sees game-day injury reports. Teams
submit their reports during the day, so at 06:00 most statuses for tonight's games are missing and predicting then
would treat those players as available.

| Task | When | Runs | Does |
|---|---|---|---|
| `NBA-Predictor-Daily` | 6:00 AM | `run_daily.bat` = `daily_workflow.py --stage morning` | collect, settle yesterday, features, results push to ntfy + daily summary email (`workflow_log.kind = 'morning'`) |
| `NBA-Predictor-Predict` | every 15 min, 10:05-22:05 | `run_predict_stage.bat` = `daily_workflow.py --stage predict` | injury snapshot, then predictions, then picks pushed to ntfy (`kind = 'predict'`) |

Each predict run prices only games that tip within the next 75 minutes (`PREDICT_WINDOW_MINUTES` in
`daily_workflow.py`, passed to `predict.py` as `NBA_PREDICT_WINDOW_MINUTES`) and that have no prediction yet, so
every game is priced 60-75 minutes before tip with the newest report, whatever its tip time. A run with nothing
to price exits quietly: no push, no log row, no odds request, and no Elo/games table reads (the cheap checks run
first). `predict.py` also never prices a game that already tipped. `python daily_workflow.py` with no flag still
does everything in one go (Run now).

**API budget** (per day, 15-minute ticks 10:05-22:05 = 49 runs):

| API | Per quiet tick | Per priced tick | Limit |
|---|---|---|---|
| NBA `ScoreboardV3` (stats.nba.com) | 1 | 1 | no published limit; 1 call / 15 min |
| NBA injury report PDFs (CDN) | 0-3 (stops at the first slot already on disk; 0.4 s apart) | same | no published limit |
| The Odds API | 0 | 1 credit (whole slate) | 500 credits/month; capped at 12/day (`ODDS_DAILY_CALL_CAP`, `data\odds_budget.json`) |
| Supabase | 1 small read (+1 if flags change) | + Elo/games/features reads | free-tier egress |
| ntfy | 0 | 1 push per new pick | none on the public server |

**Register the predict task BEFORE the morning bat changes take effect, or no predictions get made:**
```powershell
powershell -ExecutionPolicy Bypass -File scheduler\register_predict_task.ps1
```
**Remove:** `Unregister-ScheduledTask -TaskName "NBA-Predictor-Predict" -Confirm:$false` (and change `run_daily.bat`
back to `python daily_workflow.py`).

---

## Migrating to Linux / macOS cron

1. SSH into your server and activate your virtualenv.
2. Edit crontab:
   ```
   crontab -e
   ```
3. Add a line (runs at 6 AM server time):
   ```
   0 6 * * * cd /path/to/nba-predictor && source venv/bin/activate && python daily_workflow.py >> logs/workflow.log 2>&1
   ```

---

## Migrating to GitHub Actions

Create `.github/workflows/daily.yml`:

```yaml
name: NBA Daily Workflow

on:
  schedule:
    - cron: '0 11 * * *'   # 11:00 UTC = 6:00 AM EST
  workflow_dispatch:         # allow manual trigger from GitHub UI

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run daily workflow
        env:
          ODDS_API_KEY:        ${{ secrets.ODDS_API_KEY }}
          NTFY_TOPIC:          ${{ secrets.NTFY_TOPIC }}
          NTFY_TOKEN:          ${{ secrets.NTFY_TOKEN }}
          SMTP_HOST:           ${{ secrets.SMTP_HOST }}
          SMTP_USER:           ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD:       ${{ secrets.SMTP_PASSWORD }}
          ALERT_EMAIL_TO:      ${{ secrets.ALERT_EMAIL_TO }}
        run: python daily_workflow.py
```

Add all secrets under **Settings → Secrets and variables → Actions**.

---

## Migrating to a Cloud Scheduler (GCP / AWS / Azure)

### Google Cloud Scheduler → Cloud Run Jobs

1. Containerise with a `Dockerfile`:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY . .
   RUN pip install -r requirements.txt
   CMD ["python", "daily_workflow.py"]
   ```
2. Push to Google Artifact Registry, create a **Cloud Run Job**.
3. Create a **Cloud Scheduler** job pointing to it with cron `0 11 * * *`.
4. Inject env vars via Secret Manager.

### AWS EventBridge → Lambda / ECS

Same pattern — wire `daily_workflow.py` as the Lambda handler or ECS task entry point, trigger via EventBridge cron rule.

---

## Environment variables needed on any platform

```
ODDS_API_KEY
NTFY_TOPIC, NTFY_TOKEN  (optional: picks and results by push)
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO, ALERT_EMAIL_FROM  (optional: daily summary by email)
FLASK_SECRET_KEY  (only needed for the web dashboard)
```

See `.env.example` for the full list.
